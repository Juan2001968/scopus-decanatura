"""
Deduplicación de publicaciones bibliométricas.

Provee funciones para eliminar registros duplicados por EID, DOI
y títulos similares, conservando siempre la versión con más citas.
"""

from typing import Dict, Tuple

import pandas as pd

from src.utils.logger import get_logger
from src.utils.text_normalization import normalize_title

logger = get_logger(__name__)


def deduplicate_by_eid(
    df: pd.DataFrame,
    eid_col: str = "EID",
) -> pd.DataFrame:
    """Elimina filas con EID duplicado, conservando la de mayor conteo de citas.

    Parameters
    ----------
    df:
        DataFrame de publicaciones.
    eid_col:
        Nombre de la columna EID.

    Returns
    -------
    pd.DataFrame
        DataFrame sin duplicados por EID.

    Example
    -------
    >>> df_clean = deduplicate_by_eid(df)
    """
    before = len(df)
    cited_col = "Cited by"

    if cited_col in df.columns:
        df = df.sort_values(cited_col, ascending=False, na_position="last")

    df = df.drop_duplicates(subset=[eid_col], keep="first")

    removed = before - len(df)
    logger.info("Dedup EID: %d duplicados eliminados (%d → %d)", removed, before, len(df))
    return df.reset_index(drop=True)


def deduplicate_by_doi(
    df: pd.DataFrame,
    doi_col: str = "DOI",
) -> pd.DataFrame:
    """Elimina filas con DOI duplicado (ignorando nulos), conservando la de mayor citas.

    Parameters
    ----------
    df:
        DataFrame de publicaciones.
    doi_col:
        Nombre de la columna DOI.

    Returns
    -------
    pd.DataFrame
        DataFrame sin duplicados por DOI.

    Example
    -------
    >>> df_clean = deduplicate_by_doi(df)
    """
    has_doi = df[doi_col].notna() & (df[doi_col].astype(str).str.strip() != "")
    df_with = df[has_doi].copy()
    df_without = df[~has_doi].copy()

    before = len(df_with)
    cited_col = "Cited by"

    if cited_col in df_with.columns:
        df_with = df_with.sort_values(cited_col, ascending=False, na_position="last")

    df_with = df_with.drop_duplicates(subset=[doi_col], keep="first")

    removed = before - len(df_with)
    logger.info("Dedup DOI: %d duplicados eliminados (%d → %d con DOI)", removed, before, len(df_with))

    return pd.concat([df_with, df_without], ignore_index=True)


def find_near_duplicate_titles(
    df: pd.DataFrame,
    title_col: str = "Title",
    threshold: float = 0.95,
) -> pd.DataFrame:
    """Identifica posibles duplicados por título normalizado para revisión manual.

    Busca duplicados exactos por título normalizado y los marca con un
    ``duplicate_group`` numérico. No elimina filas.

    Parameters
    ----------
    df:
        DataFrame de publicaciones.
    title_col:
        Nombre de la columna de título.
    threshold:
        Umbral de similitud (reservado para futuras comparaciones fuzzy).

    Returns
    -------
    pd.DataFrame
        Subconjunto de filas sospechosas con columna ``duplicate_group``.

    Example
    -------
    >>> suspects = find_near_duplicate_titles(df)
    >>> suspects.groupby("duplicate_group").size()
    """
    work = df.copy()
    work["_norm_title"] = work[title_col].apply(
        lambda t: normalize_title(t) if isinstance(t, str) else ""
    )

    dupes = work[work["_norm_title"].duplicated(keep=False) & (work["_norm_title"] != "")]

    if dupes.empty:
        logger.info("Títulos duplicados: ninguno encontrado")
        return pd.DataFrame(columns=[*df.columns, "duplicate_group"])

    groups = dupes.groupby("_norm_title").ngroup()
    result = dupes.drop(columns=["_norm_title"]).copy()
    result["duplicate_group"] = groups.values

    logger.info(
        "Títulos duplicados: %d filas en %d grupos",
        len(result),
        result["duplicate_group"].nunique(),
    )
    return result.reset_index(drop=True)


def run_deduplication_pipeline(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Ejecuta el pipeline completo de deduplicación: EID → DOI.

    Parameters
    ----------
    df:
        DataFrame de publicaciones crudas.

    Returns
    -------
    tuple[pd.DataFrame, dict[str, int]]
        DataFrame limpio y diccionario de estadísticas con keys:
        ``original_count``, ``after_eid_dedup``, ``after_doi_dedup``,
        ``total_removed``.

    Example
    -------
    >>> df_clean, stats = run_deduplication_pipeline(df_raw)
    >>> print(stats["total_removed"])
    """
    original = len(df)
    logger.info("Deduplicación iniciada: %d registros", original)

    df = deduplicate_by_eid(df)
    after_eid = len(df)

    df = deduplicate_by_doi(df)
    after_doi = len(df)

    stats = {
        "original_count": original,
        "after_eid_dedup": after_eid,
        "after_doi_dedup": after_doi,
        "total_removed": original - after_doi,
    }

    logger.info(
        "Deduplicación completada: %d → %d (-%d registros)",
        original,
        after_doi,
        stats["total_removed"],
    )
    return df, stats
