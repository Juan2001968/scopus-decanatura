"""
Paquete de configuración del sistema bibliométrico.

Uso::

    from config import settings
    from config import get_engine, get_session
"""

from config import settings
from config.db_config import Base, get_engine, get_session, init_db

__all__ = [
    "settings",
    "Base",
    "get_engine",
    "get_session",
    "init_db",
]
