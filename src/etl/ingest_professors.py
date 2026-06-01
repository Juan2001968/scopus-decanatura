"""
Ingesta de profesores desde CSV por departamento.

Lee los 3 archivos CSV de profesores (MatyEst, BioyQui, FisyGeo),
corrige encoding, consolida por ORCID y retorna DataFrames listos
para cargar en las tablas ``profesor`` y ``autor_scopus``.

Fase 1 del pipeline ETL. No interactúa con la base de datos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

from config.settings import DATA_RAW_DIR
from src.utils.logger import get_logger
from src.utils.text_normalization import fix_encoding
from src.utils.validators import is_valid_orcid

logger = get_logger(__name__)

# Mapeo fijo: nombre de archivo → código de departamento
_FILE_DEPT_MAP: Dict[str, str] = {
    "Prof_MatyEst.csv": "MAT_EST",
    "Prof_BioyQui.csv": "BIO_QUI",
    "Prof_FisyGeo.csv": "FIS_GEO",
}


def _clean_auth_id(value: object) -> Optional[str]:
    """Convierte Auth_ID a string limpia sin sufijo '.0'.

    Parameters
    ----------
    value:
        Valor crudo de la columna Auth_ID (puede ser float, str o NaN).

    Returns
    -------
    str or None
        Auth_ID como string (ej. ``"56501378100"``) o ``None`` si ausente.
    """
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text if text else None


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------


def load_professor_csv(
    filepath: Path,
    departamento_codigo: str,
) -> pd.DataFrame:
    """Lee un archivo CSV de profesores y agrega el código de departamento.

    Aplica corrección de encoding a nombres, limpia ORCID y Auth_ID,
    y descarta filas con ORCID inválido.

    Parameters
    ----------
    filepath:
        Ruta al archivo CSV.
    departamento_codigo:
        Código del departamento (ej. ``"MAT_EST"``).

    Returns
    -------
    pd.DataFrame
        DataFrame con columnas limpias y ``departamento_codigo`` agregada.

    Example
    -------
    >>> df = load_professor_csv(Path("data/raw/Prof_MatyEst.csv"), "MAT_EST")
    >>> df.columns.tolist()
    ['AuthorName', 'AuthorName_1', 'Auth_ID', 'NumberOfDocuments',
     'SubjectArea', 'Orc_ID', 'departamento_codigo']
    """
    logger.info("Leyendo %s (depto: %s)", filepath.name, departamento_codigo)

    df = pd.read_csv(filepath, encoding="utf-8-sig")

    # Corrección de doble encoding en columnas de nombre
    for col in ("AuthorName", "AuthorName_1"):
        if col in df.columns:
            df[col] = df[col].astype(str).apply(fix_encoding).str.strip()

    # Limpiar ORCID: strip de espacios
    if "Orc_ID" in df.columns:
        df["Orc_ID"] = df["Orc_ID"].astype(str).str.strip()
        # Reemplazar cadenas vacías y "nan" por NaN real
        df["Orc_ID"] = df["Orc_ID"].replace({"": pd.NA, "nan": pd.NA})

    # Limpiar Auth_ID: float → string sin ".0"
    if "Auth_ID" in df.columns:
        df["Auth_ID"] = df["Auth_ID"].apply(_clean_auth_id)

    # Limpiar NumberOfDocuments
    if "NumberOfDocuments" in df.columns:
        df["NumberOfDocuments"] = pd.to_numeric(
            df["NumberOfDocuments"], errors="coerce",
        ).fillna(0).astype(int)

    # Agregar código de departamento
    df["departamento_codigo"] = departamento_codigo

    # Validar ORCID y filtrar inválidos
    valid_mask = df["Orc_ID"].apply(
        lambda x: is_valid_orcid(x) if pd.notna(x) else False
    )
    invalid_count = (~valid_mask).sum()
    if invalid_count > 0:
        invalid_rows = df.loc[~valid_mask, ["AuthorName", "AuthorName_1", "Orc_ID"]]
        for _, row in invalid_rows.iterrows():
            logger.warning(
                "ORCID invalido o ausente: '%s, %s' (Orc_ID='%s') — fila descartada",
                row["AuthorName"],
                row["AuthorName_1"],
                row["Orc_ID"],
            )
    df = df[valid_mask].reset_index(drop=True)

    logger.info(
        "  %s: %d filas validas (%d descartadas por ORCID invalido)",
        filepath.name,
        len(df),
        invalid_count,
    )
    return df


def load_all_professors(raw_dir: Optional[Path] = None) -> pd.DataFrame:
    """Lee los 3 archivos CSV de profesores y los concatena.

    Parameters
    ----------
    raw_dir:
        Directorio que contiene los CSV. Si es ``None``, usa
        ``config.settings.DATA_RAW_DIR``.

    Returns
    -------
    pd.DataFrame
        DataFrame concatenado con todos los profesores de los 3
        departamentos. Puede estar vacío si no se encuentra ningún CSV.

    Example
    -------
    >>> df = load_all_professors()
    >>> df["departamento_codigo"].unique()
    array(['MAT_EST', 'BIO_QUI', 'FIS_GEO'])
    """
    if raw_dir is None:
        raw_dir = DATA_RAW_DIR

    frames = []
    for filename, dept_code in _FILE_DEPT_MAP.items():
        filepath = raw_dir / filename
        if not filepath.exists():
            logger.warning("Archivo no encontrado, se omite: %s", filepath)
            continue
        df = load_professor_csv(filepath, dept_code)
        frames.append(df)

    if not frames:
        logger.warning("Ningun archivo CSV de profesores encontrado en %s", raw_dir)
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    logger.info(
        "Total filas cargadas: %d de %d archivos",
        len(result),
        len(frames),
    )
    return result


def consolidate_professors(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Consolida filas por ORCID y separa profesores de perfiles Scopus.

    Para cada ORCID único genera un registro de profesor (tomando el
    nombre de la variante con mayor ``NumberOfDocuments``) y uno o más
    registros de autor Scopus (uno por cada ``Auth_ID`` distinto).

    Parameters
    ----------
    df:
        DataFrame concatenado de ``load_all_professors()``.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        ``(df_profesores, df_autores_scopus)`` donde:

        - ``df_profesores`` tiene columnas: ``orcid``,
          ``nombre_normalizado``, ``departamento_codigo``.
        - ``df_autores_scopus`` tiene columnas: ``scopus_author_id``,
          ``nombre_scopus``, ``orcid``, ``subject_area``,
          ``numero_documentos_scopus``.

    Example
    -------
    >>> profs, autores = consolidate_professors(df_all)
    >>> len(profs)  # ~52 profesores únicos
    52
    """
    if df.empty:
        logger.warning("DataFrame vacio — nada que consolidar")
        empty_profs = pd.DataFrame(
            columns=["orcid", "nombre_normalizado", "departamento_codigo"],
        )
        empty_autores = pd.DataFrame(
            columns=[
                "scopus_author_id", "nombre_scopus", "orcid",
                "subject_area", "numero_documentos_scopus",
            ],
        )
        return empty_profs, empty_autores

    total_rows = len(df)

    # --- Profesores únicos por ORCID ---
    prof_records = []
    for orcid, group in df.groupby("Orc_ID"):
        # Tomar la fila con mayor NumberOfDocuments para el nombre display
        best = group.sort_values(
            "NumberOfDocuments", ascending=False,
        ).iloc[0]
        prof_records.append({
            "orcid": orcid,
            "nombre_normalizado": f"{best['AuthorName']}, {best['AuthorName_1']}",
            "departamento_codigo": best["departamento_codigo"],
        })

    df_profesores = pd.DataFrame(prof_records)

    # --- Perfiles Scopus (uno por Auth_ID no nulo) ---
    with_auth = df[df["Auth_ID"].notna()].copy()
    # Deduplicar Auth_ID repetidos dentro del mismo ORCID
    with_auth = with_auth.drop_duplicates(subset=["Auth_ID"], keep="first")

    autor_records = []
    for _, row in with_auth.iterrows():
        autor_records.append({
            "scopus_author_id": row["Auth_ID"],
            "nombre_scopus": f"{row['AuthorName']}, {row['AuthorName_1']}",
            "orcid": row["Orc_ID"],
            "subject_area": row.get("SubjectArea"),
            "numero_documentos_scopus": int(row["NumberOfDocuments"]),
        })

    df_autores_scopus = pd.DataFrame(autor_records) if autor_records else pd.DataFrame(
        columns=[
            "scopus_author_id", "nombre_scopus", "orcid",
            "subject_area", "numero_documentos_scopus",
        ],
    )

    # --- Estadísticas ---
    profs_sin_auth = df_profesores[
        ~df_profesores["orcid"].isin(df_autores_scopus["orcid"])
    ]

    logger.info(
        "Consolidacion completada: %d filas → %d profesores unicos, "
        "%d perfiles Scopus, %d profesores sin Auth_ID",
        total_rows,
        len(df_profesores),
        len(df_autores_scopus),
        len(profs_sin_auth),
    )

    return df_profesores, df_autores_scopus


def run_ingest_professors(
    raw_dir: Optional[Path] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Ejecuta el flujo completo de ingesta de profesores.

    Orquesta: ``load_all_professors`` → ``consolidate_professors``.

    Parameters
    ----------
    raw_dir:
        Directorio con los CSV. Si es ``None``, usa el valor por defecto.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        ``(df_profesores, df_autores_scopus)`` listos para carga en BD.

    Example
    -------
    >>> profs, autores = run_ingest_professors()
    >>> profs.columns.tolist()
    ['orcid', 'nombre_normalizado', 'departamento_codigo']
    """
    logger.info("=== Ingesta de profesores iniciada ===")

    df_all = load_all_professors(raw_dir)
    df_profesores, df_autores_scopus = consolidate_professors(df_all)

    logger.info(
        "=== Ingesta de profesores finalizada: %d profesores, %d perfiles Scopus ===",
        len(df_profesores),
        len(df_autores_scopus),
    )

    return df_profesores, df_autores_scopus
