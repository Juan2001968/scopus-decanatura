"""
PASO 4 — Matching definitivo publicación-profesor por ORCID.

Las publicaciones exportadas de Scopus no contienen ORCID directamente;
contienen IDs de Scopus en la columna 'Author(s) ID'. Los CSV de profesores
tienen tanto el Auth_ID (Scopus) como el Orc_ID (ORCID). El puente es:

    publicación.Author(s)_ID  →  profesor.Auth_ID  →  profesor.Orc_ID

Este script construye ese puente, genera 5 archivos de salida y muestra
un diagnóstico específico antes de correr el matching completo.

Uso
---
    python -m scripts.04_matching_por_orcid
    python -m scripts.04_matching_por_orcid --anio-inicio 2022
    python -m scripts.04_matching_por_orcid --diagnostico-orcid 0000-0003-1761-4116
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata

# Forzar UTF-8 en la salida estándar para evitar errores en consolas Windows
# que usan cp1252 y no soportan caracteres Unicode como ✓ ✗.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Rutas — se resuelven relativas a la raíz del proyecto
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
_RAW_DIR = _ROOT / "data" / "raw"
_OUT_DIR = _ROOT / "data" / "processed"

# Archivos CSV de profesores por departamento
_PROF_FILES: Dict[str, str] = {
    "Prof_MatyEst.csv": "MAT_EST",
    "Prof_BioyQui.csv": "BIO_QUI",
    "Prof_FisyGeo.csv": "FIS_GEO",
}

# Ventana móvil para el conteo de publicaciones recientes
_ANIO_ACTUAL = datetime.now().year
_ANIO_VENTANA = _ANIO_ACTUAL - 3  # últimos 3 años

# Patrón ORCID estándar: XXXX-XXXX-XXXX-XXXX(X)
_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


# ---------------------------------------------------------------------------
# Corrección de doble encoding UTF-8/latin-1
# (los CSV de profesores fueron codificados en latin-1 y leídos como UTF-8)
# ---------------------------------------------------------------------------

def _fix_encoding(text: str) -> str:
    """Corrige artefactos de doble encoding como 'GÃ³mez' → 'Gómez'."""
    if not text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


# ---------------------------------------------------------------------------
# Normalización de ORCID
# ---------------------------------------------------------------------------

def normalizar_orcid(orcid_raw) -> Optional[str]:
    """
    Convierte cualquier formato de ORCID al estándar sin URL: '0000-0002-1234-5678'.

    Maneja:
    - None / NaN / cadena vacía → None
    - 'https://orcid.org/0000-0002-1234-5678' → normalizado
    - 'http://orcid.org/...' → normalizado
    - Con o sin guiones (16 dígitos sin guiones → inserta guiones)
    - ORCID inválido → None
    """
    if orcid_raw is None:
        return None
    if not isinstance(orcid_raw, str):
        try:
            orcid_raw = str(orcid_raw)
        except Exception:
            return None

    orcid = orcid_raw.strip()
    if not orcid or orcid.lower() in ("nan", "none", ""):
        return None

    # Remover prefijos URL
    for prefix in ("https://orcid.org/", "http://orcid.org/",
                   "https://www.orcid.org/", "http://www.orcid.org/"):
        if orcid.startswith(prefix):
            orcid = orcid[len(prefix):]

    orcid = orcid.strip("/").strip()

    # Si tiene 16 dígitos consecutivos (sin guiones), insertar guiones
    digits_only = re.sub(r"[-\s]", "", orcid)
    if re.match(r"^\d{16}$", digits_only):
        orcid = f"{digits_only[:4]}-{digits_only[4:8]}-{digits_only[8:12]}-{digits_only[12:]}"

    # Validar formato final
    if _ORCID_RE.match(orcid):
        return orcid

    return None  # ORCID inválido


def _limpiar_auth_id(value) -> Optional[str]:
    """Convierte Auth_ID (posiblemente float) a string sin sufijo '.0'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", ""):
        return None
    # Pandas carga enteros grandes como float: '56501378100.0' → '56501378100'
    if text.endswith(".0"):
        text = text[:-2]
    return text if text else None


# ---------------------------------------------------------------------------
# Carga de profesores
# ---------------------------------------------------------------------------

def cargar_profesores() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Lee los 3 CSV de profesores, corrige encoding y consolida por ORCID.

    Retorna
    -------
    df_profesores : DataFrame
        Una fila por ORCID único, con columna 'orcid_norm' validada.
    df_auth_ids : DataFrame
        Una fila por Auth_ID (un profesor puede tener varios perfiles Scopus).
    """
    frames = []
    for filename, dept in _PROF_FILES.items():
        filepath = _RAW_DIR / filename
        if not filepath.exists():
            print(f"  [AVISO] No se encontró {filepath} — se omite.", file=sys.stderr)
            continue

        df = pd.read_csv(filepath, encoding="utf-8-sig", dtype=str)
        df["dept"] = dept

        # Corregir doble encoding en columnas de nombre
        for col in ("AuthorName", "AuthorName_1"):
            if col in df.columns:
                df[col] = df[col].fillna("").apply(_fix_encoding).str.strip()

        frames.append(df)

    if not frames:
        print("ERROR: No se encontró ningún CSV de profesores.", file=sys.stderr)
        sys.exit(1)

    df_all = pd.concat(frames, ignore_index=True)

    # Normalizar campos
    df_all["orcid_norm"] = df_all["Orc_ID"].apply(normalizar_orcid)
    df_all["auth_id_clean"] = df_all["Auth_ID"].apply(_limpiar_auth_id)

    # Nombre completo: "Apellido, Nombre"
    df_all["nombre_completo"] = (
        df_all["AuthorName"].str.strip() + ", " + df_all["AuthorName_1"].str.strip()
    )

    # NumberOfDocuments → entero
    df_all["n_docs_scopus"] = pd.to_numeric(
        df_all.get("NumberOfDocuments", 0), errors="coerce"
    ).fillna(0).astype(int)

    # --- df_profesores: una fila por ORCID único ---
    # Para cada ORCID, tomar la fila con mayor número de documentos como nombre canónico
    prof_records = []
    for orcid, grupo in df_all.groupby("orcid_norm", dropna=True):
        mejor = grupo.sort_values("n_docs_scopus", ascending=False).iloc[0]
        prof_records.append({
            "orcid": orcid,
            "nombre": mejor["nombre_completo"],
            "departamento": mejor["dept"],
            "n_docs_scopus_total": grupo["n_docs_scopus"].sum(),
        })

    df_profesores = pd.DataFrame(prof_records)

    # --- df_auth_ids: mapa Auth_ID → ORCID (uno por fila) ---
    auth_records = []
    for _, row in df_all.iterrows():
        if row["auth_id_clean"] and row["orcid_norm"]:
            auth_records.append({
                "auth_id": row["auth_id_clean"],
                "orcid": row["orcid_norm"],
                "nombre_variante": row["nombre_completo"],
                "dept": row["dept"],
            })

    df_auth_ids = pd.DataFrame(auth_records).drop_duplicates(subset=["auth_id"])

    return df_profesores, df_auth_ids


# ---------------------------------------------------------------------------
# Extracción de Auth_IDs de una publicación
# ---------------------------------------------------------------------------

def extraer_author_ids(pub: pd.Series) -> List[str]:
    """
    Extrae la lista de Scopus Author IDs de una publicación.

    Fuentes (en orden de preferencia):
    1. Columna 'author_scopus_ids' (campo limpio del pipeline ETL, si existe).
    2. Columna 'Author(s) ID' original (separado por ';').
    3. Columna 'author_full_names': extrae IDs entre paréntesis como fallback.
    """
    ids: List[str] = []

    # Fuente 1: columna limpia del pipeline ETL
    raw = pub.get("author_scopus_ids") or pub.get("Author(s) ID") or ""
    if pd.notna(raw) and str(raw).strip():
        for part in str(raw).split(";"):
            part = part.strip()
            if part and part not in ("nan", "None"):
                ids.append(part)

    # Fuente 2: parsear 'author_full_names' si la columna de IDs estaba vacía
    if not ids:
        full_names = pub.get("author_full_names", "") or pub.get("Author full names", "")
        if pd.notna(full_names) and str(full_names).strip():
            for m in re.finditer(r"\((\d{10,11})\)", str(full_names)):
                ids.append(m.group(1))

    return list(dict.fromkeys(ids))  # deduplicar preservando orden


# ---------------------------------------------------------------------------
# Carga de publicaciones
# ---------------------------------------------------------------------------

def cargar_publicaciones(anio_inicio: int, anio_fin: int) -> pd.DataFrame:
    """
    Lee todos los CSV de publicaciones en el rango de años indicado.

    Preserva la columna 'Author(s) ID' que contiene los Scopus Author IDs.
    """
    frames = []
    for year in range(anio_inicio, anio_fin + 1):
        filepath = _RAW_DIR / f"Completo {year}.csv"
        if not filepath.exists():
            continue
        try:
            df = pd.read_csv(filepath, encoding="utf-8-sig", dtype=str)
            df["_anio_archivo"] = year
            frames.append(df)
        except Exception as exc:
            print(f"  [AVISO] Error leyendo {filepath.name}: {exc}", file=sys.stderr)

    if not frames:
        print(
            f"ERROR: No se encontró ningún CSV de publicaciones en {_RAW_DIR}.",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True)

    # Renombrar columnas clave al estándar interno
    rename = {
        "Authors": "authors_raw",
        "Author full names": "author_full_names",
        "Author(s) ID": "author_scopus_ids",  # ← columna crítica que el ETL no mapeaba
        "Title": "titulo",
        "Year": "anio_publicacion",
        "EID": "eid",
        "Source title": "source_title",
        "Affiliations": "affiliations",
        "Document Type": "tipo_documental",
        "Cited by": "cited_by_count",
        "DOI": "doi",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # anio_publicacion → entero
    if "anio_publicacion" in df.columns:
        df["anio_publicacion"] = pd.to_numeric(
            df["anio_publicacion"], errors="coerce"
        ).astype("Int64")

    return df


# ---------------------------------------------------------------------------
# Diagnóstico previo al matching
# ---------------------------------------------------------------------------

def _diagnosticar_orcid(
    orcid: str,
    df_auth_ids: pd.DataFrame,
    df_publicaciones: pd.DataFrame,
) -> None:
    """
    Muestra cuántas publicaciones tienen ese ORCID (vía Auth_ID) en los datos.
    """
    print(f"\n{'='*60}")
    print(f"  DIAGNÓSTICO para ORCID: {orcid}")
    print(f"{'='*60}")

    # Auth_IDs asociados a este ORCID
    auth_ids = df_auth_ids[df_auth_ids["orcid"] == orcid]["auth_id"].tolist()
    if not auth_ids:
        print(f"  ✗ ORCID {orcid} no encontrado en los CSV de profesores.")
        return

    print(f"  Auth_IDs asociados: {', '.join(auth_ids)}")

    # ¿Cuántas publicaciones tienen alguno de esos Auth_IDs?
    total_apariciones = 0
    eids_encontrados: Set[str] = set()

    for _, pub in df_publicaciones.iterrows():
        pub_ids = extraer_author_ids(pub)
        for aid in auth_ids:
            if aid in pub_ids:
                total_apariciones += 1
                eid = str(pub.get("eid", "")).strip()
                if eid and eid not in ("nan", "None"):
                    eids_encontrados.add(eid)
                break  # contar la publicación una sola vez

    print(f"  Publicaciones encontradas por Auth_ID: {len(eids_encontrados)}")
    if len(eids_encontrados) == 0:
        print(
            "  → Los Auth_IDs de este profesor no aparecen en ninguna publicación."
        )
        print(
            "    Posibles causas: los Auth_IDs del CSV son de otro período, o el"
        )
        print(
            "    perfil Scopus fue fusionado/renombrado."
        )
    print(f"{'='*60}\n")


def diagnosticar_problemas(
    df_profesores: pd.DataFrame,
    df_auth_ids: pd.DataFrame,
    df_publicaciones: pd.DataFrame,
    orcid_especifico: Optional[str] = None,
) -> None:
    """
    Diagnóstico previo: muestra el top-5 de profesores con más docs en Scopus
    pero con 0 publicaciones encontradas por Auth_ID.
    """
    print("\n--- Diagnóstico previo al matching ---")

    # Auth_IDs de profesores que sí aparecen en publicaciones
    todos_ids_en_pubs: Set[str] = set()
    for _, pub in df_publicaciones.iterrows():
        todos_ids_en_pubs.update(extraer_author_ids(pub))

    orcids_sin_match = []
    for _, prof in df_profesores.iterrows():
        ids_prof = df_auth_ids[
            df_auth_ids["orcid"] == prof["orcid"]
        ]["auth_id"].tolist()
        tiene_match = any(aid in todos_ids_en_pubs for aid in ids_prof)
        if not tiene_match and ids_prof:
            orcids_sin_match.append(
                (prof["nombre"], prof["orcid"], prof["n_docs_scopus_total"])
            )

    if orcids_sin_match:
        orcids_sin_match.sort(key=lambda x: x[2], reverse=True)
        print(
            "  Profesores con Auth_ID registrado pero SIN publicaciones "
            f"encontradas (top {min(5, len(orcids_sin_match))}):"
        )
        for nombre, orcid, ndocs in orcids_sin_match[:5]:
            print(f"    • {nombre} | ORCID: {orcid} | docs_scopus: {ndocs}")
    else:
        print("  ✓ Todos los profesores con Auth_ID tienen publicaciones.")

    # Diagnóstico de ORCID específico si se solicitó
    if orcid_especifico:
        _diagnosticar_orcid(orcid_especifico, df_auth_ids, df_publicaciones)


# ---------------------------------------------------------------------------
# Matching principal
# ---------------------------------------------------------------------------

def hacer_matching_por_orcid(
    df_profesores: pd.DataFrame,
    df_auth_ids: pd.DataFrame,
    df_publicaciones: pd.DataFrame,
) -> pd.DataFrame:
    """
    Matching exclusivamente por Scopus Author ID → ORCID.

    Para cada publicación extrae los Auth_IDs de sus autores y los busca
    en el mapa auth_id→orcid construido desde los CSV de profesores.
    Si coincide, genera un vínculo (eid, orcid, nombre, dept, confianza).

    Una publicación puede generar varios vínculos si tiene co-autores que
    son profesores de la División.

    Retorna DataFrame con columnas:
        eid, titulo, anio_publicacion, source_title, doi,
        orcid_matched, nombre_matched, departamento_matched,
        auth_id_matched, confianza
    """
    # Mapa auth_id → info del profesor
    auth_to_prof: Dict[str, dict] = {}
    for _, row in df_auth_ids.iterrows():
        orcid = row["orcid"]
        # Obtener nombre/dept del df_profesores
        info = df_profesores[df_profesores["orcid"] == orcid]
        if info.empty:
            continue
        auth_to_prof[row["auth_id"]] = {
            "orcid": orcid,
            "nombre": info.iloc[0]["nombre"],
            "departamento": info.iloc[0]["departamento"],
        }

    # Columnas a preservar de la publicación en la salida
    cols_pub = [
        "eid", "titulo", "anio_publicacion", "source_title",
        "doi", "tipo_documental", "cited_by_count", "affiliations",
    ]

    vinculos: List[dict] = []
    eids_sin_match: List[dict] = []

    for _, pub in df_publicaciones.iterrows():
        eid = str(pub.get("eid", "")).strip()
        if not eid or eid in ("nan", "None"):
            continue

        pub_data = {c: pub.get(c) for c in cols_pub}
        auth_ids_pub = extraer_author_ids(pub)

        encontrados: List[dict] = []
        for aid in auth_ids_pub:
            if aid in auth_to_prof:
                info = auth_to_prof[aid]
                # Evitar duplicar el mismo profesor en la misma publicación
                if info["orcid"] not in {e["orcid_matched"] for e in encontrados}:
                    encontrados.append({
                        **pub_data,
                        "orcid_matched": info["orcid"],
                        "nombre_matched": info["nombre"],
                        "departamento_matched": info["departamento"],
                        "auth_id_matched": aid,
                        "confianza": "ORCID_VIA_AUTH_ID",
                    })

        if encontrados:
            vinculos.extend(encontrados)
        else:
            eids_sin_match.append({
                **pub_data,
                "orcid_matched": None,
                "nombre_matched": None,
                "departamento_matched": None,
                "auth_id_matched": None,
                "confianza": "SIN_MATCH",
            })

    df_vinculos = pd.DataFrame(vinculos) if vinculos else pd.DataFrame()
    df_sin_match = pd.DataFrame(eids_sin_match) if eids_sin_match else pd.DataFrame()

    return df_vinculos, df_sin_match


# ---------------------------------------------------------------------------
# Generación de archivos de salida
# ---------------------------------------------------------------------------

def generar_salidas(
    df_vinculos: pd.DataFrame,
    df_sin_match: pd.DataFrame,
    df_profesores: pd.DataFrame,
    df_auth_ids: pd.DataFrame,
    df_publicaciones: pd.DataFrame,
) -> None:
    """Escribe los 5 archivos de salida en data/processed/."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    anio_vent = _ANIO_VENTANA

    # -----------------------------------------------------------------------
    # 1. publicaciones_matched_v3.csv
    # -----------------------------------------------------------------------
    if not df_vinculos.empty:
        out1 = _OUT_DIR / "publicaciones_matched_v3.csv"
        df_vinculos.to_csv(out1, index=False, encoding="utf-8-sig")
        print(f"  ✓ {out1.name}  ({len(df_vinculos)} vínculos pub×prof)")
    else:
        print("  [AVISO] No se generó publicaciones_matched_v3.csv — sin vínculos.")

    # -----------------------------------------------------------------------
    # 2. resumen_por_profesor_v3.csv
    # -----------------------------------------------------------------------
    # Contar Auth_IDs por ORCID
    auth_ids_por_orcid = df_auth_ids.groupby("orcid")["auth_id"].apply(list).to_dict()

    # Auth_IDs que SÍ aparecen en el corpus de publicaciones
    ids_en_corpus: Set[str] = set()
    for _, pub in df_publicaciones.iterrows():
        ids_en_corpus.update(extraer_author_ids(pub))

    resumen_rows = []
    for _, prof in df_profesores.iterrows():
        orcid = prof["orcid"]

        if not df_vinculos.empty and orcid in df_vinculos["orcid_matched"].values:
            pubs_prof = df_vinculos[df_vinculos["orcid_matched"] == orcid]
            n_pubs = pubs_prof["eid"].nunique()
            anios = pd.to_numeric(pubs_prof["anio_publicacion"], errors="coerce")
            n_pubs_3y = pubs_prof.loc[anios >= anio_vent, "eid"].nunique()
        else:
            n_pubs = 0
            n_pubs_3y = 0

        # Verificar estado del Auth_ID en el corpus
        ids_prof = auth_ids_por_orcid.get(orcid, [])
        ids_en_pub = [aid for aid in ids_prof if aid in ids_en_corpus]

        if not ids_prof:
            estado_auth_id = "SIN_AUTH_ID"
        elif ids_en_pub:
            estado_auth_id = "AUTH_ID_OK"
        else:
            estado_auth_id = "AUTH_ID_NO_ENCONTRADO_EN_PUBS"

        resumen_rows.append({
            "profesor": prof["nombre"],
            "departamento": prof["departamento"],
            "orcid": orcid,
            "auth_ids": "; ".join(ids_prof),
            "n_publicaciones": n_pubs,
            "n_publicaciones_3anios": n_pubs_3y,
            "n_docs_scopus_declarado": prof["n_docs_scopus_total"],
            "estado_auth_id": estado_auth_id,
        })

    df_resumen = (
        pd.DataFrame(resumen_rows)
        .sort_values(["departamento", "n_publicaciones"], ascending=[True, False])
        .reset_index(drop=True)
    )
    out2 = _OUT_DIR / "resumen_por_profesor_v3.csv"
    df_resumen.to_csv(out2, index=False, encoding="utf-8-sig")
    print(f"  ✓ {out2.name}  ({len(df_resumen)} profesores)")

    # -----------------------------------------------------------------------
    # 3. publicaciones_sin_match_v3.csv
    # -----------------------------------------------------------------------
    if not df_sin_match.empty:
        out3 = _OUT_DIR / "publicaciones_sin_match_v3.csv"
        df_sin_match.to_csv(out3, index=False, encoding="utf-8-sig")
        print(f"  ✓ {out3.name}  ({len(df_sin_match)} publicaciones sin match)")

    # -----------------------------------------------------------------------
    # 4. profesores_sin_auth_id_v3.csv
    # -----------------------------------------------------------------------
    profs_sin_id = df_resumen[
        df_resumen["estado_auth_id"].isin(
            ["SIN_AUTH_ID", "AUTH_ID_NO_ENCONTRADO_EN_PUBS"]
        )
    ].copy()
    out4 = _OUT_DIR / "profesores_sin_auth_id_v3.csv"
    profs_sin_id.to_csv(out4, index=False, encoding="utf-8-sig")
    print(f"  ✓ {out4.name}  ({len(profs_sin_id)} profesores requieren atención)")

    # -----------------------------------------------------------------------
    # 5. reporte_calidad_matching_v3.csv
    # -----------------------------------------------------------------------
    calidad_rows = []
    for _, row in df_resumen.iterrows():
        diff = row["n_publicaciones"] - row["n_docs_scopus_declarado"]
        pct = (
            100.0 * row["n_publicaciones"] / row["n_docs_scopus_declarado"]
            if row["n_docs_scopus_declarado"] > 0
            else 0.0
        )
        if row["n_publicaciones"] == 0 and row["estado_auth_id"] != "SIN_AUTH_ID":
            estado = "CRÍTICO — 0 pubs encontradas"
        elif pct < 30:
            estado = f"BAJO — {pct:.0f}% del declarado"
        elif pct > 150:
            estado = f"EXCESO — {pct:.0f}% del declarado"
        else:
            estado = f"OK — {pct:.0f}% del declarado"

        calidad_rows.append({
            "profesor": row["profesor"],
            "departamento": row["departamento"],
            "orcid": row["orcid"],
            "pubs_encontradas": row["n_publicaciones"],
            "pubs_declaradas_scopus": row["n_docs_scopus_declarado"],
            "diferencia": diff,
            "pct_cobertura": round(pct, 1),
            "estado_auth_id": row["estado_auth_id"],
            "estado": estado,
        })

    df_calidad = (
        pd.DataFrame(calidad_rows)
        .sort_values("pubs_encontradas", ascending=False)
        .reset_index(drop=True)
    )
    out5 = _OUT_DIR / "reporte_calidad_matching_v3.csv"
    df_calidad.to_csv(out5, index=False, encoding="utf-8-sig")
    print(f"  ✓ {out5.name}  ({len(df_calidad)} filas)")


# ---------------------------------------------------------------------------
# Resumen en consola
# ---------------------------------------------------------------------------

def imprimir_resumen(
    df_vinculos: pd.DataFrame,
    df_sin_match: pd.DataFrame,
    df_profesores: pd.DataFrame,
    df_auth_ids: pd.DataFrame,
    df_publicaciones: pd.DataFrame,
) -> None:
    """Imprime las estadísticas finales en consola."""
    total_pubs = len(df_publicaciones["eid"].dropna().unique())
    n_vinculos = len(df_vinculos) if not df_vinculos.empty else 0
    eids_con_match = (
        df_vinculos["eid"].nunique() if not df_vinculos.empty else 0
    )
    eids_sin_match = total_pubs - eids_con_match

    n_profs = len(df_profesores)
    n_profs_con_match = (
        df_vinculos["orcid_matched"].nunique() if not df_vinculos.empty else 0
    )
    n_profs_sin_match = n_profs - n_profs_con_match

    # Contar Auth_IDs en el corpus
    ids_en_corpus: Set[str] = set()
    for _, pub in df_publicaciones.iterrows():
        ids_en_corpus.update(extraer_author_ids(pub))
    total_auth_ids = df_auth_ids["auth_id"].nunique()
    auth_ids_encontrados = df_auth_ids[
        df_auth_ids["auth_id"].isin(ids_en_corpus)
    ]["auth_id"].nunique()

    pct_match = 100.0 * eids_con_match / total_pubs if total_pubs else 0.0

    print("\n" + "=" * 60)
    print("  RESUMEN MATCHING POR ORCID (vía Auth_ID)")
    print("=" * 60)
    print(f"  Profesores únicos (por ORCID):       {n_profs}")
    print(f"  Auth_IDs registrados:                {total_auth_ids}")
    print(f"  Auth_IDs encontrados en corpus:      {auth_ids_encontrados} / {total_auth_ids}")
    print()
    print(f"  Publicaciones totales en corpus:     {total_pubs}")
    print(f"  📄 Pubs con match exitoso:           {eids_con_match} ({pct_match:.1f}%)")
    print(f"  📄 Pubs sin match:                   {eids_sin_match} ({100-pct_match:.1f}%)")
    print(f"  Total vínculos pub×prof generados:   {n_vinculos}")
    print()
    print(f"  ✓ Profesores con publicaciones:      {n_profs_con_match}")
    print(f"  ✗ Profesores sin publicaciones:      {n_profs_sin_match}")
    print("=" * 60)

    # Top 5 por publicaciones
    if not df_vinculos.empty:
        top = (
            df_vinculos.groupby(["orcid_matched", "nombre_matched"])["eid"]
            .nunique()
            .reset_index()
            .rename(columns={"eid": "n_pubs"})
            .sort_values("n_pubs", ascending=False)
            .head(5)
        )
        print("\n  Top 5 profesores por publicaciones encontradas:")
        for _, row in top.iterrows():
            print(f"    {row['n_pubs']:3d}  {row['nombre_matched']}  [{row['orcid_matched']}]")

    print()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main(
    anio_inicio: int = 2014,
    anio_fin: int = _ANIO_ACTUAL,
    orcid_especifico: Optional[str] = None,
) -> None:
    """Orquesta el matching completo."""
    print(f"\n{'='*60}")
    print("  MATCHING PUBLICACIÓN-PROFESOR POR ORCID (Paso 4)")
    print(f"  Corpus: {anio_inicio}–{anio_fin}")
    print(f"{'='*60}\n")

    # 1. Cargar profesores
    print("Cargando profesores...")
    df_profesores, df_auth_ids = cargar_profesores()
    print(
        f"  {len(df_profesores)} profesores únicos, "
        f"{df_auth_ids['auth_id'].nunique()} Auth_IDs registrados"
    )

    # 2. Cargar publicaciones
    print(f"\nCargando publicaciones ({anio_inicio}–{anio_fin})...")
    df_publicaciones = cargar_publicaciones(anio_inicio, anio_fin)
    print(f"  {len(df_publicaciones)} filas cargadas")

    # 3. Diagnóstico previo
    diagnosticar_problemas(
        df_profesores, df_auth_ids, df_publicaciones, orcid_especifico
    )

    # 4. Matching
    print("Ejecutando matching...")
    df_vinculos, df_sin_match = hacer_matching_por_orcid(
        df_profesores, df_auth_ids, df_publicaciones
    )

    # 5. Archivos de salida
    print(f"\nGenerando archivos en {_OUT_DIR}/")
    generar_salidas(
        df_vinculos, df_sin_match, df_profesores, df_auth_ids, df_publicaciones
    )

    # 6. Resumen final
    imprimir_resumen(
        df_vinculos, df_sin_match, df_profesores, df_auth_ids, df_publicaciones
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Matching publicación-profesor por ORCID vía Scopus Author ID."
    )
    parser.add_argument(
        "--anio-inicio",
        type=int,
        default=2014,
        metavar="AÑO",
        help="Primer año de publicaciones a procesar (default: 2014)",
    )
    parser.add_argument(
        "--anio-fin",
        type=int,
        default=_ANIO_ACTUAL,
        metavar="AÑO",
        help=f"Último año a procesar (default: {_ANIO_ACTUAL})",
    )
    parser.add_argument(
        "--diagnostico-orcid",
        metavar="ORCID",
        help="ORCID de un profesor específico para diagnóstico detallado",
    )
    args = parser.parse_args()

    main(
        anio_inicio=args.anio_inicio,
        anio_fin=args.anio_fin,
        orcid_especifico=args.diagnostico_orcid,
    )
