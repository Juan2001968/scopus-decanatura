"""
Limpieza y estandarización de publicaciones bibliométricas.

Recibe el DataFrame consolidado de ``ingest_publications.load_all_publications()``
y aplica: eliminación de registros inválidos, deduplicación por EID/DOI,
estandarización de campos de texto y generación de columnas derivadas.

Fase 3 del pipeline ETL. No interactúa con la base de datos.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Tuple

import pandas as pd

from config.settings import ROLLING_WINDOW_YEARS
from src.utils.deduplication import deduplicate_by_doi, deduplicate_by_eid
from src.utils.logger import get_logger
from src.utils.text_normalization import normalize_title, parse_authors_field
from src.utils.validators import is_valid_eid

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------


def remove_invalid_records(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina registros que no cumplen requisitos mínimos de calidad.

    Descarta filas sin EID, sin título, sin año de publicación o
    con EID en formato inválido.

    Parameters
    ----------
    df:
        DataFrame de publicaciones tras la ingesta.

    Returns
    -------
    pd.DataFrame
        DataFrame filtrado sin registros inválidos.

    Example
    -------
    >>> df_clean = remove_invalid_records(df_raw)
    """
    initial = len(df)

    # Sin EID
    mask_eid = df["eid"].notna() & (df["eid"].astype(str).str.strip() != "")
    removed_eid = (~mask_eid).sum()
    df = df[mask_eid]
    if removed_eid:
        logger.info("Eliminadas %d filas sin EID", removed_eid)

    # Sin título
    mask_titulo = df["titulo"].notna() & (df["titulo"].astype(str).str.strip() != "")
    removed_titulo = (~mask_titulo).sum()
    df = df[mask_titulo]
    if removed_titulo:
        logger.info("Eliminadas %d filas sin titulo", removed_titulo)

    # Sin año
    mask_anio = df["anio_publicacion"].notna()
    removed_anio = (~mask_anio).sum()
    df = df[mask_anio]
    if removed_anio:
        logger.info("Eliminadas %d filas sin anio de publicacion", removed_anio)

    # EID con formato inválido
    mask_valid_eid = df["eid"].apply(is_valid_eid)
    removed_invalid = (~mask_valid_eid).sum()
    if removed_invalid:
        bad_eids = df.loc[~mask_valid_eid, "eid"].head(5).tolist()
        logger.warning(
            "Eliminadas %d filas con EID invalido (ejemplos: %s)",
            removed_invalid,
            bad_eids,
        )
    df = df[mask_valid_eid]

    total_removed = initial - len(df)
    logger.info(
        "Validacion completada: %d → %d (-%d registros invalidos)",
        initial,
        len(df),
        total_removed,
    )
    return df.reset_index(drop=True)


def standardize_text_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Estandariza campos de texto para presentación en dashboard.

    Aplica strip y colapso de espacios múltiples. No normaliza
    agresivamente (conserva mayúsculas y acentos originales).

    Parameters
    ----------
    df:
        DataFrame de publicaciones.

    Returns
    -------
    pd.DataFrame
        DataFrame con campos de texto estandarizados.
    """
    def _clean_str(s: object) -> object:
        """Strip y colapsar espacios, preservando None/NaN."""
        if pd.isna(s):
            return s
        text = str(s).strip()
        return re.sub(r"\s+", " ", text) if text else None

    def _clean_title_case(s: object) -> object:
        """Strip, colapsar espacios y aplicar title case."""
        cleaned = _clean_str(s)
        return cleaned.title() if isinstance(cleaned, str) else cleaned

    # Campos con strip simple
    for col in ("titulo", "source_title", "publisher", "open_access",
                "publication_stage"):
        if col in df.columns:
            df[col] = df[col].apply(_clean_str)

    # Campos con title case
    for col in ("tipo_documental", "idioma"):
        if col in df.columns:
            df[col] = df[col].apply(_clean_title_case)

    logger.info("Campos de texto estandarizados")
    return df


def resolve_citation_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Resuelve duplicados entre CSV anuales conservando el registro más citado.

    Pre-ordena por ``cited_by_count`` descendente para que las funciones
    de deduplicación (que usan ``keep='first'``) conserven el registro
    con mayor conteo de citas.

    Parameters
    ----------
    df:
        DataFrame de publicaciones (puede contener duplicados de
        diferentes exportaciones anuales).

    Returns
    -------
    pd.DataFrame
        DataFrame deduplicado por EID y DOI.
    """
    # Pre-ordenar por citas desc para que keep="first" conserve el más citado
    # (las funciones de dedup buscan "Cited by" pero nuestras columnas son
    # estandarizadas; el pre-orden garantiza el comportamiento correcto)
    df = df.sort_values(
        "cited_by_count", ascending=False, na_position="last",
    )

    df = deduplicate_by_eid(df, eid_col="eid")
    df = deduplicate_by_doi(df, doi_col="doi")

    return df


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas derivadas útiles para análisis y filtrado.

    Columnas nuevas:

    - ``titulo_normalizado``: título sin acentos ni puntuación (para búsquedas).
    - ``n_authors``: cantidad de autores en la publicación.
    - ``en_ventana_3_anios``: ``True`` si la publicación cae dentro de la
      ventana móvil definida por ``ROLLING_WINDOW_YEARS``.

    Parameters
    ----------
    df:
        DataFrame de publicaciones limpias.

    Returns
    -------
    pd.DataFrame
        DataFrame con las columnas derivadas agregadas.
    """
    # Título normalizado para búsqueda/deduplicación
    df["titulo_normalizado"] = df["titulo"].apply(
        lambda t: normalize_title(t) if pd.notna(t) else "",
    )

    # Conteo de autores
    df["n_authors"] = df["authors_raw"].apply(
        lambda a: len(parse_authors_field(a)) if pd.notna(a) else 0,
    )

    # Ventana móvil
    anio_actual = datetime.now().year
    anio_inicio_ventana = anio_actual - ROLLING_WINDOW_YEARS + 1
    df["en_ventana_3_anios"] = (
        df["anio_publicacion"] >= anio_inicio_ventana
    )

    logger.info(
        "Columnas derivadas agregadas (ventana: %d–%d)",
        anio_inicio_ventana,
        anio_actual,
    )
    return df


def run_cleaning_pipeline(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Ejecuta el pipeline completo de limpieza en orden.

    Secuencia: validación → deduplicación → estandarización de texto →
    columnas derivadas.

    Parameters
    ----------
    df:
        DataFrame crudo de ``ingest_publications.load_all_publications()``.

    Returns
    -------
    tuple[pd.DataFrame, dict]
        DataFrame limpio y diccionario de estadísticas con keys:
        ``input_count``, ``after_invalid_removal``, ``after_deduplication``,
        ``final_count``, ``years_range``, ``records_in_rolling_window``.

    Example
    -------
    >>> df_clean, stats = run_cleaning_pipeline(df_raw)
    >>> print(stats["final_count"])
    """
    logger.info("=== Pipeline de limpieza iniciado (%d registros) ===", len(df))
    input_count = len(df)

    # Paso 1: Eliminar registros inválidos
    df = remove_invalid_records(df)
    after_invalid = len(df)

    # Paso 2: Deduplicación
    df = resolve_citation_duplicates(df)
    after_dedup = len(df)

    # Paso 3: Estandarizar texto
    df = standardize_text_fields(df)

    # Paso 4: Columnas derivadas
    df = add_derived_columns(df)
    final_count = len(df)

    # Estadísticas
    anio_min = df["anio_publicacion"].min() if not df.empty else None
    anio_max = df["anio_publicacion"].max() if not df.empty else None
    in_window = int(df["en_ventana_3_anios"].sum()) if not df.empty else 0

    stats: Dict[str, object] = {
        "input_count": input_count,
        "after_invalid_removal": after_invalid,
        "after_deduplication": after_dedup,
        "final_count": final_count,
        "years_range": f"{anio_min}-{anio_max}" if anio_min else None,
        "records_in_rolling_window": in_window,
    }

    logger.info(
        "=== Pipeline de limpieza finalizado: %d → %d registros "
        "(-%d invalidos, -%d duplicados) ===",
        input_count,
        final_count,
        input_count - after_invalid,
        after_invalid - after_dedup,
    )
    return df, stats
