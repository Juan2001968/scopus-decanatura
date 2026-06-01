"""
Carga datos de demostración en el dashboard bibliométrico.

Inserta 19 profesores ficticios con publicaciones de ejemplo (2014-2025)
para visualizar el diseño del dashboard sin datos reales de Scopus.

Uso:
    python -m scripts.cargar_datos_demo            # Carga (solo si tablas vacías)
    python -m scripts.cargar_datos_demo --limpiar  # Borra todo y recarga
    python -m scripts.cargar_datos_demo --eliminar # Solo borra datos demo

Cómo iniciar PostgreSQL en Windows antes de correr este script:
    pg_ctl start -D "C:/Program Files/PostgreSQL/16/data"
    o desde Servicios de Windows → PostgreSQL
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, date
from pathlib import Path

# Asegurar que el directorio raíz esté en el path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from config.db_config import get_engine
from src.database.init_db import create_schema_and_tables
from src.utils.logger import get_logger

logger = get_logger(__name__)

random.seed(42)  # reproducible

# ---------------------------------------------------------------------------
# DATOS DEMO
# ---------------------------------------------------------------------------

AÑOS = list(range(2014, 2026))  # 2014-2025

DEPARTAMENTOS = [
    # (codigo, nombre, division)
    ("MATEST", "Matemáticas, Estadística y Ciencia de Datos", "Bloque 1"),
    ("FISICA", "Física y Geociencias",                        "Bloque 2"),
    ("BIOQUI", "Biología y Química",                          "Bloque 2"),
]

# (nombre, orcid, codigo_depto, h_index, pubs_por_año[2014-2025], citas_total, pct_q1q2)
PROFESORES = [
    # ── Bloque 1: Matemáticas, Estadística y Ciencia de Datos ──────────────
    ("Carmen López",    "0000-0001-1001-0001", "MATEST", 14, [0,3,4,6,7,6,5,7,6,5,3,0], 385, 78),
    ("Andrés Restrepo", "0000-0001-1002-0002", "MATEST", 12, [2,3,4,5,6,5,4,5,5,4,3,0], 298, 72),
    ("María Fernández", "0000-0001-1003-0003", "MATEST", 13, [0,0,3,4,5,6,5,6,7,5,4,0], 312, 75),
    ("Jorge Peña",      "0000-0001-1004-0004", "MATEST",  9, [0,0,0,2,3,4,3,4,5,4,3,0], 165, 65),
    ("Laura Martínez",  "0000-0001-1005-0005", "MATEST", 18, [4,5,6,7,8,9,7,8,9,7,6,2], 612, 82),
    ("Carlos Vásquez",  "0000-0001-1006-0006", "MATEST", 11, [0,3,4,5,6,5,4,5,5,4,3,0], 245, 68),
    ("Ana Quintero",    "0000-0001-1007-0007", "MATEST",  8, [0,0,0,0,3,4,3,4,5,4,3,0], 142, 60),
    ("Santiago Gómez",  "0000-0001-1008-0008", "MATEST", 15, [0,0,3,4,5,6,5,7,8,7,6,2], 445, 85),
    ("Daniela Torres",  "0000-0001-1009-0009", "MATEST", 10, [0,0,0,2,3,4,3,5,6,5,4,0], 215, 79),
    ("Felipe Ramírez",  "0000-0001-1010-0010", "MATEST",  8, [0,0,0,0,0,2,3,4,5,5,4,2], 142, 73),
    # ── Bloque 2a: Física y Geociencias ─────────────────────────────────────
    ("Roberto Mendoza", "0000-0002-2001-0001", "FISICA", 21, [5,6,7,8,9,8,6,7,8,7,6,2], 756, 65),
    ("Isabel Castillo", "0000-0002-2002-0002", "FISICA", 15, [3,4,5,6,6,5,4,5,6,5,4,0], 389, 68),
    ("Pablo Herrera",   "0000-0002-2003-0003", "FISICA", 12, [0,2,3,4,5,5,4,5,5,4,3,0], 285, 62),
    # ── Bloque 2b: Biología y Química ────────────────────────────────────────
    ("Valentina Ríos",  "0000-0003-3001-0001", "BIOQUI", 16, [2,3,4,5,6,6,5,6,7,6,5,2], 412, 60),
    ("Eduardo Sánchez", "0000-0003-3002-0002", "BIOQUI", 13, [4,5,5,6,6,5,4,5,5,4,4,0], 342, 58),
    ("Natalia Agudelo", "0000-0003-3003-0003", "BIOQUI", 11, [0,2,3,4,4,5,4,5,5,4,3,0], 256, 55),
    ("Cristina Morales","0000-0003-3004-0004", "BIOQUI", 17, [3,4,5,6,7,6,5,6,7,6,5,2], 489, 62),
    ("Alejandro Díaz",  "0000-0003-3005-0005", "BIOQUI", 13, [2,3,4,5,5,5,4,5,5,4,3,0], 312, 58),
    ("Paola Suárez",    "0000-0003-3006-0006", "BIOQUI", 10, [0,0,2,3,4,5,4,5,5,4,3,0], 198, 55),
]

# Revistas con diferentes cuartiles
FUENTES = [
    # (title, issn, tipo, cuartil, sjr, citescore, snip)
    ("Nature",                            "0028-0836", "Journal", "Q1", 15.00, 18.5, 6.5),
    ("Science",                           "0036-8075", "Journal", "Q1", 14.50, 17.2, 6.2),
    ("PLOS ONE",                          "1932-6203", "Journal", "Q1",  1.32,  3.8, 1.2),
    ("Physical Review Letters",           "0031-9007", "Journal", "Q1",  4.80,  7.1, 2.8),
    ("Bioresource Technology",            "0960-8524", "Journal", "Q1",  2.90,  9.5, 2.1),
    ("Journal of Chemical Physics",       "0021-9606", "Journal", "Q2",  1.05,  3.2, 1.0),
    ("Mathematical Methods in Sciences",  "1991-8763", "Journal", "Q2",  0.65,  2.1, 0.8),
    ("Applied Mathematics and Computation","0096-3003", "Journal", "Q2",  0.87,  3.6, 1.1),
    ("Revista Colombiana de Matemáticas", "0034-7426", "Journal", "Q3",  0.25,  0.9, 0.4),
    ("Acta Biológica Colombiana",         "0120-548X", "Journal", "Q3",  0.18,  0.7, 0.3),
    ("International Journal of Mathematics","0129-167X","Journal", "Q4",  0.12,  0.5, 0.2),
    ("Ingeniería y Ciencia",              "1794-9165", "Journal", "Q4",  0.10,  0.4, 0.2),
]

TIPOS_DOCUMENTAL = ["Article"] * 7 + ["Review"] * 2 + ["Conference Paper"]

KEYWORDS_POOL = [
    "machine learning", "deep learning", "neural networks", "optimization",
    "statistical analysis", "Bayesian methods", "data science",
    "quantum mechanics", "fluid dynamics", "thermodynamics", "spectroscopy",
    "biodiversity", "ecology", "molecular biology", "genomics",
    "organic chemistry", "catalysis", "polymer science", "nanotechnology",
    "differential equations", "topology", "number theory", "graph theory",
    "time series", "regression analysis", "probability theory",
    "Colombia", "Scopus", "bibliometrics", "citation analysis",
]


# ---------------------------------------------------------------------------
# GENERADORES DE DATOS
# ---------------------------------------------------------------------------

def _citas_por_pub(n_pubs: int, h_index: int, total_citas: int, años: list[int]) -> list[int]:
    """Genera n_pubs valores de citas compatibles con h_index y total aproximado."""
    citas = []
    # Publicaciones más antiguas acumulan más citas (peso por antigüedad)
    pesos = [max(1, 2026 - a) for a in años]
    total_pesos = sum(pesos)

    for i, w in enumerate(pesos):
        base = int(total_citas * w / total_pesos * random.uniform(0.6, 1.6))
        citas.append(max(0, base))

    # Ajustar h-index: las top h publicaciones deben tener >= h citas
    citas.sort(reverse=True)
    for i in range(min(h_index, len(citas))):
        if citas[i] < h_index:
            citas[i] = h_index + random.randint(0, 3)

    # Re-mezclar para no tener siempre las más citadas al principio
    random.shuffle(citas)
    return citas


def _asignar_fuente(fuentes_ids: dict, pct_q1q2: int) -> tuple[int, str]:
    """Devuelve (id_fuente, cuartil) según el porcentaje Q1+Q2 del profesor."""
    rand = random.randint(0, 99)
    if rand < pct_q1q2:
        # Q1 o Q2
        candidatas = [(fid, q) for fid, q in fuentes_ids.items() if q in ("Q1", "Q2")]
    elif rand < pct_q1q2 + 20:
        candidatas = [(fid, q) for fid, q in fuentes_ids.items() if q == "Q3"]
    else:
        candidatas = [(fid, q) for fid, q in fuentes_ids.items() if q == "Q4"]
    if not candidatas:
        candidatas = list(fuentes_ids.items())
    return random.choice(candidatas)


# ---------------------------------------------------------------------------
# OPERACIONES DE BASE DE DATOS
# ---------------------------------------------------------------------------

def _truncar_tablas(conn) -> None:
    """Elimina todos los datos demo (en orden para respetar FKs)."""
    tablas = [
        "biblio.publicacion_profesor",
        "biblio.publicacion",
        "biblio.fuente_metrica",
        "biblio.fuente",
        "biblio.autor_scopus",
        "biblio.profesor",
        "biblio.departamento",
        "biblio.log_ingesta",
    ]
    conn.execute(text("SET session_replication_role = replica"))  # desactiva FK checks
    for tbl in tablas:
        conn.execute(text(f"TRUNCATE TABLE {tbl} RESTART IDENTITY CASCADE"))
    conn.execute(text("SET session_replication_role = DEFAULT"))
    conn.commit()
    logger.info("Tablas vaciadas")


def _tablas_vacias(conn) -> bool:
    r = conn.execute(text("SELECT COUNT(*) FROM biblio.profesor")).fetchone()
    return r[0] == 0


def cargar_demo(limpiar: bool = False) -> None:
    engine = get_engine()

    # 1. Crear esquema y tablas si no existen
    print("→ Verificando esquema y tablas...")
    create_schema_and_tables()

    with engine.connect() as conn:
        if not limpiar and not _tablas_vacias(conn):
            n = conn.execute(text("SELECT COUNT(*) FROM biblio.profesor")).fetchone()[0]
            print(f"⚠  Ya existen {n} profesores. Usa --limpiar para recargar.")
            return

        if limpiar:
            print("→ Limpiando datos existentes...")
            _truncar_tablas(conn)

        # 2. Departamentos
        print("→ Insertando departamentos...")
        depto_id_map: dict[str, int] = {}
        for codigo, nombre, division in DEPARTAMENTOS:
            r = conn.execute(
                text("""
                    INSERT INTO biblio.departamento (nombre, codigo, division)
                    VALUES (:nombre, :codigo, :division)
                    ON CONFLICT (codigo) DO UPDATE SET nombre=EXCLUDED.nombre
                    RETURNING id_departamento
                """),
                {"nombre": nombre, "codigo": codigo, "division": division},
            )
            depto_id_map[codigo] = r.fetchone()[0]
        conn.commit()
        print(f"   {len(DEPARTAMENTOS)} departamentos OK")

        # 3. Fuentes (revistas)
        print("→ Insertando fuentes bibliográficas...")
        fuente_id_map: dict[int, str] = {}  # id_fuente → cuartil
        for title, issn, tipo, cuartil, sjr, citescore, snip in FUENTES:
            r = conn.execute(
                text("""
                    INSERT INTO biblio.fuente
                        (source_title, issn, tipo_fuente, publisher)
                    VALUES (:titulo, :issn, :tipo, 'Demo Publisher')
                    ON CONFLICT (source_title, issn) DO UPDATE SET tipo_fuente=EXCLUDED.tipo_fuente
                    RETURNING id_fuente
                """),
                {"titulo": title, "issn": issn, "tipo": tipo},
            )
            fid = r.fetchone()[0]
            fuente_id_map[fid] = cuartil

            # Métricas para todos los años
            for anio in AÑOS:
                conn.execute(
                    text("""
                        INSERT INTO biblio.fuente_metrica
                            (id_fuente, anio, sjr, citescore, snip, cuartil_sjr, fuente_datos)
                        VALUES (:fid, :anio, :sjr, :cs, :snip, :cuartil, 'DEMO')
                        ON CONFLICT (id_fuente, anio) DO NOTHING
                    """),
                    {"fid": fid, "anio": anio, "sjr": sjr + random.uniform(-0.1, 0.1),
                     "cs": citescore, "snip": snip, "cuartil": cuartil},
                )
        conn.commit()
        print(f"   {len(FUENTES)} fuentes + métricas anuales OK")

        # 4. Profesores y publicaciones
        print("→ Insertando profesores y publicaciones...")
        total_pubs = 0
        total_links = 0
        pub_global_idx = 0

        for prof_data in PROFESORES:
            nombre, orcid, cod_depto, h_idx, pubs_año, citas_total, pct_q1q2 = prof_data
            id_depto = depto_id_map[cod_depto]

            # Insertar profesor
            r = conn.execute(
                text("""
                    INSERT INTO biblio.profesor
                        (nombre_normalizado, orcid, id_departamento, activo,
                         h_index, h_index_fecha)
                    VALUES (:nombre, :orcid, :depto, true, :h, :fecha)
                    ON CONFLICT (orcid) DO UPDATE
                        SET nombre_normalizado = EXCLUDED.nombre_normalizado,
                            h_index = EXCLUDED.h_index
                    RETURNING id_profesor
                """),
                {
                    "nombre": nombre, "orcid": orcid, "depto": id_depto,
                    "h": h_idx, "fecha": date(2025, 12, 31),
                },
            )
            id_prof = r.fetchone()[0]

            # Generar publicaciones por año
            años_pubs: list[int] = []
            for i, n_año in enumerate(pubs_año):
                años_pubs.extend([AÑOS[i]] * n_año)

            if not años_pubs:
                continue

            citas_lista = _citas_por_pub(len(años_pubs), h_idx, citas_total, años_pubs)

            for j, (año, citas) in enumerate(zip(años_pubs, citas_lista)):
                pub_global_idx += 1
                eid = f"2-s2.0-DEMO{pub_global_idx:06d}"
                tipo = random.choice(TIPOS_DOCUMENTAL)
                id_fuente, cuartil_sjr = _asignar_fuente(fuente_id_map, pct_q1q2)
                keywords = "; ".join(random.sample(KEYWORDS_POOL, k=random.randint(3, 7)))
                titulo = f"Investigación en {nombre.split()[0]}: estudio {pub_global_idx}"
                oa = random.choice(["Gold", "Green", "Closed", "Closed", "Closed"])

                conn.execute(
                    text("""
                        INSERT INTO biblio.publicacion
                            (eid, titulo, anio_publicacion, tipo_documental, idioma,
                             cited_by_count, open_access, indexed_keywords, id_fuente,
                             publisher)
                        VALUES
                            (:eid, :titulo, :anio, :tipo, 'English',
                             :citas, :oa, :kw, :fid, 'Demo Publisher')
                        ON CONFLICT (eid) DO NOTHING
                        RETURNING id_publicacion
                    """),
                    {
                        "eid": eid, "titulo": titulo, "anio": año, "tipo": tipo,
                        "citas": citas, "oa": oa, "kw": keywords, "fid": id_fuente,
                    },
                )
                r2 = conn.execute(
                    text("SELECT id_publicacion FROM biblio.publicacion WHERE eid=:eid"),
                    {"eid": eid},
                )
                id_pub = r2.fetchone()[0]

                conn.execute(
                    text("""
                        INSERT INTO biblio.publicacion_profesor
                            (id_publicacion, id_profesor, metodo_vinculacion,
                             posicion_autoria, es_autor_correspondencia)
                        VALUES (:pub, :prof, 'DEMO', 1, false)
                        ON CONFLICT DO NOTHING
                    """),
                    {"pub": id_pub, "prof": id_prof},
                )
                total_links += 1

            total_pubs += len(años_pubs)
            conn.commit()
            print(f"   ✓ {nombre:22s} → {len(años_pubs):3d} pubs, h={h_idx}, citas≈{citas_total}")

        print(f"\n{'─'*55}")
        print(f"   Departamentos : {len(DEPARTAMENTOS)}")
        print(f"   Profesores    : {len(PROFESORES)}")
        print(f"   Publicaciones : {total_pubs}")
        print(f"   Fuentes       : {len(FUENTES)}")
        print(f"   Links pub-prof: {total_links}")
        print(f"{'─'*55}")
        print("✅ Datos demo cargados correctamente.")
        print("\nInicia el dashboard con:")
        print("   python -m scripts.run_dashboard")


def eliminar_demo() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        _truncar_tablas(conn)
    print("✅ Datos demo eliminados. Las tablas están vacías y listas para datos reales.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga datos de demostración")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--limpiar",  action="store_true", help="Borra todo y recarga")
    group.add_argument("--eliminar", action="store_true", help="Solo borra, no recarga")
    args = parser.parse_args()

    try:
        if args.eliminar:
            eliminar_demo()
        else:
            cargar_demo(limpiar=args.limpiar)
    except Exception as exc:
        print(f"\n❌ Error: {exc}")
        if "Connection refused" in str(exc) or "could not connect" in str(exc).lower():
            print("\nPostgreSQL no está corriendo. Para iniciarlo en Windows:")
            print('  pg_ctl start -D "C:/Program Files/PostgreSQL/16/data"')
            print("  o desde Servicios de Windows → busca 'postgresql'")
        sys.exit(1)
