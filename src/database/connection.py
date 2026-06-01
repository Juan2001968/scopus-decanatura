"""
Capa de conexión a nivel aplicación.

Re-exporta las piezas de ``config.db_config`` y agrega una utilidad
de diagnóstico para verificar el estado de la base de datos.
"""

from typing import Dict, List

from sqlalchemy import inspect, text

from config.db_config import Base, get_engine, get_session  # noqa: F401 — re-export
from config.settings import DB_NAME, DB_SCHEMA


def get_db_status() -> Dict[str, object]:
    """Retorna el estado actual de la conexión a la base de datos.

    Intenta conectar al motor y listar las tablas existentes en el
    esquema ``biblio``. No lanza excepciones: si falla la conexión,
    retorna ``connected=False``.

    Returns
    -------
    dict
        Diccionario con keys ``connected`` (bool), ``database`` (str),
        ``schema`` (str) y ``tables`` (list[str]).

    Example
    -------
    >>> status = get_db_status()
    >>> if status["connected"]:
    ...     print(f"Tablas: {status['tables']}")
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        tables: List[str] = inspect(engine).get_table_names(schema=DB_SCHEMA)
        return {
            "connected": True,
            "database": DB_NAME,
            "schema": DB_SCHEMA,
            "tables": tables,
        }
    except Exception:
        return {
            "connected": False,
            "database": DB_NAME,
            "schema": DB_SCHEMA,
            "tables": [],
        }
