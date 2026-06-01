"""
PASO 2 (v2): Extracción corregida por AU-ID(), validación y exportación para Power BI.

AUDITORÍA DE LA VERSIÓN ANTERIOR (02_extraer_validar_exportar.py)
------------------------------------------------------------------
1. Query: AU-ID(id1) OR AU-ID(id2)  ✔ correcto
2. Verificación post-extracción del AU-ID: AUSENTE  → CORREGIDO en v2
3. Deduplicación EID: parcial (set por profesor)    → REFORZADA en v2
4. Filtro de años en query: AUSENTE                 → AÑADIDO en v2
5. Filtro de años post-extracción: AUSENTE          → AÑADIDO en v2
6. Parentización OR + AND(año): latente             → CORREGIDA en v2
7. docs_en_perfil para fragmentados: usaba max()   → CORREGIDO: usa totalResults

CAMBIOS PRINCIPALES v2
----------------------
- extraer_publicaciones_profesor(): función centralizada con:
  a) Query (AU-ID(id1) OR AU-ID(id2)) AND PUBYEAR > X AND PUBYEAR < Y
  b) Verificación: AU-ID del profesor debe estar en author_full_names del doc local
  c) Deduplicación explícita por EID
  d) Doble filtro de año (query + post-extracción)
- docs_en_perfil = opensearch:totalResults del AU-ID query (sin filtro año)
  para comparación justa con docs_extraidos (con filtro año se reporta por separado)
- calidad_matching_v2.csv: estados OK / REVISAR / CRITICO + porcentaje_precision
- Salidas con sufijo _v2 (no sobreescribe versión anterior)

Uso
---
    python -m scripts.02_extraer_validar_exportar_v2
"""

from __future__ import annotations

import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA_PROCESSED_DIR, LOGS_DIR, ROLLING_WINDOW_YEARS
from src.api_scopus.author_retrieval import retrieve_author_by_id
from src.api_scopus.client import ScopusClient
from src.etl.clean import run_cleaning_pipeline
from src.etl.enrich_sources import run_enrichment
from src.etl.ingest_publications import load_all_publications
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SLEEP: float = 1.0  # 1 segundo entre llamadas a la API (conservador)

# Rango de años para la ventana de análisis
_AÑO_FIN: int = datetime.now().year - 1          # último año con datos completos
_AÑO_INICIO: int = _AÑO_FIN - ROLLING_WINDOW_YEARS + 1

# Umbrales de calidad (sobre publicaciones totales, sin filtro año)
_UMBRAL_OK: int = 2
_UMBRAL_REVISAR: int = 10

_RUTA_VALIDADOS = DATA_PROCESSED_DIR / "profesores_validados.csv"

# ---------------------------------------------------------------------------
# Logger de errores de API
# ---------------------------------------------------------------------------

_api_err_logger = logging.getLogger("errores_api_v2")


def _configurar_log_errores() -> Path:
    """Crea/abre el archivo errores_api.log con timestamp de sesión."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ruta = LOGS_DIR / "errores_api.log"
    if not _api_err_logger.handlers:
        handler = logging.FileHandler(ruta, encoding="utf-8", mode="a")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | v2 | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        _api_err_logger.setLevel(logging.ERROR)
        _api_err_logger.addHandler(handler)
    return ruta


def _log_err(contexto: str, ref: str, exc: Exception) -> None:
    """Registra un error de API con contexto y timestamp."""
    _api_err_logger.error(
        "contexto=%s | ref=%s | tipo=%s | detalle=%s",
        contexto, ref, type(exc).__name__, str(exc),
    )


# ---------------------------------------------------------------------------
# Helpers de parseo
# ---------------------------------------------------------------------------


def _extraer_ids_autor(author_full_names: object) -> Set[str]:
    """Extrae los Scopus Author IDs de la columna author_full_names.

    El formato típico es: "García, J. (56013816500); López, M. (45678901234)"
    Retorna un set vacío si el campo está vacío o no tiene IDs en paréntesis.
    """
    if pd.isna(author_full_names) or not str(author_full_names).strip():
        return set()
    ids = re.findall(r"\((\d{9,15})\)", str(author_full_names))
    return set(ids)


def _ids_autor_como_str(ids: Set[str]) -> str:
    """Convierte un set de IDs a string separado por ';' para el CSV."""
    return ";".join(sorted(ids))


# ---------------------------------------------------------------------------
# Recuperación de EIDs desde la API (con paginación)
# ---------------------------------------------------------------------------


def _total_resultados(raw: dict) -> int:
    """Lee opensearch:totalResults de una respuesta de Scopus Search."""
    try:
        return int(raw.get("search-results", {}).get("opensearch:totalResults", 0))
    except (ValueError, TypeError):
        return 0


def _eids_de_pagina(raw: dict) -> List[str]:
    """Extrae los EIDs limpios de una página de resultados de Scopus Search."""
    entries = raw.get("search-results", {}).get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]

    eids: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("@error"):
            continue
        eid = str(entry.get("eid", entry.get("dc:identifier", ""))).strip()
        # Eliminar prefijo SCOPUS_ID: si lo trae la API
        eid = re.sub(r"^SCOPUS_ID:\s*", "", eid)
        if eid:
            eids.append(eid)
    return eids


def _recuperar_eids_paginado(
    query: str,
    nombre: str,
    client: ScopusClient,
) -> Tuple[List[str], int]:
    """Recupera todos los EIDs para una query dada, con paginación.

    Returns
    -------
    tuple[list[str], int]
        (lista_eids_únicos, total_declarado_por_api)
    """
    todos: List[str] = []
    start = 0
    count = 200
    total: Optional[int] = None

    while True:
        try:
            time.sleep(_SLEEP)
            raw = client.search_publications_page(query, start=start, count=count)
        except (PermissionError, ConnectionError) as exc:
            _log_err("paginado_eids", nombre, exc)
            break

        if raw is None:
            break

        if total is None:
            total = _total_resultados(raw)
            logger.info(
                "%s → AU-ID query (total API): %d publicaciones", nombre, total,
            )

        pagina = _eids_de_pagina(raw)
        todos.extend(pagina)

        start += count
        if not pagina or start >= (total or 0):
            break

    # Deduplicar preservando orden (por si la paginación devuelve solapamientos)
    unicos = list(dict.fromkeys(todos))
    return unicos, (total or 0)


# ---------------------------------------------------------------------------
# FUNCIÓN PRINCIPAL: extraer_publicaciones_profesor
# ---------------------------------------------------------------------------


def extraer_publicaciones_profesor(
    nombre: str,
    author_ids: List[str],
    df_pubs_local: pd.DataFrame,
    eid_index: "pd.DataFrame",
    client: ScopusClient,
    año_inicio: int = _AÑO_INICIO,
    año_fin: int = _AÑO_FIN,
) -> Tuple[pd.DataFrame, int, int]:
    """Extrae publicaciones verificadas de un profesor usando solo AU-ID().

    Flujo:
    1. Construye query ``(AU-ID(id1) OR AU-ID(id2)) AND PUBYEAR > X AND PUBYEAR < Y``
       Los paréntesis garantizan que el filtro de año aplica a TODOS los IDs.
    2. Recupera todos los EIDs con paginación (1 s entre llamadas).
    3. Para cada EID presente en los datos locales:
       a. Si author_full_names contiene IDs, verifica que al menos uno de los
          Author IDs del profesor esté en esa lista. Si no está, descarta el doc
          (falso positivo de la query).
       b. Si author_full_names está vacío, confía en la query AU-ID() y lo conserva.
    4. Deduplica por EID (garantía adicional).
    5. Aplica filtro de año post-extracción como doble verificación.

    Parameters
    ----------
    nombre:
        Nombre del profesor (para logs).
    author_ids:
        Lista de Scopus Author IDs del profesor.
    df_pubs_local:
        DataFrame limpio de publicaciones locales.
    eid_index:
        DataFrame de publicaciones locales indexado por 'eid' (precalculado).
    client:
        Instancia de ScopusClient.
    año_inicio:
        Primer año del rango (inclusive).
    año_fin:
        Último año del rango (inclusive).

    Returns
    -------
    tuple[pd.DataFrame, int, int]
        (df_publicaciones, docs_api_total_sin_filtro, n_descartados_verificacion)
        - df_publicaciones: una fila por publicación verificada y en rango.
        - docs_api_total_sin_filtro: totalResults de la query sin filtro año
          (para comparar con document_count del perfil en calidad_matching).
        - n_descartados_verificacion: EIDs descartados por no encontrar AU-ID
          del profesor en author_full_names.
    """
    if not author_ids:
        return pd.DataFrame(), 0, 0

    ids_set = set(author_ids)

    # -- Paso 1: Query sin filtro de año para calidad_matching (doc_count total) --
    query_sin_filtro = " OR ".join(f"AU-ID({aid})" for aid in author_ids)
    if len(author_ids) > 1:
        query_sin_filtro = f"({query_sin_filtro})"

    _, total_api_sin_filtro = _recuperar_eids_paginado(
        query_sin_filtro, f"{nombre}[sin_filtro]", client,
    )

    # -- Paso 2: Query CON filtro de año (paréntesis obligatorios alrededor del OR) --
    ids_parte = " OR ".join(f"AU-ID({aid})" for aid in author_ids)
    if len(author_ids) > 1:
        ids_parte = f"({ids_parte})"
    query_filtrada = (
        f"{ids_parte} AND PUBYEAR > {año_inicio - 1} AND PUBYEAR < {año_fin + 1}"
    )

    eids_filtrados, _ = _recuperar_eids_paginado(
        query_filtrada, f"{nombre}[{año_inicio}-{año_fin}]", client,
    )

    # -- Paso 3: Cruzar con datos locales + verificar AU-ID --
    filas: List[dict] = []
    eids_vistos: Set[str] = set()   # para deduplicación explícita (paso 4)
    n_descartados = 0
    n_no_en_local = 0

    for eid in eids_filtrados:
        # Paso 4: deduplicar
        if eid in eids_vistos:
            continue
        eids_vistos.add(eid)

        # Solo publicaciones presentes en los datos locales
        if eid not in eid_index.index:
            n_no_en_local += 1
            continue

        pub = eid_index.loc[eid]
        if isinstance(pub, pd.DataFrame):
            pub = pub.iloc[0]

        # -- Verificación post-extracción del AU-ID (punto A del enunciado) --
        ids_en_doc = _extraer_ids_autor(pub.get("author_full_names", ""))

        if ids_en_doc:
            # El documento local tiene IDs: verificar que el profesor esté
            if not ids_en_doc.intersection(ids_set):
                n_descartados += 1
                logger.debug(
                    "Descartado EID %s para %s: AU-ID del profesor no está en "
                    "author_full_names del doc local (posible falso positivo).",
                    eid, nombre,
                )
                continue
        # Si ids_en_doc está vacío, confiamos en que AU-ID() es correcto

        # -- Paso 5: Filtro de año post-extracción (doble verificación) --
        anio = pub.get("anio_publicacion")
        try:
            anio_int = int(anio)
        except (TypeError, ValueError):
            anio_int = 0

        if anio_int and not (año_inicio <= anio_int <= año_fin):
            continue  # el año de la query no siempre coincide con el del CSV local

        filas.append({
            "eid": eid,
            "titulo": pub.get("titulo", ""),
            "anio_publicacion": anio,
            "source_title": pub.get("source_title", ""),
            "issn": pub.get("issn", ""),
            "cited_by_count": pub.get("cited_by_count", 0),
            "tipo_documental": pub.get("tipo_documental", ""),
            "autor_ids_scopus": _ids_autor_como_str(ids_en_doc) or ";".join(author_ids),
        })

    if n_descartados:
        logger.warning(
            "%s → %d EIDs descartados por verificación de AU-ID en doc local",
            nombre, n_descartados,
        )
    if n_no_en_local:
        logger.info(
            "%s → %d EIDs de la API no encontrados en datos locales (omitidos)",
            nombre, n_no_en_local,
        )

    df_pub = pd.DataFrame(filas) if filas else pd.DataFrame(
        columns=[
            "eid", "titulo", "anio_publicacion", "source_title", "issn",
            "cited_by_count", "tipo_documental", "autor_ids_scopus",
        ]
    )
    return df_pub, total_api_sin_filtro, n_descartados


# ---------------------------------------------------------------------------
# Construcción de archivos de salida
# ---------------------------------------------------------------------------


def _construir_publicaciones_v2(
    df_profs: pd.DataFrame,
    df_pubs_por_orcid: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Combina publicaciones de todos los profesores en un único DataFrame."""
    partes: List[pd.DataFrame] = []

    for _, prof_row in df_profs.iterrows():
        orcid = str(prof_row.get("orcid", "")).strip()
        nombre = str(prof_row.get("nombre", "")).strip()
        depto = str(prof_row.get("departamento", "")).strip()

        df_pub = df_pubs_por_orcid.get(orcid, pd.DataFrame())
        if df_pub.empty:
            continue

        df_pub = df_pub.copy()
        df_pub["profesor_asignado"] = nombre
        df_pub["departamento"] = depto
        df_pub["orcid_profesor"] = orcid
        partes.append(df_pub)

    if not partes:
        return pd.DataFrame()

    df_out = pd.concat(partes, ignore_index=True)

    # Ordenar para facilitar revisión en Power BI
    df_out = df_out.sort_values(
        ["profesor_asignado", "anio_publicacion"], ascending=[True, False],
    ).reset_index(drop=True)

    logger.info(
        "publicaciones_v2.csv: %d filas — %d EIDs únicos, %d profesores",
        len(df_out),
        df_out["eid"].nunique(),
        df_out["profesor_asignado"].nunique(),
    )
    return df_out


def _construir_calidad_v2(
    df_profs: pd.DataFrame,
    docs_api_total_por_orcid: Dict[str, int],
    docs_extraidos_por_orcid: Dict[str, int],
    docs_perfil_por_orcid: Dict[str, int],
    descartados_por_orcid: Dict[str, int],
) -> pd.DataFrame:
    """Genera calidad_matching_v2.csv.

    Columnas:
      profesor | departamento | author_ids | docs_perfil_scopus |
      docs_api_total | docs_extraidos | diferencia | porcentaje_precision | estado

    Estado:
      OK       → diferencia ≤ 2
      REVISAR  → 3 ≤ diferencia ≤ 10
      CRITICO  → diferencia > 10 o sin Author ID
    """
    filas: List[dict] = []

    for _, row in df_profs.iterrows():
        orcid = str(row.get("orcid", "")).strip()
        nombre = str(row.get("nombre", "")).strip()
        depto = str(row.get("departamento", "")).strip()
        scopus_ids = str(row.get("scopus_ids", "")).strip()

        if not scopus_ids:
            filas.append({
                "profesor": nombre,
                "departamento": depto,
                "author_ids": "",
                "docs_perfil_scopus": 0,
                "docs_api_total": 0,
                "docs_extraidos": 0,
                "diferencia": 0,
                "porcentaje_precision": 0.0,
                "eids_descartados_verificacion": 0,
                "estado": "CRITICO",
            })
            continue

        # docs_api_total: totalResults de AU-ID() sin filtro año (equivale a "todo el histórico")
        docs_api = docs_api_total_por_orcid.get(orcid, 0)
        # docs_perfil_scopus: document_count del Author Retrieval (independiente)
        docs_perfil = docs_perfil_por_orcid.get(orcid, 0)
        # docs_extraidos: publicaciones que pasaron todos los filtros (año + verificación AU-ID)
        docs_ext = docs_extraidos_por_orcid.get(orcid, 0)
        descartados = descartados_por_orcid.get(orcid, 0)

        # La diferencia clave es entre lo que devuelve la query (sin año) y el perfil
        # Esto revela si el AU-ID() está trayendo documentos "extra" no en el perfil
        diferencia = abs(docs_api - docs_perfil)

        if docs_perfil > 0:
            precision = round(min(docs_api / docs_perfil, 1.0) * 100, 1)
        else:
            precision = 100.0 if docs_api == 0 else 0.0

        if diferencia <= _UMBRAL_OK:
            estado = "OK"
        elif diferencia <= _UMBRAL_REVISAR:
            estado = "REVISAR"
        else:
            estado = "CRITICO"

        filas.append({
            "profesor": nombre,
            "departamento": depto,
            "author_ids": scopus_ids,
            "docs_perfil_scopus": docs_perfil,
            "docs_api_total": docs_api,
            "docs_extraidos": docs_ext,
            "diferencia": diferencia,
            "porcentaje_precision": precision,
            "eids_descartados_verificacion": descartados,
            "estado": estado,
        })

    df_cal = pd.DataFrame(filas) if filas else pd.DataFrame()
    logger.info(
        "calidad_matching_v2.csv: %d OK, %d REVISAR, %d CRITICO",
        (df_cal["estado"] == "OK").sum() if not df_cal.empty else 0,
        (df_cal["estado"] == "REVISAR").sum() if not df_cal.empty else 0,
        (df_cal["estado"] == "CRITICO").sum() if not df_cal.empty else 0,
    )
    return df_cal


def _construir_metricas_v2(df_pubs_local: pd.DataFrame) -> pd.DataFrame:
    """Genera metricas_revista_v2.csv usando fuentes de los datos locales."""
    from src.etl.normalize import extract_fuentes

    if df_pubs_local.empty:
        return pd.DataFrame()

    df_fuentes, _, _ = extract_fuentes(df_pubs_local)
    df_enr = run_enrichment(df_fuentes)
    df_enr["anio_datos"] = datetime.now().year

    cols = ["source_title", "issn", "sjr", "snip", "citescore",
            "cuartil_sjr", "percentil_citescore", "anio_datos"]
    return df_enr[[c for c in cols if c in df_enr.columns]].copy()


def _guardar(df: pd.DataFrame, ruta: Path, etiqueta: str) -> None:
    """Guarda DataFrame como CSV utf-8-sig."""
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    logger.info("Guardado: %s (%d filas)", etiqueta, len(df))
    print(f"    {ruta}  ({len(df)} filas)")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------


def main() -> None:
    """Orquesta el flujo completo v2."""
    ruta_log = _configurar_log_errores()
    logger.info("=== Paso 2 v2: Extracción corregida iniciada ===")

    # -- Inicializar cliente --
    try:
        client = ScopusClient()
    except ValueError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

    # -- Cargar profesores validados --
    if not _RUTA_VALIDADOS.exists():
        print(
            f"\nNo se encontró {_RUTA_VALIDADOS}. "
            "Ejecuta primero: python -m scripts.01_enriquecer_ids",
            file=sys.stderr,
        )
        sys.exit(1)

    df_profs = pd.read_csv(_RUTA_VALIDADOS, encoding="utf-8-sig", dtype=str).fillna("")
    df_profs = df_profs[df_profs["scopus_ids"].str.strip() != ""].reset_index(drop=True)

    if df_profs.empty:
        print("\nNo hay profesores con scopus_ids. Completa la revisión del Paso 1.",
              file=sys.stderr)
        sys.exit(1)

    logger.info(
        "Profesores a procesar: %d | Rango de años: %d–%d",
        len(df_profs), _AÑO_INICIO, _AÑO_FIN,
    )

    # -- Cargar publicaciones locales --
    logger.info("Cargando publicaciones locales (Completo 20XX.csv)...")
    df_raw = load_all_publications()
    df_pubs_local, _ = run_cleaning_pipeline(df_raw)

    # Construir índice con EIDs únicos garantizados (paso de robustez extra)
    df_pubs_local = df_pubs_local.drop_duplicates(subset=["eid"], keep="first")
    eid_index = df_pubs_local.set_index("eid")
    logger.info("Publicaciones locales limpias: %d (EIDs únicos)", len(df_pubs_local))

    # -- Procesar cada profesor --
    df_pubs_por_orcid: Dict[str, pd.DataFrame] = {}
    docs_api_total_por_orcid: Dict[str, int] = {}
    docs_extraidos_por_orcid: Dict[str, int] = {}
    docs_perfil_por_orcid: Dict[str, int] = {}
    descartados_por_orcid: Dict[str, int] = {}
    total = len(df_profs)

    for i, (_, row) in enumerate(df_profs.iterrows()):
        orcid = str(row.get("orcid", "")).strip()
        nombre = str(row.get("nombre", "")).strip()
        scopus_ids_str = str(row.get("scopus_ids", "")).strip()

        auth_ids = [s.strip() for s in scopus_ids_str.split(";") if s.strip()]
        logger.info(
            "(%d/%d) %s → IDs: %s", i + 1, total, nombre, ", ".join(auth_ids),
        )

        # -- Extraer publicaciones verificadas con año filtrado --
        df_pub, total_api, n_desc = extraer_publicaciones_profesor(
            nombre=nombre,
            author_ids=auth_ids,
            df_pubs_local=df_pubs_local,
            eid_index=eid_index,
            client=client,
            año_inicio=_AÑO_INICIO,
            año_fin=_AÑO_FIN,
        )

        df_pubs_por_orcid[orcid] = df_pub
        docs_api_total_por_orcid[orcid] = total_api
        docs_extraidos_por_orcid[orcid] = len(df_pub)
        descartados_por_orcid[orcid] = n_desc

        # -- Obtener document_count del perfil (independiente, para comparación) --
        docs_perfil = 0
        for aid in auth_ids:
            try:
                time.sleep(_SLEEP)
                perfil = retrieve_author_by_id(aid, client)
                if perfil:
                    docs_perfil = max(docs_perfil, perfil.get("document_count", 0))
            except (PermissionError, ConnectionError) as exc:
                _log_err("doc_count_perfil", nombre, exc)
        docs_perfil_por_orcid[orcid] = docs_perfil

    # -- Construir archivos de salida --
    print("\nArchivos generados en data/processed/:")

    df_pubs_out = _construir_publicaciones_v2(df_profs, df_pubs_por_orcid)
    _guardar(df_pubs_out, DATA_PROCESSED_DIR / "publicaciones_v2.csv", "publicaciones_v2.csv")

    df_calidad = _construir_calidad_v2(
        df_profs,
        docs_api_total_por_orcid,
        docs_extraidos_por_orcid,
        docs_perfil_por_orcid,
        descartados_por_orcid,
    )
    _guardar(df_calidad, DATA_PROCESSED_DIR / "calidad_matching_v2.csv", "calidad_matching_v2.csv")

    df_metricas = _construir_metricas_v2(df_pubs_local)
    _guardar(df_metricas, DATA_PROCESSED_DIR / "metricas_revista_v2.csv", "metricas_revista_v2.csv")

    # Actualizar profesores_validados.csv con métricas de esta ejecución
    df_profs["ultima_extraccion_v2"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df_profs["docs_extraidos_v2"] = df_profs["orcid"].map(
        lambda o: docs_extraidos_por_orcid.get(o, 0)
    )
    df_profs["docs_api_total_v2"] = df_profs["orcid"].map(
        lambda o: docs_api_total_por_orcid.get(o, 0)
    )
    df_profs["docs_perfil_v2"] = df_profs["orcid"].map(
        lambda o: docs_perfil_por_orcid.get(o, 0)
    )
    _guardar(df_profs, DATA_PROCESSED_DIR / "profesores_validados_v2.csv",
             "profesores_validados_v2.csv")

    # -- Resumen en consola --
    n_ok = (df_calidad["estado"] == "OK").sum() if not df_calidad.empty else 0
    n_rev = (df_calidad["estado"] == "REVISAR").sum() if not df_calidad.empty else 0
    n_crit = (df_calidad["estado"] == "CRITICO").sum() if not df_calidad.empty else 0

    print("\n" + "=" * 65)
    print(f"  RESUMEN v2  ({_AÑO_INICIO}–{_AÑO_FIN})")
    print("=" * 65)
    print(f"  Profesores procesados          : {len(df_profs)}")
    print(f"  Estado OK    (diferencia ≤ {_UMBRAL_OK})  : {n_ok}")
    print(f"  Estado REVISAR (dif. 3–{_UMBRAL_REVISAR}) : {n_rev}")
    print(f"  Estado CRITICO  (dif. > {_UMBRAL_REVISAR}) : {n_crit}")
    print(f"  Publicaciones únicas (rango)   : {df_pubs_out['eid'].nunique() if not df_pubs_out.empty else 0}")
    print("=" * 65)

    if n_crit or n_rev:
        print(
            "\n  Ejecuta python -m scripts.03_diagnostico_matching "
            "para el diagnóstico detallado de los casos con discrepancia."
        )

    print(f"\n    Errores de API en: {ruta_log}")
    logger.info("=== Paso 2 v2 finalizado ===")


if __name__ == "__main__":
    main()
