"""
Configuración de la conexión a PostgreSQL con SQLAlchemy.

Expone el engine, la sesión, la Base declarativa y funciones auxiliares
para obtener sesiones y para inicializar el esquema de la base de datos.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config.settings import DATABASE_URL, DB_NAME, DB_SCHEMA, DB_SSLMODE, DB_USER

# ---------------------------------------------------------------------------
# Validación interna
# ---------------------------------------------------------------------------


def _validate_connection_config() -> None:
    """Verifica que las variables mínimas de conexión estén presentes."""
    missing = []
    if not DB_USER:
        missing.append("DB_USER")
    if not DB_NAME:
        missing.append("DB_NAME")
    if missing:
        raise ValueError(
            f"No se puede conectar a la base de datos: las variables "
            f"{', '.join(missing)} están vacías. Revisa tu archivo .env."
        )


# ---------------------------------------------------------------------------
# Engine y sesión
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None

Base = declarative_base()
"""Clase base declarativa para todos los modelos ORM del proyecto."""


def _get_or_create_engine() -> Engine:
    """Crea el engine en la primera llamada y lo reutiliza después."""
    global _engine
    if _engine is None:
        _validate_connection_config()
        connect_args: dict[str, str] = {}
        if DB_SSLMODE:
            connect_args["sslmode"] = DB_SSLMODE
        _engine = create_engine(
            DATABASE_URL,
            echo=False,
            pool_size=5,
            pool_pre_ping=True,
            connect_args=connect_args,
            # Codificacion explicita: si la BD contiene bytes no UTF-8 el
            # fallo es deterministico y detectable, en vez de depender del
            # client_encoding por defecto del entorno.
            client_encoding="utf8",
        )

        @event.listens_for(_engine, "connect")
        def _set_search_path(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f"SET search_path TO {DB_SCHEMA}, public")
            cursor.close()

    return _engine


def _get_session_factory() -> sessionmaker:
    """Crea la fábrica de sesiones en la primera llamada y la reutiliza."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_or_create_engine())
    return _SessionLocal


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def get_engine() -> Engine:
    """Retorna el engine de SQLAlchemy.

    Útil para operaciones bulk con pandas (``pd.read_sql``, ``to_sql``).

    Raises:
        ValueError: Si las variables de conexión están incompletas.
    """
    return _get_or_create_engine()


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Genera una sesión de base de datos con manejo automático de cierre.

    Uso::

        with get_session() as session:
            results = session.execute(...)

    La sesión hace commit automático al salir del bloque sin errores
    y rollback si ocurre una excepción.

    Raises:
        ValueError: Si las variables de conexión están incompletas.
    """
    session: Session = _get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Crea todas las tablas registradas en ``Base.metadata``.

    Ejecuta ``CREATE SCHEMA IF NOT EXISTS`` para el esquema configurado
    y luego ``Base.metadata.create_all()``.

    Raises:
        ValueError: Si las variables de conexión están incompletas.
    """
    engine = _get_or_create_engine()
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
