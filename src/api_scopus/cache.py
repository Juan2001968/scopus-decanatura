"""
Cache local en disco de respuestas de la API de Scopus.

Almacena respuestas JSON en archivos individuales dentro de
``data/interim/api_cache/``, evitando consultas repetidas durante
desarrollo, testing y re-ejecuciones del pipeline.

Cada entrada de cache se identifica por la combinación de endpoint
e identifier (ej. ``author_retrieval_56501378100.json``). Las entradas
expiran después de ``max_age_days`` días (por defecto 30).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from config.settings import DATA_INTERIM_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _get_cache_dir() -> Path:
    """Retorna la ruta del directorio de cache, creándolo si no existe.

    El directorio se ubica en ``DATA_INTERIM_DIR / "api_cache"``.

    Returns
    -------
    Path
        Ruta absoluta al directorio de cache.

    Example
    -------
    >>> cache_dir = _get_cache_dir()
    >>> cache_dir.name
    'api_cache'
    """
    cache_dir = DATA_INTERIM_DIR / "api_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _build_cache_key(endpoint: str, identifier: str) -> str:
    """Construye un nombre de archivo seguro para una entrada de cache.

    Combina ``endpoint`` e ``identifier``, reemplazando caracteres
    especiales (``/``, ``:``, espacios) por guion bajo para generar
    un nombre de archivo válido en cualquier sistema operativo.

    Parameters
    ----------
    endpoint:
        Nombre del endpoint de la API (ej. ``"author_retrieval"``,
        ``"author_search"``).
    identifier:
        Identificador único de la consulta (ej. Scopus Author ID,
        ORCID).

    Returns
    -------
    str
        Nombre de archivo con extensión ``.json``.

    Examples
    --------
    >>> _build_cache_key("author_retrieval", "56501378100")
    'author_retrieval_56501378100.json'
    >>> _build_cache_key("author/search", "orcid:0000-0003-2699-398X")
    'author_search_orcid_0000-0003-2699-398X.json'
    """
    raw = f"{endpoint}_{identifier}"
    safe = re.sub(r"[/:\s]+", "_", raw)
    return f"{safe}.json"


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------


def get_cached(
    endpoint: str,
    identifier: str,
    max_age_days: int = 30,
) -> Optional[Dict]:
    """Busca una respuesta en cache y la retorna si no ha expirado.

    Verifica la antigüedad del archivo comparando su fecha de
    modificación (``mtime``) con la fecha actual. Si supera
    ``max_age_days``, se considera expirado y retorna ``None``.

    Parameters
    ----------
    endpoint:
        Nombre del endpoint de la API.
    identifier:
        Identificador único de la consulta.
    max_age_days:
        Máxima antigüedad en días antes de considerar el cache
        expirado. Por defecto 30 días.

    Returns
    -------
    dict or None
        Datos cacheados como diccionario, o ``None`` si no hay cache,
        está expirado o es ilegible.

    Example
    -------
    >>> data = get_cached("author_retrieval", "56501378100")
    >>> if data is None:
    ...     data = call_api(...)
    ...     set_cached("author_retrieval", "56501378100", data)
    """
    cache_dir = _get_cache_dir()
    filename = _build_cache_key(endpoint, identifier)
    filepath = cache_dir / filename

    if not filepath.exists():
        return None

    # Verificar antigüedad
    mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
    age_days = (datetime.now() - mtime).total_seconds() / 86400.0

    if age_days > max_age_days:
        logger.info(
            "Cache expirado (%.1f dias > %d): %s",
            age_days, max_age_days, filename,
        )
        return None

    # Leer y parsear JSON
    try:
        text = filepath.read_text(encoding="utf-8")
        data = json.loads(text)
        logger.debug("Cache hit: %s (%.1f dias)", filename, age_days)
        return data
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning(
            "Cache corrupto o ilegible (%s): %s — tratado como miss",
            filename, exc,
        )
        return None


def set_cached(
    endpoint: str,
    identifier: str,
    data: Dict,
) -> None:
    """Guarda una respuesta de la API en cache.

    Serializa ``data`` a JSON con indentación legible y soporte
    para caracteres Unicode (nombres con acentos).

    Parameters
    ----------
    endpoint:
        Nombre del endpoint de la API.
    identifier:
        Identificador único de la consulta.
    data:
        Diccionario con la respuesta de la API a cachear.

    Example
    -------
    >>> set_cached("author_retrieval", "56501378100", {"h_index": 25})
    """
    cache_dir = _get_cache_dir()
    filename = _build_cache_key(endpoint, identifier)
    filepath = cache_dir / filename

    try:
        content = json.dumps(data, indent=2, ensure_ascii=False)
        filepath.write_text(content, encoding="utf-8")
        logger.debug("Cache guardado: %s", filename)
    except (TypeError, OSError) as exc:
        logger.warning(
            "No se pudo guardar cache (%s): %s", filename, exc,
        )


def clear_cache(endpoint: Optional[str] = None) -> int:
    """Limpia archivos del cache.

    Si ``endpoint`` es ``None``, borra todo el contenido del directorio.
    Si ``endpoint`` tiene valor, borra solo los archivos cuyo nombre
    comience con ese prefijo.

    Parameters
    ----------
    endpoint:
        Prefijo del endpoint para filtrar. Si es ``None``, borra todo.

    Returns
    -------
    int
        Número de archivos eliminados.

    Examples
    --------
    >>> clear_cache()  # borra todo
    15
    >>> clear_cache("author_retrieval")  # solo este endpoint
    5
    """
    cache_dir = _get_cache_dir()
    deleted = 0

    for filepath in cache_dir.glob("*.json"):
        if endpoint is None or filepath.name.startswith(endpoint):
            try:
                filepath.unlink()
                deleted += 1
            except OSError as exc:
                logger.warning(
                    "No se pudo borrar %s: %s", filepath.name, exc,
                )

    logger.info(
        "Cache limpiado: %d archivos eliminados%s",
        deleted,
        f" (prefijo='{endpoint}')" if endpoint else " (todo)",
    )
    return deleted


def get_cache_stats() -> Dict[str, object]:
    """Retorna estadísticas del directorio de cache.

    Cuenta archivos JSON, suma tamaño total y encuentra las fechas
    del archivo más antiguo y más reciente.

    Returns
    -------
    dict
        Estadísticas con keys:

        - ``total_files`` (int): cantidad de archivos JSON.
        - ``total_size_bytes`` (int): tamaño total en bytes.
        - ``oldest`` (str or None): nombre del archivo más antiguo.
        - ``newest`` (str or None): nombre del archivo más reciente.

    Example
    -------
    >>> stats = get_cache_stats()
    >>> stats["total_files"]
    42
    """
    cache_dir = _get_cache_dir()
    files = list(cache_dir.glob("*.json"))

    if not files:
        return {
            "total_files": 0,
            "total_size_bytes": 0,
            "oldest": None,
            "newest": None,
        }

    total_size = 0
    oldest_mtime = float("inf")
    newest_mtime = 0.0
    oldest_name: Optional[str] = None
    newest_name: Optional[str] = None

    for fp in files:
        stat = fp.stat()
        total_size += stat.st_size
        mtime = stat.st_mtime

        if mtime < oldest_mtime:
            oldest_mtime = mtime
            oldest_name = fp.name

        if mtime > newest_mtime:
            newest_mtime = mtime
            newest_name = fp.name

    return {
        "total_files": len(files),
        "total_size_bytes": total_size,
        "oldest": oldest_name,
        "newest": newest_name,
    }
