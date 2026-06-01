"""
Paquete de base de datos del sistema bibliométrico.

Expone modelos ORM, funciones de conexión y la tabla asociativa::

    from src.database import Publicacion, Profesor, get_session
"""

from src.database.connection import Base, get_db_status, get_engine, get_session
from src.database.models import (
    AutorScopus,
    Departamento,
    Fuente,
    FuenteMetrica,
    LogIngesta,
    Profesor,
    Publicacion,
    PublicacionProfesor,
    publicacion_profesor_table,
)

__all__ = [
    "Base",
    "get_session",
    "get_engine",
    "get_db_status",
    "Departamento",
    "Profesor",
    "AutorScopus",
    "Fuente",
    "FuenteMetrica",
    "Publicacion",
    "PublicacionProfesor",
    "publicacion_profesor_table",
    "LogIngesta",
]
