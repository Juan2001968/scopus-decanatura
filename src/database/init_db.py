"""
Inicialización de la base de datos.

Crea el esquema PostgreSQL ``biblio`` y todas las tablas definidas
en los modelos ORM. Puede ejecutarse directamente o importarse
desde ``scripts/init_database.py``.
"""

from typing import List

from sqlalchemy import inspect, text

from config.db_config import Base, get_engine
from config.settings import DB_SCHEMA

# Importar todos los modelos para registrarlos en Base.metadata
from src.database.models import (  # noqa: F401
    AutorScopus,
    Departamento,
    Fuente,
    FuenteMetrica,
    LogIngesta,
    Publicacion,
    PublicacionProfesor,
)

from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_schema_and_tables() -> List[str]:
    """Crea el esquema y todas las tablas del sistema bibliométrico.

    1. Crea el esquema ``biblio`` si no existe.
    2. Ejecuta ``Base.metadata.create_all()`` para crear las tablas.
    3. Retorna la lista de tablas existentes en el esquema.

    Returns
    -------
    list[str]
        Nombres de las tablas en el esquema tras la creación.

    Raises
    ------
    ValueError
        Si las variables de conexión (DB_USER, DB_NAME) están vacías.
    """
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}"))
        conn.commit()
    logger.info("Esquema '%s' verificado/creado", DB_SCHEMA)

    Base.metadata.create_all(bind=engine)

    tables = inspect(engine).get_table_names(schema=DB_SCHEMA)
    logger.info(
        "Tablas en esquema '%s': %s",
        DB_SCHEMA,
        ", ".join(tables) if tables else "(ninguna)",
    )
    return tables


def drop_all_tables() -> None:
    """Elimina TODAS las tablas del esquema. Solo para desarrollo/testing.

    .. warning::
        Esta operación es irreversible. No usar en producción.
    """
    engine = get_engine()
    logger.warning("ELIMINANDO todas las tablas del esquema '%s'", DB_SCHEMA)
    Base.metadata.drop_all(bind=engine)
    logger.warning("Tablas eliminadas del esquema '%s'", DB_SCHEMA)


if __name__ == "__main__":
    tables = create_schema_and_tables()
    print(f"Tablas creadas: {tables}")
