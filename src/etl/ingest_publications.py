"""
Ingesta de publicaciones desde CSV anuales de Scopus (2014–2025).

Descubre los archivos CSV en ``data/raw/``, los lee, consolida en un
único DataFrame y estandariza columnas y tipos para alinearlos con
el modelo ORM ``Publicacion``.

Fase 2 del pipeline ETL. No deduplica ni interactúa con la base de datos.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import pandas as pd

from config.settings import DATA_RAW_DIR
from src.utils.logger import get_logger
from src.utils.text_normalization import normalize_issn

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Mapeo de columnas Scopus → nombres internos (snake_case / ORM)
# ---------------------------------------------------------------------------

_COLUMN_MAP = {
    "Authors": "authors_raw",
    "Author full names": "author_full_names",
    "Author(s) ID": "author_scopus_ids",   # IDs numéricos de Scopus — clave para el matching Tier-1
    "Document Title": "titulo",
    "Year": "anio_publicacion",
    "EID": "eid",
    "Source title": "source_title",
    "Volume": "volumen",
    "Issue": "issue",
    "Page start": "page_start",
    "Page end": "page_end",
    "Page count": "page_count",
    "Cited by": "cited_by_count",
    "DOI": "doi",
    "Affiliations": "affiliations",
    "Index Keywords": "indexed_keywords",
    "References": "referencias_raw",
    "Correspondence Address": "correspondence_address",
    "Publisher": "publisher",
    "ISSN": "issn",
    "PubMed ID": "pubmed_id",
    "Language of Original Document": "idioma",
    "Abbreviated Source Title": "abbreviated_source_title",
    "Document Type": "tipo_documental",
    "Publication Stage": "publication_stage",
    "Open Access": "open_access",
}

_YEAR_PATTERN = re.compile(r"(20[01]\d|202[0-5])")
"""Regex para extraer un año entre 2000 y 2025 del nombre de archivo."""


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------


def discover_scopus_csvs(raw_dir: Optional[Path] = None) -> List[Path]:
    """Descubre CSV de publicaciones en el directorio de datos crudos.

    Excluye archivos de profesores (``Prof_*.csv``) y cualquier archivo
    que no tenga extensión ``.csv``.

    Parameters
    ----------
    raw_dir:
        Directorio a explorar. Si es ``None``, usa
        ``config.settings.DATA_RAW_DIR``.

    Returns
    -------
    list[Path]
        Lista de rutas a los CSV de publicaciones, ordenada por nombre.

    Example
    -------
    >>> csvs = discover_scopus_csvs()
    >>> [f.name for f in csvs]
    ['scopus_2014.csv', 'scopus_2015.csv', ...]
    """
    if raw_dir is None:
        raw_dir = DATA_RAW_DIR

    all_csvs = sorted(raw_dir.glob("*.csv"))
    publication_csvs = [
        f for f in all_csvs if not f.name.startswith("Prof_")
    ]

    logger.info(
        "CSV de publicaciones encontrados en %s: %d archivos",
        raw_dir,
        len(publication_csvs),
    )
    return publication_csvs


def load_single_csv(filepath: Path) -> pd.DataFrame:
    """Lee un CSV de Scopus y agrega metadatos de origen.

    Parameters
    ----------
    filepath:
        Ruta al archivo CSV.

    Returns
    -------
    pd.DataFrame
        DataFrame con columnas originales de Scopus más
        ``_source_file`` y ``_source_year``.

    Example
    -------
    >>> df = load_single_csv(Path("data/raw/scopus_2023.csv"))
    >>> df["_source_file"].iloc[0]
    'scopus_2023.csv'
    """
    df = pd.read_csv(filepath, encoding="utf-8-sig")

    df["_source_file"] = filepath.name

    # Intentar inferir el año desde el nombre del archivo
    match = _YEAR_PATTERN.search(filepath.stem)
    df["_source_year"] = int(match.group(1)) if match else None

    logger.info("  %s: %d filas", filepath.name, len(df))
    return df


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Renombra columnas de Scopus a nombres internos (snake_case / ORM).

    Soporta aliases comunes entre distintas exportaciones de Scopus.
    Además, garantiza columnas mínimas necesarias para las fases
    posteriores del ETL.
    """
    # 1) Renombrado base con el mapa original
    rename_map = {k: v for k, v in _COLUMN_MAP.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    # 2) Aliases frecuentes que no siempre vienen con el mismo nombre
    alias_groups = {
        "titulo": [
            "Title",
            "Document title",
            "Document Title",
            "Titles",
        ],
        "authors_raw": [
            "Authors",
            "Author(s)",
            "Author Names",
        ],
        "author_full_names": [
            "Author full names",
            "Author Full Names",
            "Authors with affiliations",
        ],
        "indexed_keywords": [
            "Index Keywords",
            "Indexed Keywords",
            "Author Keywords",
        ],
        "tipo_documental": [
            "Document Type",
            "Document type",
            "Type",
        ],
        "idioma": [
            "Language of Original Document",
            "Language",
        ],
        "open_access": [
            "Open Access",
            "Open access",
        ],
        "source_title": [
            "Source title",
            "Source Title",
        ],
        "abbreviated_source_title": [
            "Abbreviated Source Title",
            "Abbreviated source title",
        ],
        "cited_by_count": [
            "Cited by",
            "Cited By",
        ],
        "anio_publicacion": [
            "Year",
            "Publication Year",
        ],
        "doi": [
            "DOI",
            "Doi",
        ],
        "eid": [
            "EID",
            "Eid",
        ],
        "issn": [
            "ISSN",
            "Issn",
        ],
        "publisher": [
            "Publisher",
        ],
        "affiliations": [
            "Affiliations",
            "Affiliation",
        ],
        "publication_stage": [
            "Publication Stage",
        ],
        "page_start": [
            "Page start",
        ],
        "page_end": [
            "Page end",
        ],
        "page_count": [
            "Page count",
        ],
        "volume": [
            "Volume",
        ],
        "issue": [
            "Issue",
        ],
        "pubmed_id": [
            "PubMed ID",
        ],
        "referencias_raw": [
            "References",
        ],
        "correspondence_address": [
            "Correspondence Address",
        ],
    }

    for canonical, aliases in alias_groups.items():
        if canonical in df.columns:
            continue
        for alias in aliases:
            if alias in df.columns:
                df = df.rename(columns={alias: canonical})
                break

    # 3) Garantizar columnas mínimas requeridas por clean/normalize/dashboard
    required_defaults = {
        "titulo": None,
        "authors_raw": None,
        "author_full_names": None,
        "author_scopus_ids": None,
        "indexed_keywords": None,
        "tipo_documental": None,
        "idioma": None,
        "open_access": None,
        "source_title": None,
        "abbreviated_source_title": None,
        "publisher": None,
        "issn": None,
        "doi": None,
        "eid": None,
        "anio_publicacion": None,
        "cited_by_count": 0,
        "affiliations": None,
        "publication_stage": None,
        "page_start": None,
        "page_end": None,
        "page_count": None,
        "volume": None,
        "issue": None,
        "pubmed_id": None,
        "referencias_raw": None,
        "correspondence_address": None,
    }

    for col, default in required_defaults.items():
        if col not in df.columns:
            df[col] = default

    mapped = len([c for c in required_defaults if c in df.columns])
    total = len(df.columns)
    logger.info(
        "Columnas estandarizadas: columnas clave disponibles=%d, total=%d",
        mapped,
        total,
    )
    return df

def cast_types(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte tipos de datos a los esperados por el modelo ORM.

    Parameters
    ----------
    df:
        DataFrame con columnas ya estandarizadas.

    Returns
    -------
    pd.DataFrame
        DataFrame con tipos convertidos y columna ``paginas`` construida.
    """
    # anio_publicacion → Int64 (nullable integer)
    if "anio_publicacion" in df.columns:
        df["anio_publicacion"] = pd.to_numeric(
            df["anio_publicacion"], errors="coerce",
        ).astype("Int64")

    # cited_by_count → Int64, NaN → 0
    if "cited_by_count" in df.columns:
        df["cited_by_count"] = (
            pd.to_numeric(df["cited_by_count"], errors="coerce")
            .fillna(0)
            .astype("Int64")
        )

    # eid → string, strip
    if "eid" in df.columns:
        df["eid"] = df["eid"].astype(str).str.strip()
        df.loc[df["eid"].isin(["", "nan", "None"]), "eid"] = pd.NA

    # doi → string, strip; vacíos → None
    if "doi" in df.columns:
        df["doi"] = df["doi"].astype(str).str.strip()
        df.loc[df["doi"].isin(["", "nan", "None"]), "doi"] = None

    # issn → normalizar con normalize_issn
    if "issn" in df.columns:
        df["issn"] = df["issn"].apply(
            lambda x: normalize_issn(x) if pd.notna(x) and str(x).strip() else None
        )

    # Construir columna paginas: "page_start-page_end"
    if "page_start" in df.columns and "page_end" in df.columns:
        start = df["page_start"].astype(str).str.strip()
        end = df["page_end"].astype(str).str.strip()

        def _build_pages(s: str, e: str) -> Optional[str]:
            s_valid = s not in ("", "nan", "None")
            e_valid = e not in ("", "nan", "None")
            if s_valid and e_valid:
                return f"{s}-{e}"
            if s_valid:
                return s
            return None

        df["paginas"] = [_build_pages(s, e) for s, e in zip(start, end)]

    logger.info("Tipos de datos convertidos")
    return df


def load_all_publications(raw_dir: Optional[Path] = None) -> pd.DataFrame:
    """Ejecuta el flujo completo de ingesta de publicaciones.

    Descubre CSVs → lee cada uno → concatena → estandariza columnas →
    convierte tipos.

    Parameters
    ----------
    raw_dir:
        Directorio con los CSV. Si es ``None``, usa el valor por defecto.

    Returns
    -------
    pd.DataFrame
        DataFrame consolidado con columnas estandarizadas y tipos
        convertidos. Puede estar vacío si no se encuentra ningún CSV.

    Example
    -------
    >>> df = load_all_publications()
    >>> df.columns.tolist()[:5]
    ['authors_raw', 'author_full_names', 'titulo', 'anio_publicacion', 'eid']
    """
    logger.info("=== Ingesta de publicaciones iniciada ===")

    csv_files = discover_scopus_csvs(raw_dir)

    if not csv_files:
        logger.warning("No se encontraron CSV de publicaciones")
        return pd.DataFrame()

    # Leer y concatenar
    frames = []
    for filepath in csv_files:
        try:
            df = load_single_csv(filepath)
            frames.append(df)
        except Exception as exc:
            logger.error("Error leyendo %s: %s", filepath.name, exc)

    if not frames:
        logger.warning("Ningun CSV pudo leerse correctamente")
        return pd.DataFrame()

    df_all = pd.concat(frames, ignore_index=True)

    # Estandarizar y castear
    df_all = standardize_columns(df_all)
    df_all = cast_types(df_all)

    # Resumen
    anio_min = df_all["anio_publicacion"].min() if "anio_publicacion" in df_all.columns else "?"
    anio_max = df_all["anio_publicacion"].max() if "anio_publicacion" in df_all.columns else "?"

    logger.info(
        "=== Ingesta de publicaciones finalizada: %d archivos, "
        "%d filas, rango %s–%s ===",
        len(csv_files),
        len(df_all),
        anio_min,
        anio_max,
    )
    return df_all
