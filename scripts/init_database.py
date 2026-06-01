"""
Script para inicializar la base de datos PostgreSQL.

Crea el esquema ``biblio`` y todas las tablas definidas en los modelos ORM.
Uso: ``python -m scripts.init_database``
"""

import sys

from src.database.init_db import create_schema_and_tables
from src.utils.logger import get_logger

logger = get_logger(__name__)


def main() -> None:
    """Punto de entrada del script de inicialización."""
    try:
        tables = create_schema_and_tables()
        logger.info("Base de datos inicializada. Tablas: %s", tables)
        print(f"\nBase de datos inicializada correctamente.")
        print(f"  Tablas creadas: {', '.join(tables) if tables else 'ninguna'}")
    except ValueError as exc:
        logger.error("Error de configuracion: %s", exc)
        print(f"\nError de configuracion: {exc}", file=sys.stderr)
        print(
            "  Revisa las variables DB_USER y DB_NAME en tu archivo .env",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        logger.error("Error al inicializar la base de datos: %s", exc)
        print(f"\nError de conexion: {exc}", file=sys.stderr)
        print(
            "  Verifica que PostgreSQL este corriendo y que las "
            "credenciales en .env sean correctas.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
