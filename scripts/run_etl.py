"""
Script principal para ejecutar el pipeline ETL completo.

Orquesta:
1. Inicialización de esquema/tablas.
2. Ingesta de profesores.
3. Ingesta de publicaciones.
4. Limpieza de publicaciones.
5. Normalización de fuentes/keywords.
6. Enriquecimiento de fuentes.
7. Vinculación publicación-profesor.
8. Carga final a PostgreSQL.

Uso:
    python -m scripts.run_etl
"""

from __future__ import annotations

import sys
from datetime import datetime

import pandas as pd

from src.database.init_db import create_schema_and_tables
from src.etl.clean import run_cleaning_pipeline
from src.etl.enrich_sources import run_enrichment
from src.etl.ingest_professors import consolidate_professors, load_all_professors
from src.etl.ingest_publications import load_all_publications
from src.etl.link_authors import link_publications_to_professors
from src.etl.load import run_full_load
from src.etl.normalize import run_normalization
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _safe_len(df: object) -> int:
    if isinstance(df, pd.DataFrame):
        return len(df)
    return 0


def main() -> None:
    start_time = datetime.now()

    try:
        logger.info("=== ETL completo iniciado ===")

        # ------------------------------------------------------------------
        # 0. Inicializar BD
        # ------------------------------------------------------------------
        tables = create_schema_and_tables()
        logger.info("Base de datos inicializada/verificada. Tablas: %s", tables)

        # ------------------------------------------------------------------
        # 1. Ingesta de profesores
        # ------------------------------------------------------------------
        logger.info("Paso 1/7: ingesta de profesores")
        df_prof_raw = load_all_professors()
        logger.info("Profesores crudos cargados: %d", _safe_len(df_prof_raw))

        df_profesores, df_autores_scopus = consolidate_professors(df_prof_raw)
        logger.info(
            "Profesores consolidados: %d | Perfiles Scopus: %d",
            _safe_len(df_profesores),
            _safe_len(df_autores_scopus),
        )

        # ------------------------------------------------------------------
        # 2. Ingesta de publicaciones
        # ------------------------------------------------------------------
        logger.info("Paso 2/7: ingesta de publicaciones")
        df_publications_raw = load_all_publications()
        logger.info("Publicaciones crudas cargadas: %d", _safe_len(df_publications_raw))

        # ------------------------------------------------------------------
        # 3. Limpieza
        # ------------------------------------------------------------------
        logger.info("Paso 3/7: limpieza de publicaciones")
        df_publications_clean, clean_stats = run_cleaning_pipeline(df_publications_raw)
        logger.info("Limpieza completada: %s", clean_stats)

        # ------------------------------------------------------------------
        # 4. Normalización
        # ------------------------------------------------------------------
        logger.info("Paso 4/7: normalización de entidades")
        df_fuentes, df_keywords, publication_fuente_map = run_normalization(
            df_publications_clean,
        )
        logger.info(
            "Normalización completada | Fuentes: %d | Keywords: %d | Pub-fuente: %d",
            _safe_len(df_fuentes),
            _safe_len(df_keywords),
            len(publication_fuente_map),
        )

        # ------------------------------------------------------------------
        # 5. Enriquecimiento de fuentes
        # ------------------------------------------------------------------
        logger.info("Paso 5/7: enriquecimiento de fuentes")
        df_fuentes_enriched = run_enrichment(df_fuentes)
        logger.info(
            "Fuentes enriquecidas: %d",
            _safe_len(df_fuentes_enriched),
        )

        # ------------------------------------------------------------------
        # 6. Vinculación publicación-profesor
        # ------------------------------------------------------------------
        logger.info("Paso 6/7: vinculación publicación-profesor")
        df_links = link_publications_to_professors(
            df_publications_clean,
            df_profesores,
            df_autores_scopus,
        )
        logger.info("Vínculos generados: %d", _safe_len(df_links))

        # ------------------------------------------------------------------
        # 7. Carga final a PostgreSQL
        # ------------------------------------------------------------------
        logger.info("Paso 7/7: carga final a PostgreSQL")
        load_stats = run_full_load(
            df_profesores=df_profesores,
            df_autores_scopus=df_autores_scopus,
            df_publications=df_publications_clean,
            df_fuentes=df_fuentes,
            df_fuentes_enriched=df_fuentes_enriched,
            publication_fuente_map=publication_fuente_map,
            df_links=df_links,
        )

        duration = round((datetime.now() - start_time).total_seconds(), 2)

        print("\nETL completado correctamente.")
        print(f"  Tablas verificadas: {', '.join(tables) if tables else 'ninguna'}")
        print(f"  Profesores: {_safe_len(df_profesores)}")
        print(f"  Autores Scopus: {_safe_len(df_autores_scopus)}")
        print(f"  Publicaciones limpias: {_safe_len(df_publications_clean)}")
        print(f"  Fuentes: {_safe_len(df_fuentes)}")
        print(f"  Fuentes enriquecidas: {_safe_len(df_fuentes_enriched)}")
        print(f"  Keywords: {_safe_len(df_keywords)}")
        print(f"  Vínculos pub-profesor: {_safe_len(df_links)}")
        print(f"  Estadísticas de carga: {load_stats}")
        print(f"  Duración total: {duration} segundos")

        logger.info(
            "=== ETL completo finalizado en %.2fs | load_stats=%s ===",
            duration,
            load_stats,
        )

    except Exception as exc:
        logger.exception("Error en run_etl: %s", exc)
        print(f"\nError en run_etl: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
