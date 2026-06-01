"""
PASO 2: Extracción por AU-ID(), validación cruzada y exportación para Power BI.

Prerrequisito
-------------
Haber ejecutado el Paso 1 (01_enriquecer_ids.py) y completado la revisión
humana de data/processed/profesores_validados.csv (columna scopus_ids llena).

Qué hace este script
--------------------
1. Lee profesores_validados.csv (con Scopus Author IDs confirmados).
2. Para cada profesor, construye una query AU-ID(id1) OR AU-ID(id2) OR ...
   y recupera todos los EIDs de publicaciones desde la API (con paginación).
   Nunca usa búsqueda por nombre.
3. Cruza los EIDs de la API con las publicaciones locales (Completo 20XX.csv).
4. Valida: compara docs_extraidos (por AU-ID) vs docs_en_perfil (del Author
   Retrieval). Si la diferencia es >5, marca el profesor como REVISAR.
5. Genera los archivos de salida en data/processed/:
   - calidad_matching.csv
   - publicaciones.csv           (para Power BI)
   - profesores_validados.csv    (actualizado con métricas)
   - metricas_revista.csv        (para Power BI)

Salidas
-------
data/processed/calidad_matching.csv
data/processed/publicaciones.csv
data/processed/metricas_revista.csv
data/processed/profesores_validados.csv   (sobreescrito con h-index actualizado)
logs/errores_api.log

Uso
---
    python -m scripts.02_extraer_validar_exportar
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

from config.settings import DATA_PROCESSED_DIR, LOGS_DIR
from src.api_scopus.author_retrieval import retrieve_author_by_id
from src.api_scopus.client import ScopusClient
from src.etl.clean import run_cleaning_pipeline
from src.etl.enrich_sources import run_enrichment
from src.etl.ingest_professors import load_all_professors
from src.etl.ingest_publications import load_all_publications
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SLEEP_ENTRE_LLAMADAS: float = 0.5
_UMBRAL_DIFERENCIA: int = 5
"""Si |docs_perfil - docs_extraidos| > umbral → estado REVISAR."""

_RUTA_VALIDADOS = DATA_PROCESSED_DIR / "profesores_validados.csv"

# ---------------------------------------------------------------------------
# Logger de errores de API
# ---------------------------------------------------------------------------

_api_err_logger = logging.getLogger("errores_api")


def _configurar_log_errores() -> Path:
    """Configura el logger dedicado para errores de API."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ruta = LOGS_DIR / "errores_api.log"
    if not _api_err_logger.handlers:
        handler = logging.FileHandler(ruta, encoding="utf-8", mode="a")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        _api_err_logger.setLevel(logging.ERROR)
        _api_err_logger.addHandler(handler)
    return ruta


def _log_error_api(contexto: str, referencia: str, exc: Exception) -> None:
    """Escribe un error de API en errores_api.log."""
    _api_err_logger.error(
        "contexto=%s | ref=%s | tipo=%s | detalle=%s",
        contexto,
        referencia,
        type(exc).__name__,
        str(exc),
    )


# ---------------------------------------------------------------------------
# Carga de datos locales
# ---------------------------------------------------------------------------


def cargar_profesores_validados() -> pd.DataFrame:
    """Lee profesores_validados.csv generado en el Paso 1.

    Returns
    -------
    pd.DataFrame
        DataFrame con al menos las columnas: orcid, nombre, departamento,
        scopus_ids. Excluye profesores sin scopus_ids.
    """
    if not _RUTA_VALIDADOS.exists():
        raise FileNotFoundError(
            f"No se encontró {_RUTA_VALIDADOS}. "
            "Ejecuta primero: python -m scripts.01_enriquecer_ids"
        )

    df = pd.read_csv(_RUTA_VALIDADOS, encoding="utf-8-sig", dtype=str)
    df = df.fillna("")

    # Solo procesar profesores con scopus_ids definidos
    con_ids = df["scopus_ids"].str.strip() != ""
    sin_ids = (~con_ids).sum()
    if sin_ids > 0:
        logger.warning(
            "%d profesores sin scopus_ids serán omitidos. "
            "Completa la revisión humana primero.",
            sin_ids,
        )

    return df[con_ids].reset_index(drop=True)


def _extraer_author_ids_de_publicacion(author_full_names: object) -> str:
    """Extrae los Scopus Author IDs de la columna author_full_names.

    El formato típico del campo es:
    "García-Pérez, Juan (56013816500); Martínez, M. (45678901234)"

    Returns
    -------
    str
        IDs separados por ";", o cadena vacía.
    """
    if pd.isna(author_full_names) or not str(author_full_names).strip():
        return ""
    ids = re.findall(r"\((\d{9,15})\)", str(author_full_names))
    return ";".join(dict.fromkeys(ids))  # únicos, en orden de aparición


# ---------------------------------------------------------------------------
# Recuperación de EIDs desde la API (con paginación)
# ---------------------------------------------------------------------------


def _get_total_results(raw_response: dict) -> int:
    """Extrae opensearch:totalResults de una respuesta de Scopus Search."""
    try:
        sr = raw_response.get("search-results", {})
        return int(sr.get("opensearch:totalResults", 0))
    except (ValueError, TypeError):
        return 0


def _extraer_eids_de_respuesta(raw_response: dict) -> List[str]:
    """Parsea los EIDs de una respuesta de Scopus Search."""
    sr = raw_response.get("search-results", {})
    entries = sr.get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]

    eids: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("@error"):
            continue
        eid = str(entry.get("eid", entry.get("dc:identifier", ""))).strip()
        # Limpiar prefijo SCOPUS_ID: si existe
        eid = re.sub(r"^SCOPUS_ID:\s*", "", eid)
        if eid:
            eids.append(eid)
    return eids


def recuperar_eids_por_au_id(
    auth_ids: List[str],
    nombre_profesor: str,
    client: ScopusClient,
) -> List[str]:
    """Recupera todos los EIDs de un profesor usando AU-ID() (con paginación).

    Construye la query ``AU-ID(id1) OR AU-ID(id2) OR ...`` y pagina
    hasta obtener todos los resultados.

    Parameters
    ----------
    auth_ids:
        Lista de Scopus Author IDs del profesor.
    nombre_profesor:
        Nombre para logs y errores.
    client:
        Instancia de ScopusClient.

    Returns
    -------
    list[str]
        Lista de EIDs únicos, o lista vacía ante error.
    """
    if not auth_ids:
        return []

    query = " OR ".join(f"AU-ID({aid})" for aid in auth_ids)
    todos_eids: List[str] = []
    start = 0
    count = 200
    total = None

    while True:
        try:
            time.sleep(_SLEEP_ENTRE_LLAMADAS)
            raw = client.search_publications_page(query, start=start, count=count)
        except (PermissionError, ConnectionError) as exc:
            _log_error_api("recuperar_eids_au_id", nombre_profesor, exc)
            break

        if raw is None:
            break

        if total is None:
            total = _get_total_results(raw)
            logger.info(
                "%s → AU-ID query: %d publicaciones totales en Scopus",
                nombre_profesor, total,
            )

        pagina_eids = _extraer_eids_de_respuesta(raw)
        todos_eids.extend(pagina_eids)

        start += count
        # Detener si ya recuperamos todo o la página llegó vacía
        if not pagina_eids or start >= (total or 0):
            break

    unicos = list(dict.fromkeys(todos_eids))  # eliminar duplicados preservando orden
    logger.info(
        "%s → EIDs recuperados via AU-ID: %d únicos (total declarado: %s)",
        nombre_profesor, len(unicos), total,
    )
    return unicos


def recuperar_docs_en_perfil(
    auth_ids: List[str],
    nombre_profesor: str,
    client: ScopusClient,
) -> int:
    """Retorna el document_count máximo entre todos los Author IDs del profesor."""
    max_docs = 0
    for aid in auth_ids:
        try:
            time.sleep(_SLEEP_ENTRE_LLAMADAS)
            perfil = retrieve_author_by_id(aid, client)
            if perfil:
                max_docs = max(max_docs, perfil.get("document_count", 0))
        except (PermissionError, ConnectionError) as exc:
            _log_error_api("recuperar_docs_perfil", nombre_profesor, exc)
    return max_docs


# ---------------------------------------------------------------------------
# Construcción de los CSVs de salida
# ---------------------------------------------------------------------------


def construir_publicaciones_csv(
    df_profs: pd.DataFrame,
    df_pubs_local: pd.DataFrame,
    eids_por_orcid: Dict[str, Set[str]],
) -> pd.DataFrame:
    """Construye publicaciones.csv cruzando EIDs de la API con datos locales.

    Para cada (profesor, EID confirmado por AU-ID), busca la fila en los
    datos locales y agrega la información del profesor.

    Returns
    -------
    pd.DataFrame
        Una fila por (publicación, profesor). Columnas listas para Power BI.
    """
    # Índice rápido: EID → fila en publicaciones locales
    if "eid" not in df_pubs_local.columns:
        logger.error("Las publicaciones locales no tienen columna 'eid'")
        return pd.DataFrame()

    eid_index = df_pubs_local.set_index("eid")

    filas: List[dict] = []

    for _, prof_row in df_profs.iterrows():
        orcid = str(prof_row.get("orcid", "")).strip()
        nombre = str(prof_row.get("nombre", "")).strip()
        depto = str(prof_row.get("departamento", "")).strip()

        eids_del_prof = eids_por_orcid.get(orcid, set())

        for eid in eids_del_prof:
            if eid not in eid_index.index:
                continue  # EID no está en los CSV locales, omitir

            pub = eid_index.loc[eid]
            # Si hay múltiples filas con el mismo EID, tomar la primera
            if isinstance(pub, pd.DataFrame):
                pub = pub.iloc[0]

            autor_ids = _extraer_author_ids_de_publicacion(
                pub.get("author_full_names", "")
            )

            filas.append({
                "eid": eid,
                "titulo": pub.get("titulo", ""),
                "anio_publicacion": pub.get("anio_publicacion", ""),
                "source_title": pub.get("source_title", ""),
                "issn": pub.get("issn", ""),
                "cited_by_count": pub.get("cited_by_count", 0),
                "tipo_documental": pub.get("tipo_documental", ""),
                "autor_ids_scopus": autor_ids,
                "profesor_asignado": nombre,
                "departamento": depto,
                "orcid_profesor": orcid,
            })

    df_pubs_out = pd.DataFrame(filas) if filas else pd.DataFrame(
        columns=[
            "eid", "titulo", "anio_publicacion", "source_title", "issn",
            "cited_by_count", "tipo_documental", "autor_ids_scopus",
            "profesor_asignado", "departamento", "orcid_profesor",
        ]
    )

    # Deduplicar: si el mismo EID aparece para >1 profesor, cada uno tiene su fila
    # (esto es correcto para Power BI: un paper coautorado aparece una vez por prof)
    logger.info(
        "publicaciones.csv: %d filas (%d EIDs únicos, %d profesores únicos)",
        len(df_pubs_out),
        df_pubs_out["eid"].nunique() if not df_pubs_out.empty else 0,
        df_pubs_out["profesor_asignado"].nunique() if not df_pubs_out.empty else 0,
    )
    return df_pubs_out


def construir_calidad_matching(
    df_profs: pd.DataFrame,
    eids_por_orcid: Dict[str, Set[str]],
    docs_perfil_por_orcid: Dict[str, int],
) -> pd.DataFrame:
    """Genera calidad_matching.csv con validación cruzada por profesor.

    Estado:
      OK        → |docs_perfil - docs_extraidos| ≤ 5
      REVISAR   → diferencia > 5
      SIN_ID    → el profesor no tiene scopus_ids
    """
    filas: List[dict] = []

    for _, prof_row in df_profs.iterrows():
        orcid = str(prof_row.get("orcid", "")).strip()
        nombre = str(prof_row.get("nombre", "")).strip()
        depto = str(prof_row.get("departamento", "")).strip()
        scopus_ids = str(prof_row.get("scopus_ids", "")).strip()

        if not scopus_ids:
            filas.append({
                "profesor": nombre,
                "departamento": depto,
                "scopus_ids": "",
                "docs_en_perfil": 0,
                "docs_extraidos": 0,
                "diferencia": 0,
                "estado": "SIN_ID",
            })
            continue

        docs_perfil = docs_perfil_por_orcid.get(orcid, 0)
        docs_extraidos = len(eids_por_orcid.get(orcid, set()))
        diferencia = abs(docs_perfil - docs_extraidos)

        if diferencia > _UMBRAL_DIFERENCIA:
            estado = "REVISAR"
        else:
            estado = "OK"

        filas.append({
            "profesor": nombre,
            "departamento": depto,
            "scopus_ids": scopus_ids,
            "docs_en_perfil": docs_perfil,
            "docs_extraidos": docs_extraidos,
            "diferencia": diferencia,
            "estado": estado,
        })

    df_calidad = pd.DataFrame(filas) if filas else pd.DataFrame(
        columns=[
            "profesor", "departamento", "scopus_ids",
            "docs_en_perfil", "docs_extraidos", "diferencia", "estado",
        ]
    )
    logger.info(
        "calidad_matching.csv: %d profesores — %d OK, %d REVISAR, %d SIN_ID",
        len(df_calidad),
        (df_calidad["estado"] == "OK").sum() if not df_calidad.empty else 0,
        (df_calidad["estado"] == "REVISAR").sum() if not df_calidad.empty else 0,
        (df_calidad["estado"] == "SIN_ID").sum() if not df_calidad.empty else 0,
    )
    return df_calidad


def construir_metricas_revista(df_pubs_local: pd.DataFrame) -> pd.DataFrame:
    """Genera metricas_revista.csv enriqueciendo las fuentes con SJR/SNIP/CiteScore.

    Extrae las fuentes únicas de los datos locales y las cruza con los
    archivos externos de métricas (Scimago, Scopus Source List).

    Returns
    -------
    pd.DataFrame
        Columnas: source_title, issn, sjr, snip, citescore, cuartil_sjr,
        percentil_citescore, anio_datos.
    """
    from src.etl.normalize import extract_fuentes  # import tardío para no cargar BD

    if df_pubs_local.empty:
        return pd.DataFrame()

    df_fuentes, _, _ = extract_fuentes(df_pubs_local)
    df_enriquecidas = run_enrichment(df_fuentes)

    anio_datos = datetime.now().year
    df_enriquecidas["anio_datos"] = anio_datos

    cols_salida = [
        "source_title", "issn", "sjr", "snip", "citescore",
        "cuartil_sjr", "percentil_citescore", "anio_datos",
    ]
    cols_disponibles = [c for c in cols_salida if c in df_enriquecidas.columns]
    df_metricas = df_enriquecidas[cols_disponibles].copy()

    logger.info(
        "metricas_revista.csv: %d fuentes (%d con SJR, %d con CiteScore)",
        len(df_metricas),
        df_metricas["sjr"].notna().sum() if "sjr" in df_metricas.columns else 0,
        df_metricas["citescore"].notna().sum() if "citescore" in df_metricas.columns else 0,
    )
    return df_metricas


# ---------------------------------------------------------------------------
# Guardado de salidas
# ---------------------------------------------------------------------------


def _guardar_csv(df: pd.DataFrame, ruta: Path, nombre_archivo: str) -> None:
    """Guarda un DataFrame como CSV con encoding utf-8-sig."""
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    logger.info("Guardado: %s (%d filas)", nombre_archivo, len(df))
    print(f"    {ruta}  ({len(df)} filas)")


# ---------------------------------------------------------------------------
# Resumen final
# ---------------------------------------------------------------------------


def _imprimir_resumen(
    df_calidad: pd.DataFrame,
    df_pubs: pd.DataFrame,
    df_profs: pd.DataFrame,
) -> None:
    """Imprime el resumen de resultados en consola."""
    n_ok = (df_calidad["estado"] == "OK").sum() if not df_calidad.empty else 0
    n_rev = (df_calidad["estado"] == "REVISAR").sum() if not df_calidad.empty else 0
    n_sin = (df_calidad["estado"] == "SIN_ID").sum() if not df_calidad.empty else 0
    n_pubs_uniq = df_pubs["eid"].nunique() if not df_pubs.empty else 0

    print("\n" + "=" * 60)
    print("RESUMEN - Paso 2: Extracción, validación y exportación")
    print("=" * 60)
    print(f"  Profesores procesados              : {len(df_profs)}")
    print(f"  Estado OK (diferencia ≤ {_UMBRAL_DIFERENCIA})         : {n_ok}")
    print(f"  Estado REVISAR (diferencia > {_UMBRAL_DIFERENCIA})    : {n_rev}")
    print(f"  Estado SIN_ID                      : {n_sin}")
    print(f"  Publicaciones únicas en Power BI   : {n_pubs_uniq}")
    print("=" * 60)

    if n_rev > 0:
        print(
            f"\n⚠️  {n_rev} profesor(es) con diferencia > {_UMBRAL_DIFERENCIA} docs.",
        )
        print("   Revisa data/processed/calidad_matching.csv para detalles.")
        profesores_revisar = df_calidad[
            df_calidad["estado"] == "REVISAR"
        ]["profesor"].tolist()
        for p in profesores_revisar[:10]:
            print(f"     - {p}")
        if len(profesores_revisar) > 10:
            print(f"     ... y {len(profesores_revisar) - 10} más.")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------


def main() -> None:
    """Orquesta el flujo completo del paso 2."""
    ruta_log = _configurar_log_errores()
    logger.info("=== Paso 2: Extracción por AU-ID() iniciado ===")
    logger.info("Errores de API se guardarán en: %s", ruta_log)

    # -- Inicializar cliente --
    try:
        client = ScopusClient()
    except ValueError as exc:
        print(
            f"\nError: {exc}\n"
            "Configura SCOPUS_API_KEY en el archivo .env antes de ejecutar.",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- Cargar profesores validados --
    try:
        df_profs = cargar_profesores_validados()
    except FileNotFoundError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

    if df_profs.empty:
        print(
            "\nNo hay profesores con scopus_ids en profesores_validados.csv. "
            "Completa la revisión humana del Paso 1.",
            file=sys.stderr,
        )
        sys.exit(1)

    logger.info(
        "Profesores con scopus_ids a procesar: %d", len(df_profs),
    )

    # -- Cargar publicaciones locales --
    logger.info("Cargando publicaciones locales (Completo 20XX.csv)...")
    df_pubs_raw = load_all_publications()
    df_pubs_local, _ = run_cleaning_pipeline(df_pubs_raw)
    logger.info(
        "Publicaciones locales limpias: %d", len(df_pubs_local),
    )

    # -- Extraer EIDs por AU-ID() y obtener doc_count del perfil --
    eids_por_orcid: Dict[str, Set[str]] = {}
    docs_perfil_por_orcid: Dict[str, int] = {}
    total_profs = len(df_profs)

    for i, (_, prof_row) in enumerate(df_profs.iterrows()):
        orcid = str(prof_row.get("orcid", "")).strip()
        nombre = str(prof_row.get("nombre", "")).strip()
        scopus_ids_str = str(prof_row.get("scopus_ids", "")).strip()

        if not scopus_ids_str:
            continue

        auth_ids = [s.strip() for s in scopus_ids_str.split(";") if s.strip()]

        logger.info(
            "Procesando (%d/%d): %s [IDs: %s]",
            i + 1, total_profs, nombre, ", ".join(auth_ids),
        )

        # Obtener EIDs via AU-ID() (query principal — nunca por nombre)
        eids = recuperar_eids_por_au_id(auth_ids, nombre, client)
        eids_por_orcid[orcid] = set(eids)

        # Obtener document_count del perfil para validación cruzada
        docs_perfil = recuperar_docs_en_perfil(auth_ids, nombre, client)
        docs_perfil_por_orcid[orcid] = docs_perfil

    # -- Construir los CSVs de salida --
    logger.info("Construyendo publicaciones.csv...")
    df_pubs_out = construir_publicaciones_csv(
        df_profs, df_pubs_local, eids_por_orcid,
    )

    logger.info("Construyendo calidad_matching.csv...")
    df_calidad = construir_calidad_matching(
        df_profs, eids_por_orcid, docs_perfil_por_orcid,
    )

    logger.info("Construyendo metricas_revista.csv...")
    df_metricas = construir_metricas_revista(df_pubs_local)

    # -- Guardar todos los archivos --
    print("\nArchivos generados en data/processed/:")
    _guardar_csv(
        df_pubs_out,
        DATA_PROCESSED_DIR / "publicaciones.csv",
        "publicaciones.csv",
    )
    _guardar_csv(
        df_calidad,
        DATA_PROCESSED_DIR / "calidad_matching.csv",
        "calidad_matching.csv",
    )
    _guardar_csv(
        df_metricas,
        DATA_PROCESSED_DIR / "metricas_revista.csv",
        "metricas_revista.csv",
    )
    # Actualizar profesores_validados.csv con la fecha de actualización
    df_profs["ultima_extraccion"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df_profs["docs_extraidos"] = df_profs["orcid"].map(
        lambda o: len(eids_por_orcid.get(o, set()))
    )
    df_profs["docs_en_perfil"] = df_profs["orcid"].map(
        lambda o: docs_perfil_por_orcid.get(o, 0)
    )
    _guardar_csv(
        df_profs,
        _RUTA_VALIDADOS,
        "profesores_validados.csv (actualizado)",
    )

    # -- Resumen --
    _imprimir_resumen(df_calidad, df_pubs_out, df_profs)

    logger.info("=== Paso 2 finalizado ===")
    print(f"\n    {ruta_log}")


if __name__ == "__main__":
    main()
