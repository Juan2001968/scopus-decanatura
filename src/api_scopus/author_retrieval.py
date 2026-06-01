"""
Lógica de alto nivel para recuperar y procesar datos de autores desde
la API de Scopus.

Usa :class:`~src.api_scopus.client.ScopusClient` internamente para las
llamadas HTTP y provee funciones de parseo que transforman las respuestas
JSON crudas de la API en estructuras limpias de Python.

Funciones de parseo
-------------------
- **parse_author_profile**: Author Retrieval -> dict limpio con h-index,
  variantes de nombre, subject areas.
- **parse_author_search**: Author Search -> lista de dicts.
- **parse_publication_eids**: Publications Search -> lista de EIDs.

Funciones de alto nivel
-----------------------
- **retrieve_author_by_id**: consulta + parseo por Scopus Author ID.
- **retrieve_author_by_orcid**: busqueda + parseo por ORCID.
- **retrieve_author_publications_eids**: lista de EIDs de un autor.

Orquestadores
-------------
- **enrich_all_professors**: enriquece DataFrames de profesores con datos
  de la API (h-index, Author IDs nuevos, EIDs de publicaciones).
- **strengthen_author_links**: fortalece vinculos publicacion-profesor
  usando los EIDs recuperados de la API.
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.api_scopus.client import ScopusClient
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SLEEP_BETWEEN_CALLS = 0.5
"""Pausa en segundos entre llamadas a la API para respetar rate limits."""

_PROGRESS_LOG_INTERVAL = 10
"""Cada cuantos perfiles consultados se loguea el progreso."""


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _safe_int(value, default: int = 0) -> int:
    """Convierte un valor a int de forma segura.

    Parameters
    ----------
    value:
        Valor a convertir (puede ser str, int, float, None).
    default:
        Valor por defecto si la conversion falla.

    Returns
    -------
    int
        Valor convertido o ``default``.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _clean_author_id(raw_id: str) -> str:
    """Limpia el prefijo ``AUTHOR_ID:`` de un identificador de Scopus.

    Parameters
    ----------
    raw_id:
        Identificador crudo (ej. ``"AUTHOR_ID:56501378100"``).

    Returns
    -------
    str
        Author ID limpio (ej. ``"56501378100"``), o cadena vacia.

    Example
    -------
    >>> _clean_author_id("AUTHOR_ID:56501378100")
    '56501378100'
    """
    if not raw_id:
        return ""
    return re.sub(r"^AUTHOR_ID:\s*", "", str(raw_id)).strip()


def _clean_eid(raw_eid: str) -> str:
    """Normaliza un EID eliminando prefijos como ``SCOPUS_ID:``.

    Parameters
    ----------
    raw_eid:
        EID crudo (puede venir como ``"2-s2.0-85012345678"`` o
        ``"SCOPUS_ID:2-s2.0-85012345678"``).

    Returns
    -------
    str
        EID normalizado (ej. ``"2-s2.0-85012345678"``).

    Example
    -------
    >>> _clean_eid("SCOPUS_ID:2-s2.0-85012345678")
    '2-s2.0-85012345678'
    """
    if not raw_eid:
        return ""
    return re.sub(r"^SCOPUS_ID:\s*", "", str(raw_eid)).strip()


def _format_name(surname: str, given_name: str) -> str:
    """Formatea un nombre como ``"Surname, Given-name"``.

    Parameters
    ----------
    surname:
        Apellido(s).
    given_name:
        Nombre(s).

    Returns
    -------
    str
        Nombre formateado, o cadena vacia si ambos son vacios.
    """
    parts = [p for p in (surname, given_name) if p]
    return ", ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Parseo de respuestas de la API
# ---------------------------------------------------------------------------


def parse_author_profile(raw_response: dict) -> Optional[dict]:
    """Parsea el JSON crudo de Author Retrieval y extrae un dict limpio.

    Extrae con ``.get()`` defensivo todos los campos relevantes del
    endpoint ``/content/author/author_id/{id}?view=ENHANCED``.

    Parameters
    ----------
    raw_response:
        JSON completo retornado por
        :meth:`~src.api_scopus.client.ScopusClient.author_retrieval`.

    Returns
    -------
    dict or None
        Diccionario con keys:

        - ``scopus_author_id`` (str)
        - ``h_index`` (int)
        - ``citation_count`` (int)
        - ``cited_by_count`` (int)
        - ``document_count`` (int)
        - ``nombre_preferido`` (str): ``"Surname, Given-name"``
        - ``variantes_nombre`` (list[str])
        - ``subject_areas`` (list[str])

        Retorna ``None`` si ``raw_response`` es ``None`` o no tiene
        la estructura esperada.

    Example
    -------
    >>> profile = parse_author_profile(api_response)
    >>> profile["h_index"]
    12
    """
    if not raw_response or not isinstance(raw_response, dict):
        return None

    retrieval_list = raw_response.get("author-retrieval-response")
    if not retrieval_list or not isinstance(retrieval_list, list):
        logger.warning(
            "Respuesta sin 'author-retrieval-response' o formato "
            "inesperado"
        )
        return None

    entry = retrieval_list[0]
    if not isinstance(entry, dict):
        logger.warning(
            "Primera entrada de author-retrieval-response no es dict"
        )
        return None

    # --- Coredata ---
    coredata = entry.get("coredata") or {}

    # --- Author profile / preferred-name ---
    profile = entry.get("author-profile") or {}
    preferred = profile.get("preferred-name") or {}

    nombre_preferido = _format_name(
        preferred.get("surname", ""),
        preferred.get("given-name", ""),
    )

    # --- Name variants ---
    name_variants_raw = profile.get("name-variant") or []
    # La API puede retornar un dict si hay solo una variante
    if isinstance(name_variants_raw, dict):
        name_variants_raw = [name_variants_raw]

    main_id = _clean_author_id(coredata.get("dc:identifier", ""))

    variantes: List[str] = []
    alias_ids: List[str] = []  # AUIDs distintos al ID principal → perfil fragmentado

    for nv in name_variants_raw:
        if not isinstance(nv, dict):
            continue
        nombre = _format_name(
            nv.get("surname", ""),
            nv.get("given-name", ""),
        )
        if nombre:
            variantes.append(nombre)
        # Detectar perfiles fragmentados por @auid diferente al ID principal
        nv_auid = _clean_author_id(str(nv.get("@auid", "")))
        if nv_auid and nv_auid != main_id and nv_auid not in alias_ids:
            alias_ids.append(nv_auid)

    # --- Subject areas ---
    sa_container = entry.get("subject-areas") or {}
    sa_raw = sa_container.get("subject-area") or []
    if isinstance(sa_raw, dict):
        sa_raw = [sa_raw]

    areas: List[str] = []
    for sa in sa_raw:
        if isinstance(sa, dict):
            area_name = sa.get("$", "")
            if area_name:
                areas.append(area_name)

    result = {
        "scopus_author_id": main_id,
        "h_index": _safe_int(entry.get("h-index")),
        "citation_count": _safe_int(coredata.get("citation-count")),
        "cited_by_count": _safe_int(coredata.get("cited-by-count")),
        "document_count": _safe_int(coredata.get("document-count")),
        "nombre_preferido": nombre_preferido,
        "variantes_nombre": variantes,
        "subject_areas": areas,
        # IDs alternativos encontrados en name-variant/@auid (perfil fragmentado)
        "alias_ids": alias_ids,
    }

    logger.debug(
        "Author profile parseado: id=%s, h_index=%d, docs=%d",
        result["scopus_author_id"],
        result["h_index"],
        result["document_count"],
    )

    return result


def parse_author_search(raw_response: dict) -> List[dict]:
    """Parsea el JSON de Author Search y extrae lista de autores.

    Procesa la respuesta del endpoint
    ``/content/search/author?query=ORCID(...)`` extrayendo los campos
    principales de cada resultado.

    Parameters
    ----------
    raw_response:
        JSON completo retornado por
        :meth:`~src.api_scopus.client.ScopusClient.author_search_by_orcid`.

    Returns
    -------
    list[dict]
        Lista de diccionarios con keys:

        - ``scopus_author_id`` (str)
        - ``nombre`` (str): ``"surname, given-name"``
        - ``orcid`` (str): ORCID si viene en la respuesta, cadena
          vacia si no.
        - ``document_count`` (int)

        Puede ser lista vacia si no hay resultados.

    Example
    -------
    >>> results = parse_author_search(api_response)
    >>> results[0]["scopus_author_id"]
    '56501378100'
    """
    if not raw_response or not isinstance(raw_response, dict):
        return []

    search_results = raw_response.get("search-results") or {}
    entries = search_results.get("entry") or []

    if isinstance(entries, dict):
        entries = [entries]

    # Verificar totalResults — la API retorna entry con @error si 0
    total_str = search_results.get("opensearch:totalResults", "0")
    if _safe_int(total_str) == 0:
        return []

    authors: List[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Detectar entradas de error (sin resultados reales)
        if entry.get("@error"):
            continue

        pref_name = entry.get("preferred-name") or {}
        nombre = _format_name(
            pref_name.get("surname", ""),
            pref_name.get("given-name", ""),
        )

        authors.append({
            "scopus_author_id": _clean_author_id(
                entry.get("dc:identifier", "")
            ),
            "nombre": nombre,
            "orcid": entry.get("orcid", ""),
            "document_count": _safe_int(entry.get("document-count")),
        })

    logger.debug("Author Search parseado: %d resultados", len(authors))

    return authors


def parse_publication_eids(raw_response: dict) -> List[str]:
    """Parsea el JSON de Author Publications Search y extrae EIDs.

    Procesa la respuesta del endpoint
    ``/content/search/scopus?query=AU-ID(...)`` extrayendo y
    normalizando los EIDs de cada publicacion.

    Parameters
    ----------
    raw_response:
        JSON completo retornado por
        :meth:`~src.api_scopus.client.ScopusClient.search_author_publications`.

    Returns
    -------
    list[str]
        Lista de EIDs normalizados (formato ``"2-s2.0-XXXXX"``).
        Puede ser lista vacia.

    Example
    -------
    >>> eids = parse_publication_eids(api_response)
    >>> eids[0]
    '2-s2.0-85012345678'
    """
    if not raw_response or not isinstance(raw_response, dict):
        return []

    search_results = raw_response.get("search-results") or {}
    entries = search_results.get("entry") or []

    if isinstance(entries, dict):
        entries = [entries]

    # Verificar totalResults
    total_str = search_results.get("opensearch:totalResults", "0")
    if _safe_int(total_str) == 0:
        return []

    eids: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("@error"):
            continue

        raw_eid = entry.get("eid", "")
        if not raw_eid:
            # Fallback: intentar extraer de dc:identifier
            raw_eid = entry.get("dc:identifier", "")

        cleaned = _clean_eid(raw_eid)
        if cleaned:
            eids.append(cleaned)

    logger.debug("Publication EIDs parseados: %d EIDs extraidos", len(eids))

    return eids


# ---------------------------------------------------------------------------
# Funciones de alto nivel
# ---------------------------------------------------------------------------


def retrieve_author_by_id(
    author_id: str,
    client: Optional[ScopusClient] = None,
) -> Optional[dict]:
    """Consulta un autor por su Scopus Author ID y retorna perfil parseado.

    Combina la llamada HTTP a Author Retrieval con el parseo del JSON
    de respuesta.

    Parameters
    ----------
    author_id:
        Scopus Author ID (ej. ``"56501378100"``).
    client:
        Instancia de :class:`ScopusClient`. Si es ``None``, se crea
        una nueva.

    Returns
    -------
    dict or None
        Perfil parseado (ver :func:`parse_author_profile`), o ``None``
        si el autor no existe o hay error de conexion.

    Example
    -------
    >>> profile = retrieve_author_by_id("56501378100")
    >>> profile["h_index"]
    12
    """
    if not author_id:
        logger.warning("author_id vacio en retrieve_author_by_id")
        return None

    if client is None:
        client = ScopusClient()

    try:
        raw = client.author_retrieval(author_id)
    except (PermissionError, ConnectionError) as exc:
        logger.error(
            "Error al consultar Author Retrieval para %s: %s",
            author_id, exc,
        )
        return None

    return parse_author_profile(raw)


def retrieve_author_by_orcid(
    orcid: str,
    client: Optional[ScopusClient] = None,
) -> List[dict]:
    """Busca autores en Scopus por ORCID y retorna perfiles parseados.

    Util para descubrir Author IDs que no esten en los CSV de
    profesores.

    Parameters
    ----------
    orcid:
        ORCID del autor (ej. ``"0000-0003-2699-398X"``).
    client:
        Instancia de :class:`ScopusClient`. Si es ``None``, se crea
        una nueva.

    Returns
    -------
    list[dict]
        Lista de perfiles encontrados (ver :func:`parse_author_search`).
        Puede ser lista vacia.

    Example
    -------
    >>> results = retrieve_author_by_orcid("0000-0003-2699-398X")
    >>> len(results)
    1
    """
    if not orcid:
        logger.warning("ORCID vacio en retrieve_author_by_orcid")
        return []

    if client is None:
        client = ScopusClient()

    try:
        raw = client.author_search_by_orcid(orcid)
    except (PermissionError, ConnectionError) as exc:
        logger.error(
            "Error al buscar por ORCID %s: %s", orcid, exc,
        )
        return []

    return parse_author_search(raw)


def retrieve_author_publications_eids(
    author_id: str,
    client: Optional[ScopusClient] = None,
) -> List[str]:
    """Recupera la lista de EIDs de publicaciones de un autor.

    Parameters
    ----------
    author_id:
        Scopus Author ID.
    client:
        Instancia de :class:`ScopusClient`. Si es ``None``, se crea
        una nueva.

    Returns
    -------
    list[str]
        Lista de EIDs normalizados. Puede ser lista vacia.

    Example
    -------
    >>> eids = retrieve_author_publications_eids("56501378100")
    >>> "2-s2.0-85012345678" in eids
    True
    """
    if not author_id:
        logger.warning(
            "author_id vacio en retrieve_author_publications_eids"
        )
        return []

    if client is None:
        client = ScopusClient()

    try:
        raw = client.search_author_publications(author_id)
    except (PermissionError, ConnectionError) as exc:
        logger.error(
            "Error al buscar publicaciones de %s: %s",
            author_id, exc,
        )
        return []

    return parse_publication_eids(raw)


# ---------------------------------------------------------------------------
# Orquestadores
# ---------------------------------------------------------------------------


def enrich_all_professors(
    df_profesores: pd.DataFrame,
    df_autores_scopus: pd.DataFrame,
    client: Optional[ScopusClient] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Orquestador: enriquece profesores consultando la API de Scopus.

    Para cada profesor con Author ID conocido, recupera h-index,
    variantes de nombre, areas tematicas y EIDs de publicaciones.
    Para profesores sin Author ID, intenta descubrirlo por ORCID.

    El flujo consta de 4 fases:

    1. **Enriquecer perfiles existentes**: para cada Author ID en
       ``df_autores_scopus``, consultar Author Retrieval y Publications
       Search.
    2. **Descubrir Author IDs**: para profesores cuyo ORCID no tiene
       Author ID asociado, buscar en Author Search.
    3. **Actualizar h-index**: propagar el maximo h-index encontrado
       a ``df_profesores``.
    4. **Construir df_author_eids**: consolidar todos los EIDs de
       publicaciones por autor.

    Parameters
    ----------
    df_profesores:
        DataFrame de profesores con al menos columnas ``orcid`` y
        ``nombre_normalizado``.
    df_autores_scopus:
        DataFrame de perfiles Scopus con al menos columnas
        ``scopus_author_id``, ``nombre_scopus``, ``orcid``.
    client:
        Instancia de :class:`ScopusClient`. Si es ``None``, se crea
        una nueva.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
        - ``df_profesores_enriched``: copia con ``h_index`` y
          ``h_index_fecha`` actualizados.
        - ``df_autores_scopus_enriched``: copia con posibles nuevos
          Author IDs descubiertos y datos actualizados
          (``subject_area``, ``numero_documentos_scopus``).
        - ``df_author_eids``: DataFrame nuevo con columnas
          ``scopus_author_id``, ``orcid``, ``eid`` — una fila por
          cada EID de publicacion asociada al autor.

    Example
    -------
    >>> df_p, df_a, df_e = enrich_all_professors(
    ...     df_profesores, df_autores_scopus
    ... )
    >>> df_e.columns.tolist()
    ['scopus_author_id', 'orcid', 'eid']
    """
    if client is None:
        client = ScopusClient()

    logger.info(
        "Iniciando enriquecimiento: %d profesores, %d perfiles Scopus",
        len(df_profesores), len(df_autores_scopus),
    )

    # --- Copias de trabajo ---
    df_prof = df_profesores.copy()
    df_aut = df_autores_scopus.copy()

    # Asegurar columnas necesarias en profesores
    if "h_index" not in df_prof.columns:
        df_prof["h_index"] = pd.NA
    if "h_index_fecha" not in df_prof.columns:
        df_prof["h_index_fecha"] = pd.NaT

    # Asegurar columnas en autores_scopus
    if "subject_area" not in df_aut.columns:
        df_aut["subject_area"] = ""
    if "numero_documentos_scopus" not in df_aut.columns:
        df_aut["numero_documentos_scopus"] = 0

    # ---------------------------------------------------------------
    # Fase 1: Enriquecer Author IDs existentes
    # ---------------------------------------------------------------
    h_index_map: Dict[str, int] = {}
    author_eids_rows: List[dict] = []
    enriched_count = 0
    failed_count = 0

    # Filtrar filas con scopus_author_id valido
    mask_has_id = (
        df_aut["scopus_author_id"].notna()
        & (df_aut["scopus_author_id"].astype(str).str.strip() != "")
    )
    rows_with_auth_id = df_aut.loc[mask_has_id]
    total_profiles = len(rows_with_auth_id)

    logger.info(
        "Fase 1: Consultando %d perfiles Scopus existentes...",
        total_profiles,
    )

    for idx, row in rows_with_auth_id.iterrows():
        auth_id = str(row["scopus_author_id"]).strip()
        orcid = str(row.get("orcid", "")).strip()

        # --- Consultar perfil del autor ---
        profile = retrieve_author_by_id(auth_id, client)
        time.sleep(_SLEEP_BETWEEN_CALLS)

        if profile:
            # Actualizar h-index (guardar el maximo por ORCID)
            h = profile.get("h_index", 0)
            if orcid:
                h_index_map[orcid] = max(
                    h_index_map.get(orcid, 0), h,
                )

            # Actualizar datos en autores_scopus
            areas_str = "; ".join(profile.get("subject_areas", []))
            if areas_str:
                df_aut.at[idx, "subject_area"] = areas_str

            doc_count = profile.get("document_count", 0)
            if doc_count:
                df_aut.at[idx, "numero_documentos_scopus"] = doc_count

            enriched_count += 1
        else:
            failed_count += 1

        # --- Consultar EIDs de publicaciones ---
        eids = retrieve_author_publications_eids(auth_id, client)
        time.sleep(_SLEEP_BETWEEN_CALLS)

        for eid in eids:
            author_eids_rows.append({
                "scopus_author_id": auth_id,
                "orcid": orcid,
                "eid": eid,
            })

        # --- Progreso ---
        processed = enriched_count + failed_count
        if processed > 0 and processed % _PROGRESS_LOG_INTERVAL == 0:
            logger.info(
                "Progreso fase 1: %d/%d perfiles consultados "
                "(%d exitosos, %d fallidos)",
                processed, total_profiles,
                enriched_count, failed_count,
            )

    logger.info(
        "Fase 1 completada: %d exitosos, %d fallidos de %d perfiles",
        enriched_count, failed_count, total_profiles,
    )

    # ---------------------------------------------------------------
    # Fase 2: Descubrir Author IDs por ORCID
    # ---------------------------------------------------------------
    orcids_with_auth_id = set(
        df_aut.loc[mask_has_id, "orcid"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
    )
    all_orcids = set(
        df_prof["orcid"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
    )
    orcids_without_auth_id = all_orcids - orcids_with_auth_id
    orcids_without_auth_id.discard("")

    discovered_count = 0

    if orcids_without_auth_id:
        logger.info(
            "Fase 2: Buscando Author IDs para %d profesores sin "
            "Auth_ID via ORCID...",
            len(orcids_without_auth_id),
        )

        for orcid in sorted(orcids_without_auth_id):
            results = retrieve_author_by_orcid(orcid, client)
            time.sleep(_SLEEP_BETWEEN_CALLS)

            for result in results:
                new_auth_id = result.get("scopus_author_id", "")
                if not new_auth_id:
                    continue

                # Agregar nueva fila a autores_scopus
                new_row = pd.DataFrame([{
                    "scopus_author_id": new_auth_id,
                    "nombre_scopus": result.get("nombre", ""),
                    "orcid": orcid,
                    "subject_area": "",
                    "numero_documentos_scopus": result.get(
                        "document_count", 0
                    ),
                }])
                df_aut = pd.concat(
                    [df_aut, new_row], ignore_index=True,
                )
                discovered_count += 1

                logger.info(
                    "Author ID descubierto: %s para ORCID %s (%s)",
                    new_auth_id, orcid, result.get("nombre", ""),
                )

                # Recuperar EIDs del nuevo Author ID
                eids = retrieve_author_publications_eids(
                    new_auth_id, client,
                )
                time.sleep(_SLEEP_BETWEEN_CALLS)

                for eid in eids:
                    author_eids_rows.append({
                        "scopus_author_id": new_auth_id,
                        "orcid": orcid,
                        "eid": eid,
                    })
    else:
        logger.info(
            "Fase 2: Todos los profesores ya tienen Author ID "
            "asociado"
        )

    # ---------------------------------------------------------------
    # Fase 3: Actualizar h-index en profesores
    # ---------------------------------------------------------------
    today = date.today()
    updated_h_count = 0

    # Asegurar dtype compatible para h_index_fecha
    if df_prof["h_index_fecha"].dtype.name == "datetime64[ns]":
        today_val = pd.Timestamp(today)
    else:
        today_val = today

    for orcid, h_val in h_index_map.items():
        mask = df_prof["orcid"].astype(str).str.strip() == orcid
        if mask.any():
            df_prof.loc[mask, "h_index"] = h_val
            df_prof.loc[mask, "h_index_fecha"] = today_val
            updated_h_count += 1

    logger.info(
        "Fase 3: h-index actualizado para %d profesores",
        updated_h_count,
    )

    # ---------------------------------------------------------------
    # Fase 4: Construir df_author_eids
    # ---------------------------------------------------------------
    if author_eids_rows:
        df_eids = pd.DataFrame(
            author_eids_rows,
            columns=["scopus_author_id", "orcid", "eid"],
        )
        # Eliminar duplicados (mismo author_id + eid)
        df_eids = df_eids.drop_duplicates(
            subset=["scopus_author_id", "eid"],
        ).reset_index(drop=True)
    else:
        df_eids = pd.DataFrame(
            columns=["scopus_author_id", "orcid", "eid"],
        )

    # --- Resumen final ---
    total_eids = len(df_eids)
    unique_eids = df_eids["eid"].nunique() if not df_eids.empty else 0

    logger.info(
        "Enriquecimiento completado: "
        "%d perfiles enriquecidos, %d fallidos, "
        "%d Author IDs nuevos descubiertos, "
        "%d EIDs de publicaciones recuperados (%d unicos)",
        enriched_count, failed_count,
        discovered_count,
        total_eids, unique_eids,
    )

    return df_prof, df_aut, df_eids


def strengthen_author_links(
    df_links_existing: pd.DataFrame,
    df_author_eids: pd.DataFrame,
) -> pd.DataFrame:
    """Fortalece vinculos publicacion-profesor con EIDs de la API.

    Compara los EIDs recuperados de la API de Scopus contra los
    vinculos existentes (generados por name matching) para:

    1. Agregar nuevos vinculos donde la API confirma autoria pero el
       name matching no lo detecto (``metodo_vinculacion='api_eid'``).
    2. Confirmar vinculos existentes (log informativo).
    3. Registrar EIDs de la API que no estan en la base de
       publicaciones.

    Parameters
    ----------
    df_links_existing:
        DataFrame de vinculos existentes con columnas ``eid``,
        ``orcid``, ``metodo_vinculacion``, ``score_similitud``,
        ``nombre_autor_original``.
    df_author_eids:
        DataFrame con columnas ``scopus_author_id``, ``orcid``,
        ``eid`` — generado por :func:`enrich_all_professors`.

    Returns
    -------
    pd.DataFrame
        DataFrame de vinculos actualizado (concatenacion de existentes
        + nuevos), con las mismas columnas que ``df_links_existing``.

    Example
    -------
    >>> df_updated = strengthen_author_links(df_links, df_eids)
    >>> df_updated["metodo_vinculacion"].value_counts()
    exacto          120
    fuzzy            45
    api_eid          30
    fuzzy_afiliacion  5
    """
    if df_author_eids.empty:
        logger.info(
            "No hay EIDs de la API para fortalecer vinculos"
        )
        return df_links_existing.copy()

    # Construir set de EIDs conocidos en la base de publicaciones
    # (inferido de los vinculos existentes)
    known_eids: set = set()
    if not df_links_existing.empty and "eid" in df_links_existing.columns:
        known_eids = set(
            df_links_existing["eid"]
            .dropna()
            .astype(str)
            .str.strip()
            .unique()
        )

    # Construir set de pares (eid, orcid) ya vinculados
    existing_pairs: set = set()
    if not df_links_existing.empty:
        for _, row in df_links_existing.iterrows():
            eid = str(row.get("eid", "")).strip()
            orcid = str(row.get("orcid", "")).strip()
            if eid and orcid:
                existing_pairs.add((eid, orcid))

    new_links: List[dict] = []
    confirmed_count = 0
    new_count = 0
    not_in_base_count = 0

    for _, row in df_author_eids.iterrows():
        eid = str(row.get("eid", "")).strip()
        orcid = str(row.get("orcid", "")).strip()

        if not eid or not orcid:
            continue

        # Verificar si el EID existe en la base de publicaciones
        if eid not in known_eids:
            not_in_base_count += 1
            continue

        # Verificar si ya existe el vinculo
        if (eid, orcid) in existing_pairs:
            confirmed_count += 1
            continue

        # Nuevo vinculo descubierto por API
        new_links.append({
            "eid": eid,
            "orcid": orcid,
            "metodo_vinculacion": "api_eid",
            "score_similitud": 1.0,
            "nombre_autor_original": "",
        })
        existing_pairs.add((eid, orcid))
        new_count += 1

    # Construir resultado
    if new_links:
        df_new = pd.DataFrame(new_links)
        df_result = pd.concat(
            [df_links_existing, df_new], ignore_index=True,
        )
    else:
        df_result = df_links_existing.copy()

    logger.info(
        "Fortalecimiento completado: "
        "%d vinculos nuevos por API, "
        "%d vinculos confirmados, "
        "%d EIDs no encontrados en la base",
        new_count, confirmed_count, not_in_base_count,
    )

    return df_result
