"""
Script para lanzar el dashboard de monitoreo bibliométrico.

Uso:
    python -m scripts.run_dashboard

Variables opcionales:
    DASH_HOST=127.0.0.1
    DASH_PORT=8050
    DASH_DEBUG=true
    DASH_OPEN_BROWSER=false
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser

from dashboard.index import app, server  # noqa: F401
from dashboard.callbacks import filter_callbacks  # noqa: F401
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _open_browser_later(url: str, delay: float = 1.0) -> None:
    def _target() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception as exc:
            logger.warning("No se pudo abrir el navegador automáticamente: %s", exc)

    threading.Thread(target=_target, daemon=True).start()


def main() -> None:
    host = os.getenv("DASH_HOST", "127.0.0.1")
    port = int(os.getenv("DASH_PORT", "8050"))
    debug = _env_bool("DASH_DEBUG", True)
    open_browser = _env_bool("DASH_OPEN_BROWSER", False)

    url = f"http://{host}:{port}/"
    logger.info("Lanzando dashboard en %s", url)

    if open_browser:
        _open_browser_later(url)

    app.run(debug=debug, host=host, port=port)


if __name__ == "__main__":
    main()
