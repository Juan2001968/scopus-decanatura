"""
Cliente base para la API de Scopus.

Gestiona autenticación, headers, rate limiting, reintentos con backoff
exponencial y cache en disco. Todos los demás módulos de ``api_scopus/``
usan este cliente internamente.

La API de Scopus usa REST con JSON. Los endpoints principales son:

- **Author Retrieval**: perfil completo del autor (h-index, nombres, docs).
- **Author Search**: buscar autores por ORCID u otros criterios.
- **Scopus Search**: buscar publicaciones por Author ID.

Headers requeridos:

- ``X-ELS-APIKey``: clave de API de Elsevier Developer.
- ``X-ELS-Insttoken``: token institucional (opcional, si no se usa IP).
- ``Accept``: ``application/json``.
"""

from __future__ import annotations

import re
import time
from typing import Dict, Optional

import requests

from config.settings import SCOPUS_API_KEY, SCOPUS_INST_TOKEN
from src.api_scopus.cache import get_cached, set_cached
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.elsevier.com"
"""URL base de la API de Elsevier/Scopus."""

_MAX_RETRIES = 2
"""Número máximo de reintentos para errores de servidor (5xx)."""

_RATE_LIMIT_THRESHOLD = 3
"""Si quedan menos de este número de requests, esperar al reset."""


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------


class ScopusClient:
    """Cliente base para la API de Scopus con cache, rate limiting y reintentos.

    Encapsula toda la comunicación HTTP con la API de Elsevier,
    incluyendo autenticación por API key / token institucional,
    manejo de rate limits (HTTP 429), reintentos con backoff
    exponencial para errores de servidor y cache local en disco.

    Parameters
    ----------
    api_key:
        Clave de API de Elsevier Developer. Si es ``None``, se lee de
        ``config.settings.SCOPUS_API_KEY``.
    inst_token:
        Token institucional. Si es ``None``, se lee de
        ``config.settings.SCOPUS_INST_TOKEN``. Puede quedar vacío.
    cache_max_age_days:
        Máxima antigüedad en días para considerar válida una entrada
        de cache (default 30).

    Raises
    ------
    ValueError
        Si ``api_key`` está vacía o no configurada.

    Example
    -------
    >>> client = ScopusClient()
    >>> data = client.author_retrieval("56501378100")
    >>> data["author-retrieval-response"][0]["h-index"]
    '25'
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        inst_token: Optional[str] = None,
        cache_max_age_days: int = 30,
    ) -> None:
        self._api_key = api_key or SCOPUS_API_KEY
        self._inst_token = inst_token or SCOPUS_INST_TOKEN
        self._cache_max_age_days = cache_max_age_days

        if not self._api_key:
            raise ValueError(
                "SCOPUS_API_KEY no configurada. Revisa tu archivo .env"
            )

        self._session = requests.Session()
        self._session.headers.update(self._build_headers())

        logger.info(
            "ScopusClient inicializado (cache_max_age=%d dias, "
            "inst_token=%s)",
            self._cache_max_age_days,
            "configurado" if self._inst_token else "no configurado",
        )

    # ------------------------------------------------------------------
    # Headers y rate limiting
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        """Construye los headers base para las requests a la API.

        Returns
        -------
        dict[str, str]
            Headers con API key, Accept y opcionalmente token
            institucional.
        """
        headers = {
            "X-ELS-APIKey": self._api_key,
            "Accept": "application/json",
        }
        if self._inst_token:
            headers["X-ELS-Insttoken"] = self._inst_token
        return headers

    def _handle_rate_limit(self, response: requests.Response) -> None:
        """Maneja el rate limiting basándose en los headers de respuesta.

        Lee ``X-RateLimit-Remaining`` y ``X-RateLimit-Reset`` para
        determinar si es necesario esperar antes de la siguiente
        request.

        Parameters
        ----------
        response:
            Respuesta HTTP de la API de Scopus.
        """
        remaining_str = response.headers.get("X-RateLimit-Remaining")
        reset_str = response.headers.get("X-RateLimit-Reset")

        if remaining_str is None:
            return

        try:
            remaining = int(remaining_str)
        except (ValueError, TypeError):
            return

        if remaining < _RATE_LIMIT_THRESHOLD:
            wait_seconds = 1.0  # default mínimo
            if reset_str:
                try:
                    reset_ts = int(reset_str)
                    wait_seconds = max(
                        reset_ts - time.time() + 0.5,
                        1.0,
                    )
                except (ValueError, TypeError):
                    pass

            # Limitar espera máxima a 60 segundos
            wait_seconds = min(wait_seconds, 60.0)

            logger.warning(
                "Rate limit cercano (remaining=%d). "
                "Esperando %.1f segundos.",
                remaining, wait_seconds,
            )
            time.sleep(wait_seconds)

    # ------------------------------------------------------------------
    # Request central
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, str]] = None,
        use_cache: bool = True,
        cache_endpoint: str = "",
        cache_id: str = "",
    ) -> Optional[Dict]:
        """Método central de request con cache, rate limiting y reintentos.

        Flujo:

        1. Si ``use_cache`` y hay cache_endpoint/cache_id, buscar en
           cache. Si hay hit, retornar sin hacer request HTTP.
        2. Hacer la request HTTP.
        3. Si 200: parsear JSON, guardar en cache, retornar.
        4. Si 429: manejar rate limit, reintentar UNA vez.
        5. Si 401/403: lanzar ``PermissionError``.
        6. Si 404: retornar ``None``.
        7. Si 5xx: reintentar hasta ``_MAX_RETRIES`` veces con backoff
           exponencial. Si agota, lanzar ``ConnectionError``.

        Parameters
        ----------
        method:
            Método HTTP (``"GET"``).
        url:
            URL completa del endpoint.
        params:
            Parámetros de query string.
        use_cache:
            Si ``True``, consultar/guardar cache.
        cache_endpoint:
            Nombre del endpoint para la clave de cache.
        cache_id:
            Identificador para la clave de cache.

        Returns
        -------
        dict or None
            Respuesta JSON parseada, o ``None`` si el recurso no
            existe (404).

        Raises
        ------
        PermissionError
            Si la API responde 401 o 403.
        ConnectionError
            Si se agotan los reintentos para errores de servidor.
        """
        # --- Cache lookup ---
        if use_cache and cache_endpoint and cache_id:
            cached = get_cached(
                cache_endpoint, cache_id, self._cache_max_age_days,
            )
            if cached is not None:
                logger.debug(
                    "Cache hit para %s/%s — omitiendo request HTTP",
                    cache_endpoint, cache_id,
                )
                return cached

        # --- Request HTTP con reintentos ---
        last_exception: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._session.request(
                    method, url, params=params, timeout=30,
                )
            except requests.RequestException as exc:
                logger.error(
                    "Error de conexion (intento %d/%d): %s",
                    attempt + 1, _MAX_RETRIES + 1, exc,
                )
                last_exception = exc
                if attempt < _MAX_RETRIES:
                    sleep_time = 2 ** attempt
                    time.sleep(sleep_time)
                    continue
                raise ConnectionError(
                    f"Error de conexion tras {_MAX_RETRIES + 1} intentos: "
                    f"{exc}"
                ) from exc

            status = response.status_code

            # --- 200 OK ---
            if status == 200:
                self._handle_rate_limit(response)
                try:
                    data = response.json()
                except ValueError as exc:
                    logger.error(
                        "Respuesta 200 con JSON invalido: %s", exc,
                    )
                    return None

                if use_cache and cache_endpoint and cache_id:
                    set_cached(cache_endpoint, cache_id, data)

                return data

            # --- 429 Too Many Requests ---
            if status == 429:
                logger.warning(
                    "HTTP 429 Too Many Requests (intento %d)",
                    attempt + 1,
                )
                self._handle_rate_limit(response)
                # Reintentar una vez tras esperar
                if attempt == 0:
                    # Espera mínima si no hubo header de reset
                    if not response.headers.get("X-RateLimit-Reset"):
                        time.sleep(2.0)
                    continue
                # Ya reintentamos, propagar error
                raise ConnectionError(
                    f"Rate limit excedido (HTTP 429) tras reintento. "
                    f"URL: {url}"
                )

            # --- 401 / 403 Autenticación ---
            if status in (401, 403):
                msg = (
                    f"Error de autenticacion con la API de Scopus "
                    f"(HTTP {status}). Verifica SCOPUS_API_KEY y "
                    f"SCOPUS_INST_TOKEN en tu archivo .env. URL: {url}"
                )
                logger.error(msg)
                raise PermissionError(msg)

            # --- 404 Not Found ---
            if status == 404:
                logger.warning(
                    "Recurso no encontrado (HTTP 404): %s", url,
                )
                return None

            # --- 5xx Server Error ---
            if 500 <= status < 600:
                logger.error(
                    "Error de servidor (HTTP %d, intento %d/%d): %s",
                    status, attempt + 1, _MAX_RETRIES + 1, url,
                )
                last_exception = ConnectionError(
                    f"HTTP {status} en {url}",
                )
                if attempt < _MAX_RETRIES:
                    sleep_time = 2 ** attempt
                    logger.info(
                        "Reintentando en %d segundos...", sleep_time,
                    )
                    time.sleep(sleep_time)
                    continue
                raise ConnectionError(
                    f"Error de servidor (HTTP {status}) tras "
                    f"{_MAX_RETRIES + 1} intentos. URL: {url}"
                ) from last_exception

            # --- Otros códigos inesperados ---
            logger.error(
                "Respuesta inesperada (HTTP %d): %s", status, url,
            )
            return None

        # No debería llegar aquí, pero por seguridad
        raise ConnectionError(
            f"Reintentos agotados para {url}"
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def get(
        self,
        url: str,
        params: Optional[Dict[str, str]] = None,
        use_cache: bool = True,
        cache_endpoint: str = "",
        cache_id: str = "",
    ) -> Optional[Dict]:
        """Ejecuta un GET contra la API de Scopus.

        Wrapper público de :meth:`_request` para peticiones GET.

        Parameters
        ----------
        url:
            URL completa del endpoint.
        params:
            Parámetros de query string.
        use_cache:
            Si ``True``, consultar/guardar cache.
        cache_endpoint:
            Nombre del endpoint para la clave de cache.
        cache_id:
            Identificador para la clave de cache.

        Returns
        -------
        dict or None
            Respuesta JSON parseada, o ``None`` si 404.
        """
        return self._request(
            method="GET",
            url=url,
            params=params,
            use_cache=use_cache,
            cache_endpoint=cache_endpoint,
            cache_id=cache_id,
        )

    def author_retrieval(
        self,
        author_id: str,
        view: str = "ENHANCED",
    ) -> Optional[Dict]:
        """Consulta el perfil completo de un autor por su Scopus Author ID.

        Endpoint: ``/content/author/author_id/{author_id}``

        La vista ``ENHANCED`` incluye h-index, variantes de nombre,
        conteo de documentos, subject areas y métricas del autor.

        Parameters
        ----------
        author_id:
            Scopus Author ID (ej. ``"56501378100"``).
        view:
            Vista de la API. Default ``"ENHANCED"`` para datos
            completos.

        Returns
        -------
        dict or None
            JSON de respuesta completo, o ``None`` si el autor no
            existe (404).

        Example
        -------
        >>> client = ScopusClient()
        >>> data = client.author_retrieval("56501378100")
        """
        url = f"{_BASE_URL}/content/author/author_id/{author_id}"
        logger.info("Author Retrieval: author_id=%s", author_id)

        return self.get(
            url=url,
            params={"view": view},
            use_cache=True,
            cache_endpoint="author_retrieval",
            cache_id=author_id,
        )

    def author_search_by_orcid(
        self,
        orcid: str,
    ) -> Optional[Dict]:
        """Busca un autor en Scopus por su ORCID.

        Endpoint: ``/content/search/author?query=ORCID({orcid})``

        Parameters
        ----------
        orcid:
            ORCID del autor (ej. ``"0000-0003-2699-398X"``).

        Returns
        -------
        dict or None
            JSON de respuesta con resultados de búsqueda, o ``None``
            si no hay resultados.

        Example
        -------
        >>> client = ScopusClient()
        >>> data = client.author_search_by_orcid("0000-0003-2699-398X")
        >>> data["search-results"]["opensearch:totalResults"]
        '1'
        """
        url = f"{_BASE_URL}/content/search/author"
        logger.info("Author Search by ORCID: %s", orcid)

        return self.get(
            url=url,
            params={"query": f"ORCID({orcid})"},
            use_cache=True,
            cache_endpoint="author_search_orcid",
            cache_id=orcid,
        )

    def search_author_publications(
        self,
        author_id: str,
        count: int = 200,
    ) -> Optional[Dict]:
        """Busca publicaciones de un autor por su Scopus Author ID.

        Endpoint: ``/content/search/scopus?query=AU-ID({author_id})``

        Ordena por fecha de publicación descendente. Retorna hasta
        ``count`` resultados en la primera página.

        Parameters
        ----------
        author_id:
            Scopus Author ID.
        count:
            Número máximo de resultados por página (default 200).

        Returns
        -------
        dict or None
            JSON de respuesta con los resultados de búsqueda.

        Example
        -------
        >>> client = ScopusClient()
        >>> data = client.search_author_publications("56501378100")
        >>> len(data["search-results"]["entry"])
        45

        .. note::
            Si el autor tiene más publicaciones que ``count``, la API
            incluye un link ``next`` en los resultados.
        """
        # TODO: implementar paginación para autores con más de {count}
        # publicaciones si el response indica que hay más.
        url = f"{_BASE_URL}/content/search/scopus"
        logger.info(
            "Search Author Publications: author_id=%s, count=%d",
            author_id, count,
        )

        return self.get(
            url=url,
            params={
                "query": f"AU-ID({author_id})",
                "count": str(count),
                "sort": "-coverDate",
            },
            use_cache=True,
            cache_endpoint="author_publications",
            cache_id=author_id,
        )

    def author_search_by_name(
        self,
        last_name: str,
        first_name: str = "",
        affiliation: str = "Universidad del Norte",
    ) -> Optional[Dict]:
        """Busca autores en Scopus por apellido, nombre y afiliación.

        Útil para encontrar Author IDs cuando no se dispone de ORCID.
        Intenta con ``AUTHLASTNAME + AUTHFIRST + AFFIL``; si ``first_name``
        está vacío, omite el filtro de nombre.

        Parameters
        ----------
        last_name:
            Apellido del autor (ej. ``"García"``).
        first_name:
            Nombre del autor (ej. ``"Juan"``). Opcional.
        affiliation:
            Institución de afiliación. Mejora la precisión.

        Returns
        -------
        dict or None
            JSON de respuesta con resultados, o ``None`` si hay error.

        Example
        -------
        >>> client = ScopusClient()
        >>> data = client.author_search_by_name("García", "Juan")
        >>> data["search-results"]["opensearch:totalResults"]
        '2'
        """
        query_parts = [f"AUTHLASTNAME({last_name})"]
        if first_name:
            query_parts.append(f"AUTHFIRST({first_name})")
        if affiliation:
            query_parts.append(f"AFFIL({affiliation})")
        query = " AND ".join(query_parts)

        # cache_id sin caracteres especiales
        raw_id = f"{last_name}_{first_name}_{affiliation}"
        cache_id = re.sub(r"[^a-zA-Z0-9_]", "_", raw_id).lower()[:120]

        url = f"{_BASE_URL}/content/search/author"
        logger.info(
            "Author Search by Name: apellido=%s, nombre=%s, afil=%s",
            last_name, first_name, affiliation,
        )

        return self.get(
            url=url,
            params={"query": query, "count": "25"},
            use_cache=True,
            cache_endpoint="author_search_name",
            cache_id=cache_id,
        )

    def search_publications_page(
        self,
        query: str,
        start: int = 0,
        count: int = 200,
    ) -> Optional[Dict]:
        """Busca publicaciones en Scopus con paginación explícita.

        Versión paginada que permite recuperar resultados más allá
        de los primeros ``count`` (útil para autores con >200 docs).

        Parameters
        ----------
        query:
            Query en sintaxis Scopus
            (ej. ``"AU-ID(56501378100) OR AU-ID(23456789)"``).
        start:
            Índice de inicio de la página (0, 200, 400 …).
        count:
            Tamaño de página, máximo 200.

        Returns
        -------
        dict or None
            JSON de respuesta, o ``None`` si hay error.

        Example
        -------
        >>> client = ScopusClient()
        >>> page2 = client.search_publications_page(
        ...     "AU-ID(56501378100)", start=200
        ... )
        """
        url = f"{_BASE_URL}/content/search/scopus"
        raw_id = f"{query}_s{start}"
        cache_id = re.sub(r"[^a-zA-Z0-9_]", "_", raw_id)[:120]

        logger.info(
            "Search Publications Page: start=%d, count=%d, query=%.80s",
            start, count, query,
        )

        return self.get(
            url=url,
            params={
                "query": query,
                "count": str(count),
                "start": str(start),
                "sort": "-coverDate",
            },
            use_cache=True,
            cache_endpoint="publications_page",
            cache_id=cache_id,
        )

    def test_connection(self) -> bool:
        """Verifica la conectividad con la API de Scopus.

        Realiza una búsqueda de autor mínima para comprobar que la
        API key es válida y hay conectividad.

        Returns
        -------
        bool
            ``True`` si la API responde correctamente, ``False`` en
            caso contrario.

        Example
        -------
        >>> client = ScopusClient()
        >>> client.test_connection()
        True
        """
        logger.info("Probando conexion con API de Scopus...")
        try:
            result = self.get(
                url=f"{_BASE_URL}/content/search/author",
                params={"query": "AUTHLASTNAME(test)", "count": "1"},
                use_cache=False,
            )
            if result is not None:
                logger.info("Conexion con API de Scopus exitosa")
                return True
            logger.error("API de Scopus retorno None en test")
            return False
        except PermissionError:
            logger.error(
                "Fallo de autenticacion en test de conexion. "
                "Verifica SCOPUS_API_KEY.",
            )
            return False
        except ConnectionError as exc:
            logger.error(
                "Fallo de conexion en test: %s", exc,
            )
            return False
        except Exception as exc:
            logger.error(
                "Error inesperado en test de conexion: %s", exc,
            )
            return False
