"""
Enriquecimiento de fuentes con métricas bibliométricas externas.

Cruza la tabla de fuentes del sistema con datos de Scimago (SJR, cuartiles)
y Scopus Source List (CiteScore, SNIP) por ISSN.

Fase 5 del pipeline ETL. Tolerante a la ausencia de archivos externos:
si no hay datos de Scimago o Scopus Source List, retorna las fuentes
sin métricas y el sistema sigue funcionando.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from config.settings import DATA_EXTERNAL_DIR
from src.utils.logger import get_logger
from src.utils.text_normalization import normalize_issn

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _explode_issns(issn_field: object) -> List[Optional[str]]:
    """Splitea un campo ISSN que puede contener múltiples valores separados por coma.

    Returns
    -------
    list[str | None]
        Lista de ISSNs normalizados (los inválidos se descartan).
    """
    if pd.isna(issn_field):
        return []
    parts = str(issn_field).split(",")
    result = []
    for part in parts:
        normalized = normalize_issn(part.strip())
        if normalized:
            result.append(normalized)
    return result


def _find_file(directory: Path, *keywords: str) -> Optional[Path]:
    """Busca un archivo en el directorio cuyo nombre contenga alguna keyword.

    Busca primero CSV, luego Excel. Retorna el primero que coincida.
    """
    if not directory.exists():
        return None
    for ext in ("*.csv", "*.xlsx", "*.xls"):
        for filepath in sorted(directory.glob(ext)):
            name_lower = filepath.name.lower()
            if any(kw in name_lower for kw in keywords):
                return filepath
    return None


def _safe_float(value: object) -> Optional[float]:
    """Convierte a float de forma segura, retornando None ante fallos."""
    if pd.isna(value):
        return None
    try:
        text = str(value).replace(",", ".")
        return float(text)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------


def load_scimago(filepath: Path) -> pd.DataFrame:
    """Lee un CSV de Scimago y normaliza ISSNs y métricas.

    El campo ``Issn`` de Scimago puede contener múltiples ISSNs
    separados por coma (print + electronic). Se crea una fila por
    cada ISSN normalizado para facilitar el cruce.

    Parameters
    ----------
    filepath:
        Ruta al CSV de Scimago.

    Returns
    -------
    pd.DataFrame
        Columnas: ``issn``, ``sjr``, ``cuartil_sjr``,
        ``source_title_scimago``.

    Example
    -------
    >>> df_sci = load_scimago(Path("data/external/scimago_2023.csv"))
    >>> df_sci.columns.tolist()
    ['issn', 'sjr', 'cuartil_sjr', 'source_title_scimago']
    """
    logger.info("Cargando Scimago: %s", filepath.name)

    # Scimago usa separador ';' en algunos archivos
    try:
        df = pd.read_csv(filepath, encoding="utf-8-sig", sep=";")
        if len(df.columns) < 3:
            df = pd.read_csv(filepath, encoding="utf-8-sig", sep=",")
    except UnicodeDecodeError:
        df = pd.read_csv(filepath, encoding="latin-1", sep=";")
        if len(df.columns) < 3:
            df = pd.read_csv(filepath, encoding="latin-1", sep=",")

    # Normalizar nombres de columna (Scimago varía entre años)
    df.columns = df.columns.str.strip()

    # Mapeo flexible de columnas
    col_map = {}
    for col in df.columns:
        cl = col.lower().strip()
        if cl == "issn":
            col_map[col] = "issn_raw"
        elif cl == "sjr":
            col_map[col] = "sjr"
        elif cl in ("sjr best quartile", "sjr_best_quartile"):
            col_map[col] = "cuartil_sjr"
        elif cl == "title":
            col_map[col] = "source_title_scimago"

    df = df.rename(columns=col_map)

    # Verificar columnas mínimas
    needed = {"issn_raw"}
    if not needed.issubset(df.columns):
        logger.warning("Scimago: columnas esperadas no encontradas (%s)", df.columns.tolist())
        return pd.DataFrame(columns=["issn", "sjr", "cuartil_sjr", "source_title_scimago"])

    # Explode ISSNs múltiples
    df["_issn_list"] = df["issn_raw"].apply(_explode_issns)
    df = df.explode("_issn_list").rename(columns={"_issn_list": "issn"})
    df = df[df["issn"].notna()].copy()

    # Convertir SJR a float
    if "sjr" in df.columns:
        df["sjr"] = df["sjr"].apply(_safe_float)

    # Normalizar cuartil
    if "cuartil_sjr" in df.columns:
        df["cuartil_sjr"] = df["cuartil_sjr"].astype(str).str.strip().str.upper()
        valid_q = {"Q1", "Q2", "Q3", "Q4"}
        df.loc[~df["cuartil_sjr"].isin(valid_q), "cuartil_sjr"] = None

    # Seleccionar y deduplicar
    out_cols = ["issn", "sjr", "cuartil_sjr", "source_title_scimago"]
    for col in out_cols:
        if col not in df.columns:
            df[col] = None
    df = df[out_cols].drop_duplicates(subset=["issn"], keep="first")

    logger.info("Scimago cargado: %d registros con ISSN unico", len(df))
    return df.reset_index(drop=True)


def load_scopus_source_list(filepath: Path) -> pd.DataFrame:
    """Lee un archivo de Scopus Source List (CSV o Excel) y normaliza.

    Parameters
    ----------
    filepath:
        Ruta al archivo Scopus Source List.

    Returns
    -------
    pd.DataFrame
        Columnas: ``issn``, ``e_issn``, ``citescore``, ``snip``,
        ``percentile``.

    Example
    -------
    >>> df_sl = load_scopus_source_list(Path("data/external/scopus_source_2023.xlsx"))
    """
    logger.info("Cargando Scopus Source List: %s", filepath.name)

    if filepath.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(filepath)
    else:
        try:
            df = pd.read_csv(filepath, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(filepath, encoding="latin-1")

    df.columns = df.columns.str.strip()

    # Mapeo flexible de columnas
    col_map = {}
    for col in df.columns:
        cl = col.lower().strip().replace("-", "").replace("_", "").replace(" ", "")
        if cl == "issn":
            col_map[col] = "issn_raw"
        elif cl in ("eissn", "eissn"):
            col_map[col] = "e_issn_raw"
        elif cl == "citescore":
            col_map[col] = "citescore"
        elif cl == "snip":
            col_map[col] = "snip"
        elif cl in ("percentile", "percentilecitescore"):
            col_map[col] = "percentile"

    df = df.rename(columns=col_map)

    # Normalizar ISSNs
    if "issn_raw" in df.columns:
        df["issn"] = df["issn_raw"].apply(
            lambda x: normalize_issn(str(x)) if pd.notna(x) else None,
        )
    else:
        df["issn"] = None

    if "e_issn_raw" in df.columns:
        df["e_issn"] = df["e_issn_raw"].apply(
            lambda x: normalize_issn(str(x)) if pd.notna(x) else None,
        )
    else:
        df["e_issn"] = None

    # Convertir métricas a float
    for col in ("citescore", "snip"):
        if col in df.columns:
            df[col] = df[col].apply(_safe_float)
        else:
            df[col] = None

    if "percentile" in df.columns:
        df["percentile"] = pd.to_numeric(df["percentile"], errors="coerce")
    else:
        df["percentile"] = None

    out_cols = ["issn", "e_issn", "citescore", "snip", "percentile"]
    df = df[out_cols].copy()
    df = df[df["issn"].notna() | df["e_issn"].notna()]
    df = df.drop_duplicates(subset=["issn"], keep="first")

    logger.info("Scopus Source List cargado: %d registros", len(df))
    return df.reset_index(drop=True)


def merge_metrics_by_issn(
    df_fuentes: pd.DataFrame,
    df_scimago: Optional[pd.DataFrame] = None,
    df_scopus_source: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Cruza fuentes del sistema con métricas externas por ISSN.

    Realiza left join con Scimago y Scopus Source List. Cuando ambas
    fuentes proveen SJR, prioriza Scimago.

    Parameters
    ----------
    df_fuentes:
        DataFrame de fuentes (output de ``normalize.extract_fuentes``).
    df_scimago:
        Datos de Scimago (output de ``load_scimago``). Puede ser ``None``.
    df_scopus_source:
        Datos de Scopus Source List. Puede ser ``None``.

    Returns
    -------
    pd.DataFrame
        Fuentes enriquecidas con columnas: ``sjr``, ``snip``,
        ``citescore``, ``cuartil_sjr``, ``percentil_citescore``.
    """
    result = df_fuentes.copy()
    metric_cols = ["sjr", "snip", "citescore", "cuartil_sjr", "percentil_citescore"]

    # Inicializar columnas de métricas
    for col in metric_cols:
        if col not in result.columns:
            result[col] = None

    matched_scimago = 0
    matched_scopus = 0

    # --- Merge con Scimago ---
    if df_scimago is not None and not df_scimago.empty:
        sci = df_scimago[df_scimago["issn"].notna()][
            ["issn", "sjr", "cuartil_sjr"]
        ].copy()
        sci = sci.rename(columns={"sjr": "_sci_sjr", "cuartil_sjr": "_sci_cuartil"})

        result = result.merge(sci, on="issn", how="left")

        has_sci = result["_sci_sjr"].notna()
        matched_scimago = int(has_sci.sum())
        result.loc[has_sci, "sjr"] = result.loc[has_sci, "_sci_sjr"]
        result.loc[has_sci, "cuartil_sjr"] = result.loc[has_sci, "_sci_cuartil"]
        result = result.drop(columns=["_sci_sjr", "_sci_cuartil"])

    # --- Merge con Scopus Source List ---
    if df_scopus_source is not None and not df_scopus_source.empty:
        # Solo filas con ISSN válido para el merge principal
        sl = df_scopus_source[df_scopus_source["issn"].notna()][
            ["issn", "citescore", "snip", "percentile"]
        ].copy()
        sl = sl.rename(columns={
            "citescore": "_sl_citescore",
            "snip": "_sl_snip",
            "percentile": "_sl_percentile",
        })

        result = result.merge(sl, on="issn", how="left")

        # Fallback: intentar por e_issn para fuentes sin match por issn
        if "e_issn" in df_scopus_source.columns:
            sl_eissn = df_scopus_source[
                df_scopus_source["e_issn"].notna()
            ][["e_issn", "citescore", "snip", "percentile"]].copy()
            sl_eissn = sl_eissn.rename(columns={
                "e_issn": "issn",
                "citescore": "_sl_e_citescore",
                "snip": "_sl_e_snip",
                "percentile": "_sl_e_percentile",
            })
            # Solo merge con filas que tienen issn válido en el resultado
            sl_eissn = sl_eissn[sl_eissn["issn"].notna()]

            result = result.merge(sl_eissn, on="issn", how="left")

            # Rellenar con e_issn donde falta el match principal
            for base, fallback in [
                ("_sl_citescore", "_sl_e_citescore"),
                ("_sl_snip", "_sl_e_snip"),
                ("_sl_percentile", "_sl_e_percentile"),
            ]:
                if fallback in result.columns:
                    result[base] = result[base].fillna(result[fallback])
                    result = result.drop(columns=[fallback])

        has_sl = result["_sl_citescore"].notna() | result["_sl_snip"].notna()
        matched_scopus = int(has_sl.sum())

        result.loc[result["_sl_citescore"].notna(), "citescore"] = result["_sl_citescore"]
        result.loc[result["_sl_snip"].notna(), "snip"] = result["_sl_snip"]
        result.loc[result["_sl_percentile"].notna(), "percentil_citescore"] = result["_sl_percentile"]
        result = result.drop(
            columns=[c for c in result.columns if c.startswith("_sl_")],
        )

    # --- Estadísticas ---
    total = len(result)
    has_any = result[["sjr", "citescore", "snip"]].notna().any(axis=1).sum()
    sin_metrica = total - has_any

    logger.info(
        "Enriquecimiento: %d fuentes totales, %d con Scimago, "
        "%d con Scopus Source List, %d sin metricas",
        total,
        matched_scimago,
        matched_scopus,
        sin_metrica,
    )

    # Asegurar que las columnas métricas existen incluso si no hubo merge
    for col in metric_cols:
        if col not in result.columns:
            result[col] = None

    return result


def run_enrichment(
    df_fuentes: pd.DataFrame,
    scimago_path: Optional[Path] = None,
    scopus_source_path: Optional[Path] = None,
    anio: Optional[int] = None,
) -> pd.DataFrame:
    """Ejecuta el pipeline completo de enriquecimiento de fuentes.

    Busca automáticamente archivos de Scimago y Scopus Source List
    en ``data/external/`` si no se proporcionan rutas explícitas.
    Si no encuentra archivos externos, retorna las fuentes sin métricas.

    Parameters
    ----------
    df_fuentes:
        DataFrame de fuentes (output de ``normalize.extract_fuentes``).
    scimago_path:
        Ruta al CSV de Scimago. Si ``None``, busca automáticamente.
    scopus_source_path:
        Ruta al archivo de Scopus Source List. Si ``None``, busca
        automáticamente.
    anio:
        Año de referencia para las métricas. Si ``None``, usa el actual.

    Returns
    -------
    pd.DataFrame
        Fuentes enriquecidas (o sin enriquecer si no hay datos externos).

    Example
    -------
    >>> df_enriched = run_enrichment(df_fuentes)
    """
    if anio is None:
        anio = datetime.now().year

    logger.info(
        "=== Enriquecimiento de fuentes iniciado (%d fuentes, anio=%d) ===",
        len(df_fuentes),
        anio,
    )

    # --- Auto-descubrimiento de archivos ---
    df_scimago = None
    df_scopus_source = None

    if scimago_path is None:
        scimago_path = _find_file(DATA_EXTERNAL_DIR, "scimago")

    if scimago_path and scimago_path.exists():
        try:
            df_scimago = load_scimago(scimago_path)
        except Exception as exc:
            logger.error("Error cargando Scimago (%s): %s", scimago_path.name, exc)
    else:
        logger.warning("No se encontro archivo de Scimago en %s", DATA_EXTERNAL_DIR)

    if scopus_source_path is None:
        scopus_source_path = _find_file(
            DATA_EXTERNAL_DIR, "scopus_source", "source_list",
        )

    if scopus_source_path and scopus_source_path.exists():
        try:
            df_scopus_source = load_scopus_source_list(scopus_source_path)
        except Exception as exc:
            logger.error(
                "Error cargando Scopus Source List (%s): %s",
                scopus_source_path.name,
                exc,
            )
    else:
        logger.warning(
            "No se encontro archivo de Scopus Source List en %s",
            DATA_EXTERNAL_DIR,
        )

    # --- Merge ---
    result = merge_metrics_by_issn(df_fuentes, df_scimago, df_scopus_source)

    logger.info("=== Enriquecimiento finalizado ===")
    return result
