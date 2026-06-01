"""
Vinculación de publicaciones con profesores de la División.

Jerarquía de evidencia (de más a menos confiable):
  Tier 1 — Scopus Author ID exacto: extrae el ID numérico del campo
            ``Author full names`` (formato: "García, Juan (57214321859)")
            y lo cruza contra los Auth_IDs registrados en df_autores_scopus.
  Tier 2 — Nombre exacto: variantes normalizadas del nombre (comma-aware,
            con variantes de abreviatura para cubrir "García, Juan C." vs
            "García, Juan Carlos").
  Tier 3 — Fuzzy restringido: solo cuando la publicación tiene al menos una
            afiliación Uninorte confirmada (necesario pero no suficiente).

Fase 6 del pipeline ETL. No interactúa con la base de datos.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional, Set, Tuple

import pandas as pd
from fuzzywuzzy import fuzz

from config.settings import DATA_INTERIM_DIR, FUZZY_MATCH_THRESHOLD
from src.utils.logger import get_logger
from src.utils.text_normalization import (
    normalize_name_for_matching,
    parse_authors_field,
)

logger = get_logger(__name__)

# Scopus Author IDs are 10–11 digit numbers enclosed in parentheses at the
# end of each entry in the "Author full names" field.
_SCOPUS_ID_RE = re.compile(r"\((\d{10,11})\)\s*$")

# Grey zone eliminated: _GREY_ZONE_LOW == threshold disables the zone.
# Paper-level affiliations cover all co-authors; they cannot validate a
# specific author's institution, so the zone was a source of false positives.
_GREY_ZONE_LOW: float = FUZZY_MATCH_THRESHOLD

_AFFILIATION_KEYWORDS: List[str] = [
    "universidad del norte",
    "uninorte",
    "universidad del norte barranquilla",
    "univ. del norte",
    "univ del norte",
    "university of the north",
]

_STOPWORDS: Set[str] = {
    "de", "del", "la", "las", "los", "y", "e", "da", "do", "dos",
    "van", "von",
}


# ---------------------------------------------------------------------------
# Low-level text helpers
# ---------------------------------------------------------------------------


def _normalize_affiliation(text: str) -> str:
    if not text:
        return ""
    return text.lower().strip()


def _split_on_comma(raw_name: str) -> Tuple[str, str]:
    """Split 'Apellido(s), Nombre(s)' on the FIRST comma.

    Returns (surname_part, given_part).  If no comma is present, returns
    (full_name, '').
    """
    raw = str(raw_name).strip()
    if "," in raw:
        idx = raw.index(",")
        return raw[:idx].strip(), raw[idx + 1:].strip()
    return raw, ""


def _extract_scopus_id_from_full_name_entry(
    entry: str,
) -> Tuple[str, Optional[str]]:
    """Parse one entry of the Author full names field.

    Examples
    --------
    'García, Juan Carlos (57214321859)' → ('García, Juan Carlos', '57214321859')
    'de Hoyos-Castro F.E.'              → ('de Hoyos-Castro F.E.', None)
    """
    entry = entry.strip()
    m = _SCOPUS_ID_RE.search(entry)
    if m:
        auth_id = m.group(1)
        name = entry[:m.start()].strip()
        return name, auth_id
    return entry, None


def _split_full_names_field(value: object) -> List[str]:
    """Split the 'Author full names' semicolon-delimited field."""
    if pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r";\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _clean_tokens_for_variants(name: str) -> List[str]:
    norm = normalize_name_for_matching(name)
    if not norm:
        return []
    return [t for t in norm.split() if t and t not in _STOPWORDS]


def _surname_key_from_tokens(tokens: List[str]) -> str:
    """Return the primary surname key used for bucket lookup.

    Uses tokens[0] — the first meaningful token after stopword removal,
    which is the first surname word in 'Apellido, Nombre' format.
    """
    if not tokens:
        return ""
    return tokens[0]


def _generate_name_variants(name: object) -> Set[str]:
    """Generate a set of normalized name variants for exact matching.

    Comma-aware: splits 'Apellido(s), Nombre(s)' before normalizing so the
    surname and given-name portions can be recombined with abbreviation
    variants.  This lets 'García López, Juan C.' match the professor entry
    'García López, Juan Carlos' stored in the name index, and vice-versa.

    Key variants generated:
    - Full form: all surname tokens + all given tokens.
    - Reversed: given tokens + surname tokens.
    - Last-given abbreviated: surname + given[:-1] + first-letter-of-last-given
      (enables matching when Scopus lists an abbreviated middle/second given
      name while the professor file has the full form, or the reverse).
    - Drop-compound-surname: first surname token + given tokens
      (for professors whose compound surname is sometimes dropped in papers).
    - Compact: first surname token + last given token.
    """
    if pd.isna(name):
        return set()
    raw = str(name).strip()
    if not raw:
        return set()

    variants: Set[str] = set()
    surname_raw, given_raw = _split_on_comma(raw)

    surname_tokens = _clean_tokens_for_variants(surname_raw)
    given_tokens = _clean_tokens_for_variants(given_raw) if given_raw else []

    if not surname_tokens and not given_tokens:
        return set()

    all_tokens = surname_tokens + given_tokens
    full = " ".join(all_tokens)
    if full:
        variants.add(full)

    if given_tokens:
        last_given = given_tokens[-1]

        # Reversed order
        variants.add(" ".join(given_tokens + surname_tokens))

        # Abbreviation variants: abbreviate LAST given-name token when it is a
        # full word (not already a single initial).  Both directions so the
        # index covers whichever side has the full vs. abbreviated form.
        abbrev_given: Optional[List[str]] = None
        if len(given_tokens) >= 2 and len(last_given) > 1:
            abbrev_given = given_tokens[:-1] + [last_given[0]]
            variants.add(" ".join(surname_tokens + abbrev_given))
            variants.add(" ".join(abbrev_given + surname_tokens))

        # Drop-compound-surname variants (first surname + all given)
        if len(surname_tokens) >= 2:
            t0 = surname_tokens[0]
            if len(t0) > 1:
                variants.add(" ".join([t0] + given_tokens))
                variants.add(" ".join(given_tokens + [t0]))
                if abbrev_given:
                    variants.add(" ".join([t0] + abbrev_given))

        # Compact: first surname + last given (both must be full words)
        t0 = surname_tokens[0]
        if len(t0) > 1 and len(last_given) > 1:
            variants.add(f"{t0} {last_given}")
            variants.add(f"{last_given} {t0}")
    else:
        # No comma found: flat token processing (non-standard format fallback)
        if len(all_tokens) >= 2:
            first = all_tokens[0]
            last = all_tokens[-1]
            if len(first) > 1 and len(last) > 1:
                variants.add(f"{first} {last}")
                variants.add(f"{last} {first}")

    return {v.strip() for v in variants if v and len(v.strip()) >= 3}


# ---------------------------------------------------------------------------
# Candidate extraction from publication rows
# ---------------------------------------------------------------------------


def _extract_pub_auth_id_candidates(
    pub: pd.Series,
) -> List[Tuple[str, str]]:
    """Extract (name, scopus_author_id) pairs from a publication row.

    Strategy (in order of preference):
    1. ``author_scopus_ids`` — the dedicated 'Author(s) ID' column mapped by
       ingest_publications.  Clean semicolon-delimited integers, no parsing
       needed.  Names are filled from ``author_full_names`` when available.
    2. ``author_full_names`` — fallback regex extraction of (ID) suffixes when
       the dedicated column is absent (legacy data or manual loads).
    """
    seen_ids: Set[str] = set()
    pairs: List[Tuple[str, str]] = []

    # Build a name lookup from author_full_names (id → name) for annotation
    name_by_id: Dict[str, str] = {}
    full_names_val = pub.get("author_full_names", "")
    if pd.notna(full_names_val) and str(full_names_val).strip():
        for entry in _split_full_names_field(str(full_names_val)):
            n, aid = _extract_scopus_id_from_full_name_entry(entry)
            if aid:
                name_by_id[aid] = n

    # Source 1: dedicated author_scopus_ids column (preferred)
    raw_ids = pub.get("author_scopus_ids", "")
    if pd.notna(raw_ids) and str(raw_ids).strip():
        for part in str(raw_ids).split(";"):
            auth_id = part.strip()
            if auth_id and auth_id not in ("nan", "None") and auth_id not in seen_ids:
                seen_ids.add(auth_id)
                pairs.append((name_by_id.get(auth_id, ""), auth_id))

    # Source 2: fallback — parse (ID) from author_full_names
    if not pairs and pd.notna(full_names_val) and str(full_names_val).strip():
        for entry in _split_full_names_field(str(full_names_val)):
            n, auth_id = _extract_scopus_id_from_full_name_entry(entry)
            if auth_id and auth_id not in seen_ids:
                seen_ids.add(auth_id)
                pairs.append((n, auth_id))

    return pairs


def _extract_publication_author_candidates(pub: pd.Series) -> List[str]:
    """Return deduplicated author name candidates from both author fields.

    Draws from:
    - ``authors_raw`` (Authors field, semicolon-delimited, abbreviated names).
    - ``author_full_names`` (Author full names field, IDs stripped).
    """
    candidates: List[str] = []

    authors_raw = pub.get("authors_raw", "")
    if pd.notna(authors_raw):
        candidates.extend(parse_authors_field(str(authors_raw)))

    author_full_names = pub.get("author_full_names", "")
    if pd.notna(author_full_names):
        for entry in _split_full_names_field(str(author_full_names)):
            name, _ = _extract_scopus_id_from_full_name_entry(entry)
            if name:
                candidates.append(name)

    seen: Set[str] = set()
    out: List[str] = []
    for c in candidates:
        key = normalize_name_for_matching(c)
        if key and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _is_name_specific_enough(name: str) -> bool:
    """Return True only if the name has ≥2 tokens with more than 1 character.

    Blocks highly abbreviated entries like 'García, J.' that cannot be safely
    attributed to a specific professor — 'garcia j' has only one real token
    ('garcia'), making it impossible to distinguish 'García, Juan' from
    'García, Jorge'.
    """
    norm = normalize_name_for_matching(name)
    real_tokens = [t for t in norm.split() if len(t) > 1]
    return len(real_tokens) >= 2


def _best_fuzzy_score(a: str, b: str) -> float:
    s1 = fuzz.token_sort_ratio(a, b)
    s2 = fuzz.partial_ratio(a, b)
    s3 = fuzz.ratio(a, b)
    return max(s1, s2, s3) / 100.0


def _author_tokens(author_name: str) -> List[str]:
    return _clean_tokens_for_variants(author_name)


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------


def _build_auth_id_index(df_autores_scopus: pd.DataFrame) -> Dict[str, str]:
    """Build Scopus Author ID → ORCID lookup from the professor profiles table."""
    idx: Dict[str, str] = {}
    for _, row in df_autores_scopus.iterrows():
        orcid = row.get("orcid")
        auth_id = row.get("scopus_author_id")
        if pd.notna(orcid) and pd.notna(auth_id):
            key = str(auth_id).strip()
            if key:
                idx[key] = str(orcid).strip()
    logger.info("Indice de Auth_IDs construido: %d entradas", len(idx))
    return idx


def build_professor_name_index(
    df_autores_scopus: pd.DataFrame,
    df_profesores: pd.DataFrame,
) -> Dict[str, str]:
    """Build normalized name variant → ORCID lookup.

    Ambiguous variants (mapping to 2+ distinct ORCIDs) are excluded to avoid
    false positives when two professors share the same name pattern.
    """
    variant_to_orcids: Dict[str, Set[str]] = {}

    for _, row in df_profesores.iterrows():
        orcid = row.get("orcid")
        nombre = row.get("nombre_normalizado")
        if pd.notna(orcid) and pd.notna(nombre):
            for variant in _generate_name_variants(str(nombre)):
                variant_to_orcids.setdefault(variant, set()).add(str(orcid))

    for _, row in df_autores_scopus.iterrows():
        orcid = row.get("orcid")
        nombre = row.get("nombre_scopus")
        if pd.notna(orcid) and pd.notna(nombre):
            for variant in _generate_name_variants(str(nombre)):
                variant_to_orcids.setdefault(variant, set()).add(str(orcid))

    index: Dict[str, str] = {
        variant: next(iter(orcids))
        for variant, orcids in variant_to_orcids.items()
        if len(orcids) == 1
    }

    ambiguous = sum(1 for v in variant_to_orcids.values() if len(v) > 1)
    logger.info(
        "Indice de nombres construido: %d entradas unicas no ambiguas "
        "(%d variantes ambiguas descartadas, %d profesores, %d perfiles Scopus)",
        len(index),
        ambiguous,
        len(df_profesores),
        len(df_autores_scopus),
    )
    return index


def build_surname_bucket_index(
    name_index: Dict[str, str],
) -> DefaultDict[str, List[Tuple[str, str]]]:
    buckets: DefaultDict[str, List[Tuple[str, str]]] = defaultdict(list)
    for variant, orcid in name_index.items():
        tokens = _clean_tokens_for_variants(variant)
        surname_key = _surname_key_from_tokens(tokens)
        if surname_key:
            buckets[surname_key].append((variant, orcid))
    return buckets


# ---------------------------------------------------------------------------
# Match functions (one per tier)
# ---------------------------------------------------------------------------


def match_by_auth_id(
    auth_id_candidates: List[Tuple[str, str]],
    auth_id_index: Dict[str, str],
) -> List[Tuple[str, str, float]]:
    """Tier 1: exact Scopus Author ID match."""
    results: List[Tuple[str, str, float]] = []
    for name, auth_id in auth_id_candidates:
        if auth_id in auth_id_index:
            results.append((name, auth_id_index[auth_id], 1.0))
    return results


def match_exact(
    authors_parsed: List[str],
    name_index: Dict[str, str],
) -> List[Tuple[str, str, float]]:
    """Tier 2: exact normalized name variant lookup."""
    results: List[Tuple[str, str, float]] = []
    for author in authors_parsed:
        if not _is_name_specific_enough(author):
            continue
        variants = _generate_name_variants(author)
        found_orcid: Optional[str] = None
        for variant in variants:
            if variant in name_index:
                found_orcid = name_index[variant]
                break
        if found_orcid:
            results.append((author, found_orcid, 1.0))
    return results


def match_fuzzy_fast(
    authors_parsed: List[str],
    name_index: Dict[str, str],
    surname_buckets: DefaultDict[str, List[Tuple[str, str]]],
    threshold: float = FUZZY_MATCH_THRESHOLD,
) -> List[Tuple[str, str, float]]:
    """Tier 3: fuzzy match restricted to the same-surname bucket."""
    results: List[Tuple[str, str, float]] = []
    for author in authors_parsed:
        tokens = _author_tokens(author)
        if not tokens:
            continue
        surname_key = _surname_key_from_tokens(tokens)
        candidate_pool = surname_buckets.get(surname_key, [])
        if not candidate_pool:
            continue
        author_variants = _generate_name_variants(author)
        best_score = 0.0
        best_orcid = ""
        for author_variant in author_variants:
            for idx_name, orcid in candidate_pool:
                score = _best_fuzzy_score(author_variant, idx_name)
                if score > best_score:
                    best_score = score
                    best_orcid = orcid
        if best_score >= threshold:
            results.append((author, best_orcid, best_score))
    return results


def validate_by_affiliation(
    affiliations: object,
    threshold_low: float = _GREY_ZONE_LOW,
    threshold_high: float = FUZZY_MATCH_THRESHOLD,
) -> bool:
    del threshold_low, threshold_high
    if pd.isna(affiliations):
        return False
    aff_lower = _normalize_affiliation(str(affiliations))
    return any(kw in aff_lower for kw in _AFFILIATION_KEYWORDS)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def link_publications_to_professors(
    df_publications: pd.DataFrame,
    df_profesores: pd.DataFrame,
    df_autores_scopus: pd.DataFrame,
) -> pd.DataFrame:
    out_cols = [
        "eid",
        "orcid",
        "metodo_vinculacion",
        "score_similitud",
        "nombre_autor_original",
    ]

    if df_publications.empty or df_profesores.empty:
        logger.warning("DataFrames vacios — no se puede vincular")
        return pd.DataFrame(columns=out_cols)

    auth_id_index = _build_auth_id_index(df_autores_scopus)
    name_index = build_professor_name_index(df_autores_scopus, df_profesores)
    if not auth_id_index and not name_index:
        logger.warning("Indices vacios — no se puede vincular")
        return pd.DataFrame(columns=out_cols)

    surname_buckets = build_surname_bucket_index(name_index)
    threshold = FUZZY_MATCH_THRESHOLD

    records: List[dict] = []
    total = len(df_publications)
    id_count = 0
    exact_count = 0
    fuzzy_count = 0
    skipped_abbreviated = 0

    for idx, (_, pub) in enumerate(df_publications.iterrows()):
        eid = pub.get("eid")
        if pd.isna(eid):
            continue

        affiliations = pub.get("affiliations")
        matched_orcids: Set[str] = set()
        matched_norm_names: Set[str] = set()

        # --- Tier 1: Scopus Author ID ---
        for author_name, orcid, score in match_by_auth_id(
            _extract_pub_auth_id_candidates(pub), auth_id_index
        ):
            if orcid in matched_orcids:
                continue
            records.append({
                "eid": eid,
                "orcid": orcid,
                "metodo_vinculacion": "id_scopus",
                "score_similitud": score,
                "nombre_autor_original": author_name,
            })
            matched_orcids.add(orcid)
            matched_norm_names.add(normalize_name_for_matching(author_name))
            id_count += 1

        # --- Tier 2: Exact name ---
        authors_candidates = _extract_publication_author_candidates(pub)
        skipped_abbreviated += sum(
            1 for a in authors_candidates if not _is_name_specific_enough(a)
        )

        remaining = [
            a for a in authors_candidates
            if normalize_name_for_matching(a) not in matched_norm_names
        ]

        for author_name, orcid, score in match_exact(remaining, name_index):
            if orcid in matched_orcids:
                continue
            records.append({
                "eid": eid,
                "orcid": orcid,
                "metodo_vinculacion": "exacto",
                "score_similitud": score,
                "nombre_autor_original": author_name,
            })
            matched_orcids.add(orcid)
            matched_norm_names.add(normalize_name_for_matching(author_name))
            exact_count += 1

        # --- Tier 3: Fuzzy (only with confirmed Uninorte affiliation) ---
        remaining = [
            a for a in authors_candidates
            if normalize_name_for_matching(a) not in matched_norm_names
        ]

        if remaining and validate_by_affiliation(affiliations):
            for author_name, orcid, score in match_fuzzy_fast(
                remaining, name_index, surname_buckets, threshold
            ):
                if orcid in matched_orcids:
                    continue
                if score >= threshold:
                    records.append({
                        "eid": eid,
                        "orcid": orcid,
                        "metodo_vinculacion": "fuzzy",
                        "score_similitud": round(score, 4),
                        "nombre_autor_original": author_name,
                    })
                    matched_orcids.add(orcid)
                    fuzzy_count += 1

        if (idx + 1) % 500 == 0:
            logger.info(
                "Progreso vinculacion: %d/%d publicaciones procesadas",
                idx + 1,
                total,
            )

    df_links = (
        pd.DataFrame(records, columns=out_cols)
        if records
        else pd.DataFrame(columns=out_cols)
    )

    logger.info(
        "Vinculacion completada: %d links (%d id_scopus, %d exacto, %d fuzzy) "
        "en %d publicaciones (%d autores abreviados omitidos en Tier-2)",
        len(df_links),
        id_count,
        exact_count,
        fuzzy_count,
        total,
        skipped_abbreviated,
    )
    return df_links.reset_index(drop=True)


def generate_pending_review(
    df_publications: pd.DataFrame,
    df_links: pd.DataFrame,
) -> pd.DataFrame:
    out_cols = [
        "eid",
        "titulo",
        "authors_raw",
        "anio_publicacion",
        "affiliations",
    ]

    if df_publications.empty:
        return pd.DataFrame(columns=out_cols)

    linked_eids = set(df_links["eid"].unique()) if not df_links.empty else set()
    mask = ~df_publications["eid"].isin(linked_eids)
    pending = df_publications.loc[mask].copy()

    available = [c for c in out_cols if c in pending.columns]
    pending = pending[available]

    for c in out_cols:
        if c not in pending.columns:
            pending[c] = None

    pending = pending[out_cols]

    logger.info(
        "Publicaciones sin vincular (pendientes de revision): %d/%d (%.1f%%)",
        len(pending),
        len(df_publications),
        (100.0 * len(pending) / len(df_publications) if len(df_publications) > 0 else 0),
    )
    return pending.reset_index(drop=True)


def run_author_linking(
    df_publications: pd.DataFrame,
    df_profesores: pd.DataFrame,
    df_autores_scopus: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    logger.info(
        "=== Vinculacion de autores iniciada (%d publicaciones, %d profesores, %d perfiles Scopus) ===",
        len(df_publications),
        len(df_profesores),
        len(df_autores_scopus),
    )

    df_links = link_publications_to_professors(
        df_publications,
        df_profesores,
        df_autores_scopus,
    )

    df_pending = generate_pending_review(df_publications, df_links)

    if not df_pending.empty:
        try:
            DATA_INTERIM_DIR.mkdir(parents=True, exist_ok=True)
            pending_path = DATA_INTERIM_DIR / "pending_author_review.csv"
            df_pending.to_csv(pending_path, index=False, encoding="utf-8-sig")
            logger.info("Pendientes de revision guardados en %s", pending_path)
        except Exception as exc:
            logger.warning("No se pudo guardar archivo de pendientes: %s", exc)

    unique_profs = df_links["orcid"].nunique() if not df_links.empty else 0
    unique_pubs = df_links["eid"].nunique() if not df_links.empty else 0

    logger.info(
        "=== Vinculacion finalizada: %d links, %d publicaciones vinculadas, "
        "%d profesores distintos, %d publicaciones pendientes ===",
        len(df_links),
        unique_pubs,
        unique_profs,
        len(df_pending),
    )
    return df_links, df_pending
