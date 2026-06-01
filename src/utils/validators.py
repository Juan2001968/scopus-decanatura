"""
Validación de identificadores bibliométricos.

Funciones puras para verificar formato de ORCID, EID, ISSN y DOI,
más una función de auditoría de DataFrames completos.
"""

import re
from typing import Dict

import pandas as pd


def is_valid_orcid(orcid: str) -> bool:
    """Valida formato ORCID (``XXXX-XXXX-XXXX-XXXX``).

    Parameters
    ----------
    orcid:
        Cadena a validar.

    Returns
    -------
    bool
        ``True`` si cumple el formato ORCID.

    Example
    -------
    >>> is_valid_orcid("0000-0002-7107-7617")
    True
    """
    if not orcid or not isinstance(orcid, str):
        return False
    return bool(re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid.strip()))


def is_valid_eid(eid: str) -> bool:
    """Valida formato EID de Scopus (``2-s2.0-`` seguido de dígitos).

    Parameters
    ----------
    eid:
        Cadena a validar.

    Returns
    -------
    bool
        ``True`` si cumple el formato EID.

    Example
    -------
    >>> is_valid_eid("2-s2.0-85012345678")
    True
    """
    if not eid or not isinstance(eid, str):
        return False
    return bool(re.fullmatch(r"2-s2\.0-\d+", eid.strip()))


def is_valid_issn(issn: str) -> bool:
    """Valida formato ISSN (8 caracteres, último puede ser X, con o sin guion).

    Parameters
    ----------
    issn:
        Cadena a validar.

    Returns
    -------
    bool
        ``True`` si cumple el formato ISSN.

    Example
    -------
    >>> is_valid_issn("1234-5678")
    True
    >>> is_valid_issn("1234567X")
    True
    """
    if not issn or not isinstance(issn, str):
        return False
    cleaned = re.sub(r"[\s\-]", "", issn.strip()).upper()
    return bool(re.fullmatch(r"\d{7}[\dX]", cleaned))


def is_valid_doi(doi: str) -> bool:
    """Valida formato DOI (empieza con ``10.`` seguido de al menos un carácter).

    Parameters
    ----------
    doi:
        Cadena a validar.

    Returns
    -------
    bool
        ``True`` si cumple el formato DOI.

    Example
    -------
    >>> is_valid_doi("10.1016/j.jclepro.2020.123456")
    True
    """
    if not doi or not isinstance(doi, str):
        return False
    return bool(re.fullmatch(r"10\..+", doi.strip()))


def validate_dataframe_ids(df: pd.DataFrame) -> Dict[str, int]:
    """Audita la validez de identificadores en un DataFrame de publicaciones.

    Parameters
    ----------
    df:
        DataFrame con columnas ``EID``, ``DOI`` e ``ISSN`` (opcionales).

    Returns
    -------
    dict[str, int]
        Estadísticas de validez con keys: ``total_rows``, ``valid_eid``,
        ``valid_doi``, ``valid_issn``, ``missing_eid``, ``missing_doi``.

    Example
    -------
    >>> stats = validate_dataframe_ids(df)
    >>> stats["valid_eid"]
    4500
    """
    total = len(df)

    def _count_valid(col: str, validator) -> int:
        if col not in df.columns:
            return 0
        return int(df[col].dropna().astype(str).apply(validator).sum())

    def _count_missing(col: str) -> int:
        if col not in df.columns:
            return total
        return int(df[col].isna().sum() + (df[col].astype(str).str.strip() == "").sum())

    return {
        "total_rows": total,
        "valid_eid": _count_valid("EID", is_valid_eid),
        "valid_doi": _count_valid("DOI", is_valid_doi),
        "valid_issn": _count_valid("ISSN", is_valid_issn),
        "missing_eid": _count_missing("EID"),
        "missing_doi": _count_missing("DOI"),
    }
