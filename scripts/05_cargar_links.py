"""
05_cargar_links.py — Carga quirúrgica de vínculos publicación-profesor.

Lee data/processed/publicaciones_matched_v3.csv (generado por 04_matching_por_orcid.py)
y lo inserta en biblio.publicacion_profesor sin re-ejecutar el ETL completo.

Pasos:
  1. Lee publicaciones_matched_v3.csv
  2. Adapta columnas al formato esperado por load_publication_professor_links
  3. Construye pub_map  (eid → id_publicacion) desde biblio.publicacion
  4. Construye prof_map (orcid → id_profesor)  desde biblio.profesor
  5. Inserta vínculos (upsert — ignora duplicados)
  6. Recalcula h-index de todos los profesores
  7. Imprime resumen antes/después
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── encoding seguro en Windows ───────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Añadir raíz del proyecto al path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from sqlalchemy import text

from config.db_config import get_session
from src.database.models import Publicacion, Profesor, publicacion_profesor_table
from src.etl.load import load_publication_professor_links, update_h_index_profesores

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

LINKS_CSV = PROJECT_ROOT / "data" / "processed" / "publicaciones_matched_v3.csv"

# Mapa de valores en columna 'confianza' → metodo_vinculacion en BD
_CONFIANZA_A_METODO = {
    "ORCID_VIA_AUTH_ID": "id_scopus",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contar_links(session) -> int:
    """Cuenta filas actuales en biblio.publicacion_profesor."""
    result = session.execute(
        text("SELECT COUNT(*) FROM biblio.publicacion_profesor")
    )
    return result.scalar()


def _build_pub_map(session) -> dict[str, int]:
    """Construye eid → id_publicacion desde biblio.publicacion."""
    rows = session.query(Publicacion.eid, Publicacion.id_publicacion).all()
    return {eid: id_pub for eid, id_pub in rows if eid}


def _build_prof_map(session) -> dict[str, int]:
    """Construye orcid → id_profesor desde biblio.profesor."""
    rows = session.query(Profesor.orcid, Profesor.id_profesor).all()
    return {orcid: id_prof for orcid, id_prof in rows if orcid}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # 1. Leer CSV
    if not LINKS_CSV.exists():
        print(f"[ERROR] No se encontró el archivo: {LINKS_CSV}")
        print("        Ejecuta primero scripts/04_matching_por_orcid.py")
        sys.exit(1)

    df = pd.read_csv(LINKS_CSV, dtype=str)
    print(f"[OK] CSV leído: {len(df)} vínculos en {LINKS_CSV.name}")
    print(f"     Columnas: {list(df.columns)}")

    # 2. Adaptar columnas al formato que espera load_publication_professor_links
    #    Necesita: eid, orcid, metodo_vinculacion
    df = df.rename(columns={"orcid_matched": "orcid"})

    if "confianza" in df.columns:
        df["metodo_vinculacion"] = (
            df["confianza"]
            .map(_CONFIANZA_A_METODO)
            .fillna("id_scopus")  # fallback por si hay valores nuevos
        )
    else:
        df["metodo_vinculacion"] = "id_scopus"

    # Verificar columnas requeridas
    required = {"eid", "orcid", "metodo_vinculacion"}
    missing = required - set(df.columns)
    if missing:
        print(f"[ERROR] Columnas faltantes en el CSV: {missing}")
        sys.exit(1)

    # Eliminar filas sin eid u orcid
    antes = len(df)
    df = df.dropna(subset=["eid", "orcid"])
    df = df[df["eid"].str.strip().ne("") & df["orcid"].str.strip().ne("")]
    if len(df) < antes:
        print(f"[WARN] {antes - len(df)} filas descartadas por eid/orcid vacío")

    print(f"[OK] Vínculos a cargar: {len(df)}")

    with get_session() as session:
        # 3. Conteo previo
        links_antes = _contar_links(session)
        print(f"\n--- Estado previo ---")
        print(f"  publicacion_profesor: {links_antes} filas")

        # 4. Construir mapas desde la BD
        pub_map = _build_pub_map(session)
        prof_map = _build_prof_map(session)
        print(f"  pub_map:  {len(pub_map)} publicaciones conocidas en BD")
        print(f"  prof_map: {len(prof_map)} profesores conocidos en BD")

        # Diagnóstico rápido de cobertura
        eids_csv = set(df["eid"].str.strip())
        orcids_csv = set(df["orcid"].str.strip())
        eids_no_bd = eids_csv - set(pub_map.keys())
        orcids_no_bd = orcids_csv - set(prof_map.keys())
        if eids_no_bd:
            print(f"  [WARN] {len(eids_no_bd)} EIDs del CSV no existen en biblio.publicacion")
        if orcids_no_bd:
            print(f"  [WARN] {len(orcids_no_bd)} ORCIDs del CSV no existen en biblio.profesor:")
            for o in sorted(orcids_no_bd):
                print(f"         {o}")

        # 5. Insertar vínculos
        print(f"\n--- Cargando vínculos ---")
        load_publication_professor_links(session, df, pub_map, prof_map)

        # 6. Recalcular h-index
        print(f"\n--- Recalculando h-index ---")
        n_hindex = update_h_index_profesores(session)
        print(f"  h-index actualizado para {n_hindex} profesores")

        # 7. Conteo posterior
        links_despues = _contar_links(session)

    # 8. Resumen
    print(f"\n=== RESUMEN ===")
    print(f"  Vínculos antes:  {links_antes}")
    print(f"  Vínculos después: {links_despues}")
    print(f"  Insertados:      {links_despues - links_antes}")
    print(f"  h-index actualizados: {n_hindex}")
    if links_despues > 0:
        print(f"\n[OK] Dashboard debería mostrar KPIs correctos ahora.")
    else:
        print(f"\n[WARN] No se insertaron filas. Revisa los warnings arriba.")


if __name__ == "__main__":
    main()
