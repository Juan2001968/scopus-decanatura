"""
Normalización de texto para nombres de autores, títulos y fuentes.

Incluye corrección de doble encoding UTF-8/latin-1, normalización
agresiva para matching de nombres y estandarización de ISSN.
"""

import re
import unicodedata
from typing import List, Optional


def fix_encoding(text: str) -> str:
    """Corrige doble encoding UTF-8/latin-1 en cadenas de texto.

    Los CSV de profesores fueron codificados en latin-1 pero leídos como
    UTF-8, produciendo artefactos como ``"GÃ³mez"`` en lugar de ``"Gómez"``.

    Parameters
    ----------
    text:
        Cadena posiblemente dañada por doble encoding.

    Returns
    -------
    str
        Cadena corregida, o la original si no se detecta el problema.

    Example
    -------
    >>> fix_encoding("GÃ³mez")
    'Gómez'
    >>> fix_encoding("Aldana-DomÃ\\xadnguez")
    'Aldana-Domínguez'
    """
    if not text:
        return text or ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def normalize_text(text: str) -> str:
    """Normalización general: strip, colapsar espacios, lowercase.

    Parameters
    ----------
    text:
        Cadena a normalizar.

    Returns
    -------
    str
        Cadena normalizada o cadena vacía si la entrada es ``None``.

    Example
    -------
    >>> normalize_text("  Hola   Mundo  ")
    'hola mundo'
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip()).lower()


def _strip_accents(text: str) -> str:
    """Elimina diacríticos (acentos, tildes) de una cadena."""
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")


def normalize_name_for_matching(name: str) -> str:
    """Normalización agresiva de nombres de autor para comparación.

    Aplica corrección de encoding, lowercase, eliminación de acentos,
    reemplazo de guiones por espacio y eliminación de puntuación.

    Parameters
    ----------
    name:
        Nombre de autor en cualquier formato.

    Returns
    -------
    str
        Nombre normalizado para matching, o cadena vacía.

    Examples
    --------
    >>> normalize_name_for_matching("Gutiérrez-García, Ismael S.")
    'gutierrez garcia ismael s'
    >>> normalize_name_for_matching("de Oro Aguado, Carlos Mario")
    'de oro aguado carlos mario'
    """
    if not name:
        return ""
    text = fix_encoding(name)
    text = text.lower()
    text = _strip_accents(text)
    text = text.replace("-", " ")
    text = re.sub(r"[.,;:]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(title: str) -> str:
    """Normalización de títulos de publicación para deduplicación.

    Lowercase, sin acentos, sin signos de puntuación, espacios colapsados.

    Parameters
    ----------
    title:
        Título original de la publicación.

    Returns
    -------
    str
        Título normalizado, o cadena vacía.

    Example
    -------
    >>> normalize_title("A Novel Approach to...")
    'a novel approach to'
    """
    if not title:
        return ""
    text = title.lower()
    text = _strip_accents(text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_issn(issn: str) -> Optional[str]:
    """Limpia y estandariza un ISSN al formato ``XXXX-XXXX``.

    Parameters
    ----------
    issn:
        ISSN en cualquier formato (con o sin guion, espacios, etc.).

    Returns
    -------
    str or None
        ISSN formateado como ``"XXXX-XXXX"`` o ``None`` si es inválido.

    Example
    -------
    >>> normalize_issn("1234 5678")
    '1234-5678'
    >>> normalize_issn("bad") is None
    True
    """
    if not issn:
        return None
    cleaned = re.sub(r"[\s\-]", "", issn).upper()
    if re.fullmatch(r"\d{7}[\dX]", cleaned):
        return f"{cleaned[:4]}-{cleaned[4:]}"
    return None


def parse_authors_field(authors_str: str) -> List[str]:
    """Parsea el campo ``Authors`` de los CSV de Scopus.

    Scopus separa autores con ``;`` (punto y coma). Formato típico:
    ``"Apellido-Apellido N.I.; Apellido2, N.I.2."``.

    Parameters
    ----------
    authors_str:
        Cadena cruda del campo Authors.

    Returns
    -------
    list[str]
        Lista de nombres de autores individuales.

    Example
    -------
    >>> parse_authors_field("Castañeda-Jinete M.; Maldonado-Pizarro I.M.")
    ['Castañeda-Jinete M.', 'Maldonado-Pizarro I.M.']
    """
    if not authors_str:
        return []
    parts = re.split(r";\s*", authors_str)
    return [p.strip() for p in parts if p.strip()]
