"""
Paquete de integracion con la API de Scopus.

Modulos:

- **cache**: cache local en disco de respuestas JSON de la API.
- **client**: :class:`ScopusClient` — cliente HTTP base con auth,
  rate limiting, reintentos y cache.
- **author_retrieval**: logica de alto nivel para recuperar y procesar
  datos de autores (h-index, Author IDs, EIDs de publicaciones).
"""

from src.api_scopus.client import ScopusClient
from src.api_scopus.author_retrieval import (
    parse_author_profile,
    parse_author_search,
    parse_publication_eids,
    retrieve_author_by_id,
    retrieve_author_by_orcid,
    retrieve_author_publications_eids,
    enrich_all_professors,
    strengthen_author_links,
)
