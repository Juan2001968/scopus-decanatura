"""
Punto central de configuración del proyecto bibliométrico.

Carga variables de entorno desde .env, define rutas del proyecto,
parámetros de conexión a BD, credenciales de API y constantes del sistema.
"""

import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
"""Raíz del proyecto (directorio que contiene config/)."""

load_dotenv(PROJECT_ROOT / ".env")

DATA_RAW_DIR: Path = PROJECT_ROOT / "data" / "raw"
DATA_INTERIM_DIR: Path = PROJECT_ROOT / "data" / "interim"
DATA_PROCESSED_DIR: Path = PROJECT_ROOT / "data" / "processed"
DATA_EXTERNAL_DIR: Path = PROJECT_ROOT / "data" / "external"
LOGS_DIR: Path = PROJECT_ROOT / "logs"

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: str = os.getenv("DB_PORT", "5432")
DB_NAME: str = os.getenv("DB_NAME", "")
DB_USER: str = os.getenv("DB_USER", "")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
DB_SCHEMA: str = "biblio"

DATABASE_URL: str = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)


def _host_requires_ssl(host: str) -> bool:
    """Indica si el host corresponde a una BD gestionada de Render.

    Cubre tanto el host externo (``*.oregon-postgres.render.com``) como el
    host interno (``dpg-xxxxxxxx-a``), ambos sirven sobre SSL.
    """
    return "render.com" in host or host.startswith("dpg-")


DB_SSLMODE: str | None = os.getenv("DB_SSLMODE") or (
    "require" if _host_requires_ssl(DB_HOST) else None
)
"""Modo SSL para psycopg2. ``None`` en local (no se fuerza SSL); ``require`` en Render.

Se puede sobrescribir con la variable de entorno ``DB_SSLMODE``.
"""

# ---------------------------------------------------------------------------
# API de Scopus
# ---------------------------------------------------------------------------

SCOPUS_API_KEY: str = os.getenv("SCOPUS_API_KEY", "")
SCOPUS_INST_TOKEN: str = os.getenv("SCOPUS_INST_TOKEN", "")

# ---------------------------------------------------------------------------
# Parámetros del sistema
# ---------------------------------------------------------------------------

ROLLING_WINDOW_YEARS: int = 3
"""Cantidad de años para la ventana móvil de análisis (usado en ETL)."""

PUB_YEAR_INICIO: int = 2014
"""Año de inicio del período de análisis del dashboard."""

PUB_YEAR_FIN: int = 2025
"""Año de cierre del período de análisis del dashboard."""

FUZZY_MATCH_THRESHOLD: float = 0.90
"""Umbral mínimo de similitud Jaro-Winkler para matching de nombres."""

DEFAULT_ENCODING: str = "utf-8"

FECHA_CORTE_DATOS: str = "abril 2026"
"""Fecha de la última descarga de datos de Scopus (MAX(fecha_ingesta) en biblio.publicacion)."""

# ---------------------------------------------------------------------------
# Validación al importar
# ---------------------------------------------------------------------------

if not DB_NAME:
    warnings.warn(
        "La variable de entorno DB_NAME está vacía. "
        "Configúrala en el archivo .env antes de conectar a la base de datos.",
        stacklevel=2,
    )

if not DB_USER:
    warnings.warn(
        "La variable de entorno DB_USER está vacía. "
        "Configúrala en el archivo .env antes de conectar a la base de datos.",
        stacklevel=2,
    )
