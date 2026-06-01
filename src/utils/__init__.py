"""
Paquete de utilidades compartidas del proyecto bibliométrico.

Expone las funciones principales de cada submódulo para acceso directo::

    from src.utils import get_logger, fix_encoding, is_valid_orcid
"""

from src.utils.deduplication import (
    deduplicate_by_doi,
    deduplicate_by_eid,
    run_deduplication_pipeline,
)
from src.utils.logger import get_logger
from src.utils.text_normalization import (
    fix_encoding,
    normalize_issn,
    normalize_name_for_matching,
    normalize_text,
    normalize_title,
    parse_authors_field,
)
from src.utils.validators import (
    is_valid_doi,
    is_valid_eid,
    is_valid_issn,
    is_valid_orcid,
)

__all__ = [
    "get_logger",
    "fix_encoding",
    "normalize_text",
    "normalize_name_for_matching",
    "normalize_title",
    "normalize_issn",
    "parse_authors_field",
    "deduplicate_by_eid",
    "deduplicate_by_doi",
    "run_deduplication_pipeline",
    "is_valid_orcid",
    "is_valid_eid",
    "is_valid_issn",
    "is_valid_doi",
]
