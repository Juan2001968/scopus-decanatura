"""
Descarga año a año (2014–2025) de publicaciones de Universidad del Norte
desde la API de Scopus, generando los CSV que consume el ETL.

Alternativa por API a la descarga manual de CSV documentada en
``docs/query_descarga_scopus.md``. Usa el endpoint Scopus Search con
``view=COMPLETE`` y paginación por cursor, y aplana cada publicación a las
columnas que espera ``src/etl/ingest_publications.py`` (``_COLUMN_MAP``).

Limitaciones (ver el doc):
  - Necesita API key + Insttoken con acceso COMPLETE (suscripción institucional).
  - COMPLETE devuelve 25 registros por página.
  - El campo ``References`` NO lo entrega la Search API: queda vacío. Para
    poblarlo hay que un segundo pase con Abstract Retrieval (view=REF) por EID.

Uso:
    python scripts/06_descargar_scopus_api.py --af-id 60052106
    python scripts/06_descargar_scopus_api.py --af-id "60052106 OR 60110546" \
        --desde 2014 --hasta 2025
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from config.settings import DATA_RAW_DIR
from src.api_scopus.client import ScopusClient, _BASE_URL
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = f"{_BASE_URL}/content/search/scopus"
_PAGE_SIZE = 25  # máximo permitido por la vista COMPLETE


# ---------------------------------------------------------------------------
# Aplanado JSON Scopus -> columnas del ETL
# ---------------------------------------------------------------------------


def _build_author_full_names(authors: List[Dict]) -> str:
    """Construye el campo 'Author full names' con el formato que parsea
    el matching Tier-1: ``Apellido, Nombre (AUTHID); ...``."""
    partes = []
    for a in authors or []:
        authid = a.get("authid", "")
        surname = a.get("surname") or ""
        given = a.get("given-name") or ""
        nombre = f"{surname}, {given}".strip().strip(",").strip()
        if not nombre:
            nombre = a.get("authname", "") or ""
        partes.append(f"{nombre} ({authid})" if authid else nombre)
    return "; ".join(partes)


def _build_author_ids(authors: List[Dict]) -> str:
    return "; ".join(a.get("authid", "") for a in (authors or []) if a.get("authid"))


def _build_authors(authors: List[Dict], creator: str) -> str:
    if authors:
        return "; ".join(a.get("authname", "") for a in authors if a.get("authname"))
    return creator or ""


def _build_affiliations(affs: List[Dict]) -> str:
    nombres = []
    for af in affs or []:
        name = af.get("affilname", "")
        city = af.get("affiliation-city", "")
        country = af.get("affiliation-country", "")
        nombres.append(", ".join(p for p in (name, city, country) if p))
    return "; ".join(nombres)


def _year_from_cover_date(entry: Dict) -> Optional[int]:
    cover = entry.get("prism:coverDate", "")  # 'YYYY-MM-DD'
    if cover and len(cover) >= 4 and cover[:4].isdigit():
        return int(cover[:4])
    return None


def _flatten_entry(entry: Dict) -> Dict:
    """Convierte una entrada de Scopus Search (COMPLETE) en una fila con los
    NOMBRES DE COLUMNA EXACTOS que espera el ETL (`_COLUMN_MAP`)."""
    authors = entry.get("author") or []
    affs = entry.get("affiliation") or []
    page_range = entry.get("prism:pageRange") or ""
    page_start, page_end = "", ""
    if "-" in page_range:
        page_start, _, page_end = page_range.partition("-")
    elif page_range:
        page_start = page_range

    return {
        "Authors": _build_authors(authors, entry.get("dc:creator", "")),
        "Author full names": _build_author_full_names(authors),
        "Author(s) ID": _build_author_ids(authors),
        "Document Title": entry.get("dc:title", ""),
        "Year": _year_from_cover_date(entry),
        "EID": entry.get("eid", ""),
        "Source title": entry.get("prism:publicationName", ""),
        "Abbreviated Source Title": entry.get("prism:publicationName", ""),
        "Volume": entry.get("prism:volume", ""),
        "Issue": entry.get("prism:issueIdentifier", ""),
        "Page start": page_start,
        "Page end": page_end,
        "Page count": "",
        "Cited by": entry.get("citedby-count", ""),
        "DOI": entry.get("prism:doi", ""),
        "Affiliations": _build_affiliations(affs),
        "Index Keywords": entry.get("authkeywords", ""),
        "References": "",  # no disponible en Search API (ver docstring)
        "Correspondence Address": "",
        "Publisher": entry.get("dc:publisher", ""),
        "ISSN": entry.get("prism:issn", "") or entry.get("prism:eIssn", ""),
        "PubMed ID": entry.get("pubmed-id", ""),
        "Language of Original Document": "",  # no expuesto en Search
        "Document Type": entry.get("subtypeDescription", ""),
        "Publication Stage": entry.get("prism:publicationStage", ""),
        "Open Access": entry.get("openaccess", ""),
    }


# ---------------------------------------------------------------------------
# Descarga por año con paginación por cursor
# ---------------------------------------------------------------------------


def descargar_anio(client: ScopusClient, af_id: str, anio: int) -> pd.DataFrame:
    query = f"AF-ID({af_id}) AND PUBYEAR = {anio}"
    cursor = "*"
    filas: List[Dict] = []

    logger.info("Año %d — query: %s", anio, query)

    while cursor is not None:
        data = client.get(
            url=_SEARCH_URL,
            params={
                "query": query,
                "view": "COMPLETE",
                "count": str(_PAGE_SIZE),
                "cursor": cursor,
                "sort": "coverDate",
            },
            use_cache=False,  # descarga fresca
        )
        if not data:
            break

        results = data.get("search-results", {})
        entries = results.get("entry", []) or []

        # Scopus mete un 'error' dummy en entry cuando no hay resultados
        if len(entries) == 1 and "error" in entries[0]:
            break

        for e in entries:
            filas.append(_flatten_entry(e))

        next_cursor = results.get("cursor", {}).get("@next")
        # Cortar si no avanza o no hay más entradas
        if not entries or next_cursor in (None, cursor):
            cursor = None
        else:
            cursor = next_cursor

        time.sleep(0.2)  # cortesía con el rate limit

    df = pd.DataFrame(filas)
    logger.info("Año %d — %d publicaciones", anio, len(df))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga Scopus por año vía API.")
    parser.add_argument(
        "--af-id",
        required=True,
        help="AF-ID de Uninorte. Para varios: \"60052106 OR 60110546\".",
    )
    parser.add_argument("--desde", type=int, default=2014)
    parser.add_argument("--hasta", type=int, default=2025)
    parser.add_argument(
        "--salida",
        type=Path,
        default=DATA_RAW_DIR,
        help="Directorio de salida (default: data/raw/).",
    )
    args = parser.parse_args()

    args.salida.mkdir(parents=True, exist_ok=True)
    client = ScopusClient()

    if not client.test_connection():
        logger.error("No se pudo conectar a la API de Scopus. Revisa el .env.")
        return

    total = 0
    for anio in range(args.desde, args.hasta + 1):
        df = descargar_anio(client, args.af_id, anio)
        if df.empty:
            logger.warning("Año %d sin resultados; se omite.", anio)
            continue
        out = args.salida / f"scopus_{anio}.csv"
        df.to_csv(out, index=False, encoding="utf-8-sig")
        logger.info("Guardado %s (%d filas)", out, len(df))
        total += len(df)

    logger.info("=== Descarga finalizada: %d publicaciones en total ===", total)


if __name__ == "__main__":
    main()
