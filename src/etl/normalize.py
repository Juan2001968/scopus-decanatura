"""
Normalización de entidades bibliométricas.

Extrae fuentes (revistas, proceedings) y keywords del DataFrame limpio
de publicaciones, generando tablas normalizadas listas para carga en BD.

Fase 4 del pipeline ETL. No interactúa con la base de datos.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _normalize_source_key(title: object) -> str:
    """Normaliza un source_title para comparación (lowercase, strip)."""
    if pd.isna(title):
        return ""
    return str(title).strip().lower()


def _infer_tipo_fuente(doc_types: pd.Series) -> str:
    """Infiere el tipo de fuente a partir de los tipos documentales asociados.

    Parameters
    ----------
    doc_types:
        Serie con los ``tipo_documental`` de las publicaciones de la fuente.

    Returns
    -------
    str
        ``"Conference Proceedings"``, ``"Book Series"`` o ``"Journal"``.
    """
    if doc_types.empty:
        return "Journal"

    counts = doc_types.str.lower().value_counts()
    most_common = counts.index[0] if len(counts) > 0 else ""

    if "conference paper" in most_common:
        return "Conference Proceedings"
    if "book chapter" in most_common:
        return "Book Series"
    return "Journal"


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------


def extract_fuentes(df: pd.DataFrame) -> pd.DataFrame:
    """Extrae la tabla de fuentes únicas desde el DataFrame de publicaciones.

    Deduplica por ISSN cuando disponible, por ``source_title`` normalizado
    cuando no. Para conflictos de ISSN con títulos distintos, conserva el
    más frecuente. Infiere ``tipo_fuente`` desde los tipos documentales.

    Parameters
    ----------
    df:
        DataFrame limpio de publicaciones (output de ``clean.py``).

    Returns
    -------
    pd.DataFrame
        Fuentes únicas con columnas: ``source_title``,
        ``abbreviated_source_title``, ``issn``, ``tipo_fuente``,
        ``publisher``.

    Example
    -------
    >>> df_fuentes = extract_fuentes(df_clean)
    >>> df_fuentes.columns.tolist()
    ['source_title', 'abbreviated_source_title', 'issn', 'tipo_fuente', 'publisher']
    """
    if df.empty or "source_title" not in df.columns:
        logger.warning("DataFrame vacio o sin source_title")
        return pd.DataFrame(
            columns=["source_title", "abbreviated_source_title",
                     "issn", "tipo_fuente", "publisher"],
        )

    # Columnas de interés (con valores por defecto si faltan)
    cols = ["source_title", "abbreviated_source_title", "issn",
            "publisher", "tipo_documental"]
    work = df[[c for c in cols if c in df.columns]].copy()
    for c in cols:
        if c not in work.columns:
            work[c] = None

    work["_src_key"] = work["source_title"].apply(_normalize_source_key)

    # ------------------------------------------------------------------
    # Parte A: fuentes CON ISSN (deduplicar por issn)
    # ------------------------------------------------------------------
    has_issn = work["issn"].notna() & (work["issn"].astype(str).str.strip() != "")
    df_with_issn = work[has_issn].copy()
    df_without_issn = work[~has_issn].copy()

    fuentes_issn: List[dict] = []
    if not df_with_issn.empty:
        for issn, group in df_with_issn.groupby("issn"):
            # source_title más frecuente para este ISSN
            best_title = group["source_title"].mode().iloc[0] if not group["source_title"].mode().empty else group["source_title"].iloc[0]
            best_abbrev = group["abbreviated_source_title"].mode().iloc[0] if "abbreviated_source_title" in group.columns and not group["abbreviated_source_title"].mode().empty else None
            best_publisher = group["publisher"].mode().iloc[0] if not group["publisher"].mode().empty else None
            tipo = _infer_tipo_fuente(group["tipo_documental"].dropna())

            fuentes_issn.append({
                "source_title": best_title,
                "abbreviated_source_title": best_abbrev,
                "issn": issn,
                "tipo_fuente": tipo,
                "publisher": best_publisher,
                "_src_key": _normalize_source_key(best_title),
            })

    # ------------------------------------------------------------------
    # Parte B: fuentes SIN ISSN (deduplicar por source_title normalizado)
    # ------------------------------------------------------------------
    # Excluir títulos que ya aparecen en fuentes_issn
    issn_keys = {f["_src_key"] for f in fuentes_issn}

    fuentes_no_issn: List[dict] = []
    if not df_without_issn.empty:
        for src_key, group in df_without_issn.groupby("_src_key"):
            if not src_key or src_key in issn_keys:
                continue
            best_title = group["source_title"].mode().iloc[0] if not group["source_title"].mode().empty else group["source_title"].iloc[0]
            best_abbrev = group["abbreviated_source_title"].mode().iloc[0] if "abbreviated_source_title" in group.columns and not group["abbreviated_source_title"].mode().empty else None
            best_publisher = group["publisher"].mode().iloc[0] if not group["publisher"].mode().empty else None
            tipo = _infer_tipo_fuente(group["tipo_documental"].dropna())

            fuentes_no_issn.append({
                "source_title": best_title,
                "abbreviated_source_title": best_abbrev,
                "issn": None,
                "tipo_fuente": tipo,
                "publisher": best_publisher,
                "_src_key": src_key,
            })

    # Combinar y limpiar
    all_fuentes = fuentes_issn + fuentes_no_issn
    if not all_fuentes:
        logger.warning("No se encontraron fuentes")
        return pd.DataFrame(
            columns=["source_title", "abbreviated_source_title",
                     "issn", "tipo_fuente", "publisher"],
        )

    df_fuentes = pd.DataFrame(all_fuentes)
    df_fuentes = df_fuentes.drop(columns=["_src_key"])

    # Limpiar NaN textuales en abbreviated_source_title/publisher
    for col in ("abbreviated_source_title", "publisher"):
        if col in df_fuentes.columns:
            df_fuentes[col] = df_fuentes[col].where(
                df_fuentes[col].notna() & (df_fuentes[col].astype(str) != "nan"),
                None,
            )

    con_issn = df_fuentes["issn"].notna().sum()
    sin_issn = len(df_fuentes) - con_issn

    logger.info(
        "Fuentes extraidas: %d unicas (%d con ISSN, %d sin ISSN)",
        len(df_fuentes),
        con_issn,
        sin_issn,
    )
    return df_fuentes.reset_index(drop=True)


def build_publication_fuente_map(
    df_publications: pd.DataFrame,
    df_fuentes: pd.DataFrame,
) -> Dict[str, str]:
    """Construye un mapa EID → source_title para vincular publicaciones con fuentes.

    Prioriza vinculación por ISSN; usa fallback por ``source_title``
    normalizado cuando el ISSN no está disponible.

    Parameters
    ----------
    df_publications:
        DataFrame de publicaciones limpias.
    df_fuentes:
        DataFrame de fuentes extraídas con ``extract_fuentes()``.

    Returns
    -------
    dict[str, str]
        Diccionario ``{eid: source_title}`` para cada publicación que
        pudo vincularse a una fuente.

    Example
    -------
    >>> pub_map = build_publication_fuente_map(df_pubs, df_fuentes)
    >>> pub_map["2-s2.0-85012345678"]
    'Nature Materials'
    """
    if df_publications.empty or df_fuentes.empty:
        return {}

    # Índice de fuentes por ISSN
    issn_to_title: Dict[str, str] = {}
    for _, row in df_fuentes[df_fuentes["issn"].notna()].iterrows():
        issn_to_title[row["issn"]] = row["source_title"]

    # Índice de fuentes por source_title normalizado
    key_to_title: Dict[str, str] = {}
    for _, row in df_fuentes.iterrows():
        key = _normalize_source_key(row["source_title"])
        if key:
            key_to_title[key] = row["source_title"]

    # Mapear cada publicación
    result: Dict[str, str] = {}
    matched_issn = 0
    matched_title = 0

    for _, pub in df_publications.iterrows():
        eid = pub.get("eid")
        if pd.isna(eid):
            continue

        # Prioridad 1: ISSN
        pub_issn = pub.get("issn")
        if pd.notna(pub_issn) and pub_issn in issn_to_title:
            result[eid] = issn_to_title[pub_issn]
            matched_issn += 1
            continue

        # Prioridad 2: source_title normalizado
        pub_src = _normalize_source_key(pub.get("source_title"))
        if pub_src and pub_src in key_to_title:
            result[eid] = key_to_title[pub_src]
            matched_title += 1
            continue

    unmatched = len(df_publications) - len(result)
    logger.info(
        "Mapa publicacion-fuente: %d vinculadas (%d por ISSN, %d por titulo), "
        "%d sin fuente",
        len(result),
        matched_issn,
        matched_title,
        unmatched,
    )
    return result


def extract_keywords_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Extrae un resumen de indexed keywords por año.

    Parsea el campo ``indexed_keywords`` (separado por ``"; "``),
    normaliza cada keyword (strip, title case) y cuenta frecuencias
    por año.

    Parameters
    ----------
    df:
        DataFrame limpio de publicaciones.

    Returns
    -------
    pd.DataFrame
        Resumen con columnas: ``keyword``, ``anio``, ``frecuencia``.

    Example
    -------
    >>> df_kw = extract_keywords_summary(df_clean)
    >>> df_kw.head()
       keyword            anio  frecuencia
    0  Machine Learning   2023  15
    """
    if df.empty or "indexed_keywords" not in df.columns:
        logger.warning("Sin datos de keywords para procesar")
        return pd.DataFrame(columns=["keyword", "anio", "frecuencia"])

    records: List[dict] = []
    has_kw = df["indexed_keywords"].notna() & (
        df["indexed_keywords"].astype(str).str.strip() != ""
    )

    for _, row in df[has_kw].iterrows():
        anio = row.get("anio_publicacion")
        raw_kw = str(row["indexed_keywords"])
        keywords = [kw.strip().title() for kw in raw_kw.split(";") if kw.strip()]

        for kw in keywords:
            records.append({"keyword": kw, "anio": anio})

    if not records:
        logger.info("No se encontraron keywords")
        return pd.DataFrame(columns=["keyword", "anio", "frecuencia"])

    df_kw = pd.DataFrame(records)
    df_summary = (
        df_kw.groupby(["keyword", "anio"])
        .size()
        .reset_index(name="frecuencia")
        .sort_values(["anio", "frecuencia"], ascending=[True, False])
        .reset_index(drop=True)
    )

    n_unique = df_summary["keyword"].nunique()
    logger.info(
        "Keywords extraidas: %d unicas, %d registros keyword-anio",
        n_unique,
        len(df_summary),
    )
    return df_summary


def run_normalization(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str]]:
    """Ejecuta el pipeline completo de normalización de entidades.

    Secuencia: extracción de fuentes → mapa publicación-fuente →
    resumen de keywords.

    Parameters
    ----------
    df:
        DataFrame limpio de publicaciones (output de ``clean.py``).

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]
        ``(df_fuentes, df_keywords, publication_fuente_map)``.

    Example
    -------
    >>> fuentes, keywords, pub_map = run_normalization(df_clean)
    """
    logger.info("=== Normalizacion de entidades iniciada (%d registros) ===", len(df))

    df_fuentes = extract_fuentes(df)
    pub_fuente_map = build_publication_fuente_map(df, df_fuentes)
    df_keywords = extract_keywords_summary(df)

    logger.info(
        "=== Normalizacion finalizada: %d fuentes, %d keywords unicas, "
        "%d publicaciones vinculadas ===",
        len(df_fuentes),
        df_keywords["keyword"].nunique() if not df_keywords.empty else 0,
        len(pub_fuente_map),
    )
    return df_fuentes, df_keywords, pub_fuente_map
