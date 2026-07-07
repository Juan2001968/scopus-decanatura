"""
07_reparar_matching.py — Repara publicacion_profesor con base en evidencia de Author ID.

Contexto (auditoría 2026-07-06)
-------------------------------
La tabla ``publicacion_profesor`` mezclaba dos generaciones de matching:

- ``id_scopus`` (819 vínculos): puente Author(s) ID de Scopus → Auth_ID del
  roster → ORCID → profesor.  Verificado 100% respaldado por los CSV crudos.
- ``fuzzy``/``exacto`` (485 vínculos): matching por NOMBRE de un ETL anterior.
  La auditoría contra ``data/raw/scopus_*.csv`` mostró que NINGUNO de esos
  485 tiene respaldo de Author ID y que en su mayoría son homónimos
  (p. ej., el mega-ensayo COVID de la OMS atribuido por el apellido
  "Martínez"; papers de "Alvarez E." asignados a Álvarez-Silva).

Además, el profesor "de la Cruz, Javier" (MAT_EST) nunca se insertó en
``biblio.profesor`` porque su ORCID venía malformado en el roster
(``0000-0003-36099148``, sin el guion: debe ser ``0000-0003-3609-9148``),
dejando ~23 publicaciones suyas sin vincular.

Qué hace (transaccional, idempotente)
-------------------------------------
1. Inserta al profesor "de la Cruz, Javier" y sus 2 perfiles Scopus si faltan.
2. Recomputa los vínculos esperados por Author ID desde data/raw/scopus_*.csv
   contra biblio.autor_scopus.
3. Exporta a data/processed/ los vínculos por nombre SIN respaldo (auditoría)
   y los ELIMINA de la BD.
4. Inserta los vínculos respaldados que falten (metodo 'id_scopus').
5. Recalcula el h-index almacenado de los profesores (consistencia de BD;
   el dashboard ya lo calcula al vuelo).
6. Exporta candidatos a "segundo perfil Scopus" por profesor para revisión
   manual (data/processed/candidatos_segundo_perfil.csv): si la decanatura
   confirma un ID, se agrega a biblio.autor_scopus y se re-ejecuta este
   script para recuperar esas publicaciones con evidencia.

Uso
---
    python -m scripts.07_reparar_matching            # aplica cambios
    python -m scripts.07_reparar_matching --dry-run  # solo reporta
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from sqlalchemy import text

from config.db_config import get_engine

RAW = PROJECT_ROOT / "data" / "raw"
OUT = PROJECT_ROOT / "data" / "processed"

# Profesor omitido por ORCID malformado en Prof_MatyEst.csv
PROF_FALTANTE = {
    "nombre_normalizado": "de la Cruz, Javier",
    "orcid": "0000-0003-3609-9148",
    "codigo_departamento": "MAT_EST",
    "perfiles": [
        {"scopus_author_id": "53163468700", "numero_documentos_scopus": 18},
        {"scopus_author_id": "58085767000", "numero_documentos_scopus": 2},
    ],
    "subject_area": "Mathematics",
}

PAIR_RE = re.compile(r"([^;()]+?)\s*\((\d{7,12})\)")


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t))
                   if unicodedata.category(c) != "Mn").lower()


# ---------------------------------------------------------------------------
# Corpus crudo: EID -> author ids / (nombre, id)
# ---------------------------------------------------------------------------

def cargar_corpus() -> tuple[dict, dict]:
    eid_ids: dict[str, set] = {}
    eid_pairs: dict[str, list] = {}
    for year in range(2014, 2026):
        f = RAW / f"scopus_{year}.csv"
        if not f.exists():
            print(f"  [AVISO] falta {f.name}")
            continue
        df = pd.read_csv(f, encoding="utf-8-sig", dtype=str)
        for _, row in df.iterrows():
            eid = str(row.get("EID", "")).strip()
            if not eid or eid in ("nan", "None"):
                continue
            pairs = [(n.strip(), i) for n, i in
                     PAIR_RE.findall(str(row.get("Author full names") or ""))]
            ids = {i.strip() for i in str(row.get("Author(s) ID") or "").split(";")
                   if i.strip() and i.strip() != "nan"}
            ids |= {i for _, i in pairs}
            eid_ids.setdefault(eid, set()).update(ids)
            eid_pairs.setdefault(eid, []).extend(pairs)
    return eid_ids, eid_pairs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(dry_run: bool = False) -> None:
    stamp = datetime.now().strftime("%Y%m%d")
    engine = get_engine()

    print("Cargando corpus crudo (data/raw/scopus_*.csv)...")
    eid_ids, eid_pairs = cargar_corpus()
    print(f"  {len(eid_ids)} EIDs con author IDs")

    with engine.begin() as conn:
        # ------------------------------------------------------------------
        # 1. Profesor faltante
        # ------------------------------------------------------------------
        row = conn.execute(text(
            "SELECT id_profesor FROM biblio.profesor WHERE orcid = :orcid"
        ), {"orcid": PROF_FALTANTE["orcid"]}).fetchone()

        if row:
            id_cruz = row[0]
            print(f"1. Profesor '{PROF_FALTANTE['nombre_normalizado']}' ya existe (id={id_cruz}).")
        elif dry_run:
            id_cruz = None
            print(f"1. [dry-run] Se insertaría el profesor '{PROF_FALTANTE['nombre_normalizado']}'.")
        else:
            id_depto = conn.execute(text(
                "SELECT id_departamento FROM biblio.departamento WHERE codigo = :c"
            ), {"c": PROF_FALTANTE["codigo_departamento"]}).scalar()
            id_cruz = conn.execute(text(
                "INSERT INTO biblio.profesor (nombre_normalizado, orcid, activo, id_departamento) "
                "VALUES (:n, :o, TRUE, :d) RETURNING id_profesor"
            ), {"n": PROF_FALTANTE["nombre_normalizado"],
                "o": PROF_FALTANTE["orcid"], "d": id_depto}).scalar()
            print(f"1. Insertado profesor '{PROF_FALTANTE['nombre_normalizado']}' (id={id_cruz}).")

        if id_cruz is not None and not dry_run:
            for perfil in PROF_FALTANTE["perfiles"]:
                existe = conn.execute(text(
                    "SELECT 1 FROM biblio.autor_scopus WHERE scopus_author_id = :a"
                ), {"a": perfil["scopus_author_id"]}).fetchone()
                if not existe:
                    conn.execute(text(
                        "INSERT INTO biblio.autor_scopus "
                        "(scopus_author_id, nombre_scopus, id_profesor, subject_area, numero_documentos_scopus) "
                        "VALUES (:a, :n, :p, :s, :nd)"
                    ), {"a": perfil["scopus_author_id"],
                        "n": PROF_FALTANTE["nombre_normalizado"],
                        "p": id_cruz, "s": PROF_FALTANTE["subject_area"],
                        "nd": perfil["numero_documentos_scopus"]})
                    print(f"   + autor_scopus {perfil['scopus_author_id']}")

        # ------------------------------------------------------------------
        # 2. Estado actual y vínculos esperados por Author ID
        # ------------------------------------------------------------------
        links = pd.read_sql(text(
            "SELECT id_publicacion, id_profesor, metodo_vinculacion "
            "FROM biblio.publicacion_profesor"), conn)
        profs = pd.read_sql(text(
            "SELECT id_profesor, nombre_normalizado FROM biblio.profesor"), conn)
        autsc = pd.read_sql(text(
            "SELECT id_profesor, scopus_author_id, numero_documentos_scopus "
            "FROM biblio.autor_scopus"), conn)
        pubs = pd.read_sql(text(
            "SELECT id_publicacion, eid, anio_publicacion, titulo "
            "FROM biblio.publicacion"), conn)

        nombre_prof = dict(zip(profs["id_profesor"], profs["nombre_normalizado"]))
        id_por_eid = dict(zip(pubs["eid"], pubs["id_publicacion"]))
        eid_por_id = dict(zip(pubs["id_publicacion"], pubs["eid"]))
        autsc["scopus_author_id"] = autsc["scopus_author_id"].astype(str).str.strip()
        auth2prof = dict(zip(autsc["scopus_author_id"], autsc["id_profesor"]))
        ids_de_prof: dict = defaultdict(set)
        for aid, p in auth2prof.items():
            ids_de_prof[p].add(aid)

        esperados: set = set()
        for eid, ids in eid_ids.items():
            pid_pub = id_por_eid.get(eid)
            if pid_pub is None:
                continue
            for aid in ids:
                p = auth2prof.get(aid)
                if p is not None:
                    esperados.add((int(pid_pub), int(p)))

        actuales = set(zip(links["id_publicacion"].astype(int),
                           links["id_profesor"].astype(int)))
        sin_respaldo = {(pub, p) for (pub, p) in actuales
                        if not (eid_ids.get(eid_por_id.get(pub), set()) & ids_de_prof[p])}
        faltantes = esperados - actuales

        print(f"2. Vínculos actuales={len(actuales)}, esperados por Author ID={len(esperados)}, "
              f"sin respaldo={len(sin_respaldo)}, faltantes={len(faltantes)}")

        antes = links.groupby("id_profesor")["id_publicacion"].nunique().to_dict()

        # ------------------------------------------------------------------
        # 3. Exportar y eliminar vínculos sin respaldo
        # ------------------------------------------------------------------
        metodo = {(int(r["id_publicacion"]), int(r["id_profesor"])): r["metodo_vinculacion"]
                  for _, r in links.iterrows()}
        titulo_por_id = dict(zip(pubs["id_publicacion"], pubs["titulo"]))
        anio_por_id = dict(zip(pubs["id_publicacion"], pubs["anio_publicacion"]))

        OUT.mkdir(parents=True, exist_ok=True)
        df_del = pd.DataFrame([{
            "id_publicacion": pub, "id_profesor": p,
            "profesor": nombre_prof.get(p), "eid": eid_por_id.get(pub),
            "anio": anio_por_id.get(pub), "titulo": titulo_por_id.get(pub),
            "metodo_vinculacion": metodo.get((pub, p)),
        } for (pub, p) in sorted(sin_respaldo)])
        out_del = OUT / f"links_eliminados_{stamp}.csv"
        df_del.to_csv(out_del, index=False, encoding="utf-8-sig")
        print(f"3. Exportado {out_del.name} ({len(df_del)} vínculos)")

        if not dry_run and sin_respaldo:
            for (pub, p) in sin_respaldo:
                conn.execute(text(
                    "DELETE FROM biblio.publicacion_profesor "
                    "WHERE id_publicacion = :pub AND id_profesor = :p"
                ), {"pub": pub, "p": p})
            print(f"   Eliminados {len(sin_respaldo)} vínculos sin respaldo.")

        # ------------------------------------------------------------------
        # 4. Insertar vínculos respaldados que falten
        # ------------------------------------------------------------------
        if not dry_run and faltantes:
            for (pub, p) in sorted(faltantes):
                conn.execute(text(
                    "INSERT INTO biblio.publicacion_profesor "
                    "(id_publicacion, id_profesor, metodo_vinculacion) "
                    "VALUES (:pub, :p, 'id_scopus') ON CONFLICT DO NOTHING"
                ), {"pub": pub, "p": p})
            print(f"4. Insertados {len(faltantes)} vínculos respaldados por Author ID.")
        elif faltantes:
            print(f"4. [dry-run] Se insertarían {len(faltantes)} vínculos.")

        # ------------------------------------------------------------------
        # 5. Recalcular h-index almacenado
        # ------------------------------------------------------------------
        if not dry_run:
            filas = conn.execute(text(
                "SELECT pp.id_profesor, p.cited_by_count "
                "FROM biblio.publicacion_profesor pp "
                "JOIN biblio.publicacion p ON p.id_publicacion = pp.id_publicacion"
            )).all()
            citas_prof: dict = defaultdict(list)
            for pid, c in filas:
                citas_prof[pid].append(int(c or 0))
            for pid, citas in citas_prof.items():
                citas.sort(reverse=True)
                h = 0
                for i, c in enumerate(citas, start=1):
                    if c >= i:
                        h = i
                    else:
                        break
                conn.execute(text(
                    "UPDATE biblio.profesor SET h_index = :h, h_index_fecha = NOW() "
                    "WHERE id_profesor = :p"), {"h": h, "p": pid})
            print(f"5. h-index almacenado recalculado para {len(citas_prof)} profesores.")

        # ------------------------------------------------------------------
        # 6. Candidatos a segundo perfil (para revisión de la decanatura)
        # ------------------------------------------------------------------
        cand_rows = []
        for (pub, p) in sorted(sin_respaldo):
            eid = eid_por_id.get(pub)
            nombre = nombre_prof.get(p, "")
            ap = _sin_acentos(nombre.split(",")[0])
            toks = [t for t in re.split(r"[\s\-]+", ap) if len(t) > 2]
            ini = ""
            partes = nombre.split(",")
            if len(partes) > 1 and partes[1].strip():
                ini = _sin_acentos(partes[1].strip())[:1]
            for autor, aid in eid_pairs.get(eid, []):
                an = _sin_acentos(autor)
                ap_a = an.split(",")[0]
                no_a = an.split(",")[1].strip() if "," in an else ""
                if any(t in ap_a for t in toks) and (not ini or no_a.startswith(ini)):
                    cand_rows.append({"id_profesor": p, "profesor": nombre,
                                      "author_id_candidato": aid,
                                      "nombre_autor_en_pub": autor, "eid": eid})
        if cand_rows:
            dfc = pd.DataFrame(cand_rows)
            resumen = (dfc.groupby(["id_profesor", "profesor", "author_id_candidato"])
                       .agg(apariciones=("eid", "nunique"),
                            ejemplo_nombre=("nombre_autor_en_pub", "first"))
                       .reset_index()
                       .sort_values(["profesor", "apariciones"], ascending=[True, False]))
            out_cand = OUT / "candidatos_segundo_perfil.csv"
            resumen.to_csv(out_cand, index=False, encoding="utf-8-sig")
            print(f"6. Exportado {out_cand.name} ({len(resumen)} candidatos ID×profesor). "
                  "Confirmar con la decanatura y agregarlos a biblio.autor_scopus.")

        # ------------------------------------------------------------------
        # 7. Reporte antes/después por profesor
        # ------------------------------------------------------------------
        links2 = pd.read_sql(text(
            "SELECT id_publicacion, id_profesor FROM biblio.publicacion_profesor"), conn)
        despues = links2.groupby("id_profesor")["id_publicacion"].nunique().to_dict()
        decl = autsc.groupby("id_profesor")["numero_documentos_scopus"].sum().to_dict()

        print("\n%-36s %6s %8s %10s" % ("PROFESOR", "antes", "después", "decl.Scopus"))
        todos = sorted(set(antes) | set(despues),
                       key=lambda p: antes.get(p, 0) - despues.get(p, 0), reverse=True)
        for p in todos:
            a, d = antes.get(p, 0), despues.get(p, 0)
            if a != d:
                print(f"{str(nombre_prof.get(p, p))[:36]:36s} {a:6d} {d:8d} {int(decl.get(p, 0)):10d}")

        total_a, total_d = sum(antes.values()), sum(despues.values())
        print(f"\nTOTAL vínculos: {total_a} → {total_d}")
        if dry_run:
            print("\n[dry-run] No se aplicó ningún cambio (la transacción se revierte).")
            raise SystemExit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo reporta; no modifica la base de datos.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
