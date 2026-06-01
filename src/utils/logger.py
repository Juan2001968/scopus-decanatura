"""
Configuración centralizada de logging del proyecto.

Provee ``get_logger`` para obtener loggers con salida simultánea
a consola y a archivo rotativo en ``logs/biblio_system.log``.
"""

import logging
from logging.handlers import RotatingFileHandler

from config.settings import LOGS_DIR

_LOG_FILE = LOGS_DIR / "biblio_system.log"
_LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
_MAX_BYTES = 5_000_000
_BACKUP_COUNT = 3

_initialized: set = set()


def get_logger(name: str) -> logging.Logger:
    """Retorna un logger configurado con salida a consola y archivo rotativo.

    Si el logger ya fue configurado previamente, lo retorna sin
    agregar handlers duplicados.

    Parameters
    ----------
    name:
        Nombre del logger (típicamente ``__name__``).

    Returns
    -------
    logging.Logger
        Logger listo para usar.

    Example
    -------
    >>> logger = get_logger(__name__)
    >>> logger.info("Pipeline iniciado")
    """
    if name in _initialized:
        return logging.getLogger(name)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _initialized.add(name)
    return logger
