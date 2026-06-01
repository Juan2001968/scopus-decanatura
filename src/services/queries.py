"""
Funciones reutilizables de consulta a la base de datos.

Capa de acceso a datos que retorna ``pd.DataFrame`` para uso directo
en ``metrics.py``, ``aggregations.py`` y el dashboard Dash.

Cada funcion construye una query SQL parametrizada con
``sqlalchemy.text()``, la ejecuta via ``pd.read_sql()`` contra el
engine y retorna un DataFrame.  Los filtros opcionales (``None``) se
omiten de la query, retornando todos los registros.

Principio de diseno:

- **Solo recuperacion de datos** — las metricas derivadas se calculan
  en ``metrics.py``.
- **Todas las funciones retornan pd.DataFrame** — incluso vacio con
  columnas correctas cuando no hay resultados o hay error.
- **Queries parametrizadas** — los valores de usuario nunca se
  interpolan en el SQL; se pasan como ``:param`` con bind parameters.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from config.db_config import get_engine
from config.settings import DB_SCHEMA, ROLLING_WINDOW_YEARS
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes internas
# ---------------------------------------------------------------------------

_S = DB_SCHEMA
"""Nombre del esquema PostgreSQL (``biblio``)."""

# Columnas esperadas para DataFrames vacios
_PUB_BASE_COLS: List[str] = [
    "id_publicacion", "eid", "doi", "titulo", "anio_publicacion",
    "tipo_documental", "idioma", "cited_by_count", "open_access",
    "authors_raw", "indexed_keywords", "source_title", "issn",
    "tipo_fuente", "publisher", "sjr", "citescore", "snip",
    "cuartil_sjr",
]

_PUB_PROF_EXTRA: List[str] = [
    "id_profesor", "nombre_normalizado", "nombre_departamento",
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _exec(sql: str, params: Optional[dict] = None) -> pd.DataFrame:
    """Ejecuta una query SQL parametrizada y retorna un DataFrame.

    Obtiene el engine de forma lazy (no se crea hasta la primera
    llamada real) y usa una conexion del pool para la consulta.

    Parameters
    ----------
    sql:
        Query SQL como string.  Se envuelve en ``text()`` internamente.
    params:
        Diccionario de parametros para bind (``{":nombre": valor}``).

    Returns
    -------
    pd.DataFrame
        Resultado de la query.
    """
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def _empty(columns: List[str]) -> pd.DataFrame:
    """Retorna un DataFrame vacio con las columnas indicadas.

    Parameters
    ----------
    columns:
        Lista de nombres de columna.

    Returns
    -------
    pd.DataFrame
        DataFrame vacio con las columnas especificadas.
    """
    return pd.DataFrame(columns=columns)


# ---------------------------------------------------------------------------
# Consultas publicas
# ---------------------------------------------------------------------------


def get_publicaciones(
    anio_min: Optional[int] = None,
    anio_max: Optional[int] = None,
    departamento_id: Optional[int] = None,
    profesor_id: Optional[int] = None,
    tipo_documental: Optional[str] = None,
    solo_ventana_rolling: bool = False,
) -> pd.DataFrame:
    """Consulta principal de publicaciones con filtros opcionales.

    Query base: publicacion LEFT JOIN fuente LEFT JOIN fuente_metrica
    (del anio correspondiente a la publicacion).  Si se filtra por
    profesor, se agregan JOINs con ``publicacion_profesor``,
    ``profesor`` y ``departamento`` y se incluyen columnas de profesor.
    Si se filtra solo por departamento, se usa un ``EXISTS`` para
    evitar duplicados.

    Parameters
    ----------
    anio_min:
        Anio minimo de publicacion (inclusive).
    anio_max:
        Anio maximo de publicacion (inclusive).
    departamento_id:
        Filtrar por departamento.
    profesor_id:
        Filtrar por profesor.  Agrega columnas ``id_profesor``,
        ``nombre_normalizado`` y ``nombre_departamento`` al resultado.
    tipo_documental:
        Filtrar por tipo de documento (ej. ``"Article"``).
    solo_ventana_rolling:
        Si ``True``, filtra por la ventana movil de
        ``ROLLING_WINDOW_YEARS`` anios (incluido el actual).

    Returns
    -------
    pd.DataFrame
        Columnas: ``id_publicacion``, ``eid``, ``doi``, ``titulo``,
        ``anio_publicacion``, ``tipo_documental``, ``idioma``,
        ``cited_by_count``, ``open_access``, ``authors_raw``,
        ``indexed_keywords``, ``source_title``, ``issn``,
        ``tipo_fuente``, ``publisher``, ``sjr``, ``citescore``,
        ``snip``, ``cuartil_sjr``.  Si se filtra por profesor,
        agrega ``id_profesor``, ``nombre_normalizado``,
        ``nombre_departamento``.
    """
    add_prof_cols = profesor_id is not None

    # --- SELECT ----------------------------------------------------------
    select = f"""\
    p.id_publicacion, p.eid, p.doi, p.titulo, p.anio_publicacion,
    p.tipo_documental, p.idioma, p.cited_by_count, p.open_access,
    NULL::text AS authors_raw, p.indexed_keywords,
    f.source_title, f.issn, f.tipo_fuente, p.publisher,
    fm.sjr, fm.citescore, fm.snip, fm.cuartil_sjr"""

    if add_prof_cols:
        select += """,
    pr.id_profesor, pr.nombre_normalizado,
    d.nombre AS nombre_departamento"""

    # --- FROM / JOIN -----------------------------------------------------
    from_sql = f"""\
FROM {_S}.publicacion p
LEFT JOIN {_S}.fuente f
    ON p.id_fuente = f.id_fuente
LEFT JOIN {_S}.fuente_metrica fm
    ON f.id_fuente = fm.id_fuente
    AND fm.anio = p.anio_publicacion"""

    if add_prof_cols:
        from_sql += f"""
JOIN {_S}.publicacion_profesor pp
    ON p.id_publicacion = pp.id_publicacion
JOIN {_S}.profesor pr
    ON pp.id_profesor = pr.id_profesor
JOIN {_S}.departamento d
    ON pr.id_departamento = d.id_departamento"""

    # --- WHERE -----------------------------------------------------------
    where: List[str] = []
    params: dict = {}

    if anio_min is not None:
        where.append("p.anio_publicacion >= :anio_min")
        params["anio_min"] = anio_min

    if anio_max is not None:
        where.append("p.anio_publicacion <= :anio_max")
        params["anio_max"] = anio_max

    if solo_ventana_rolling:
        anio_desde = date.today().year - ROLLING_WINDOW_YEARS + 1
        where.append("p.anio_publicacion >= :anio_rolling")
        params["anio_rolling"] = anio_desde

    if tipo_documental is not None:
        where.append("p.tipo_documental = :tipo_doc")
        params["tipo_doc"] = tipo_documental

    if profesor_id is not None:
        where.append("pr.id_profesor = :prof_id")
        params["prof_id"] = profesor_id
        if departamento_id is not None:
            where.append("d.id_departamento = :depto_id")
            params["depto_id"] = departamento_id
    elif departamento_id is not None:
        # Usar EXISTS para evitar duplicados cuando una publicacion
        # tiene multiples profesores del mismo departamento.
        where.append(f"""\
EXISTS (
        SELECT 1
        FROM {_S}.publicacion_profesor pp2
        JOIN {_S}.profesor pr2 ON pp2.id_profesor = pr2.id_profesor
        WHERE pp2.id_publicacion = p.id_publicacion
          AND pr2.id_departamento = :depto_id
    )""")
        params["depto_id"] = departamento_id

    where_sql = ""
    if where:
        where_sql = "\nWHERE " + "\n  AND ".join(where)

    # --- BUILD -----------------------------------------------------------
    sql = (
        f"SELECT {select}\n{from_sql}{where_sql}\n"
        f"ORDER BY p.anio_publicacion DESC, p.id_publicacion"
    )

    expected_cols = (
        _PUB_BASE_COLS + _PUB_PROF_EXTRA if add_prof_cols
        else _PUB_BASE_COLS
    )

    try:
        df = _exec(sql, params)
    except Exception as exc:
        logger.error("Error en get_publicaciones: %s", exc)
        return _empty(expected_cols)

    filtros_desc = params.copy()
    if solo_ventana_rolling:
        filtros_desc["ventana_rolling"] = ROLLING_WINDOW_YEARS
    logger.info(
        "get_publicaciones: %d registros (filtros: %s)",
        len(df), filtros_desc if filtros_desc else "ninguno",
    )
    return df


def get_profesores(
    departamento_id: Optional[int] = None,
    solo_activos: bool = True,
) -> pd.DataFrame:
    """Lista de profesores con datos del departamento.

    Parameters
    ----------
    departamento_id:
        Filtrar por departamento.
    solo_activos:
        Si ``True`` (default), retorna solo profesores activos.

    Returns
    -------
    pd.DataFrame
        Columnas: ``id_profesor``, ``nombre_normalizado``, ``orcid``,
        ``h_index``, ``h_index_fecha``, ``activo``,
        ``id_departamento``, ``nombre_departamento``,
        ``codigo_departamento``.
    """
    cols = [
        "id_profesor", "nombre_normalizado", "orcid", "h_index",
        "h_index_fecha", "activo", "id_departamento",
        "nombre_departamento", "codigo_departamento",
    ]

    where: List[str] = []
    params: dict = {}

    if solo_activos:
        where.append("pr.activo = TRUE")

    if departamento_id is not None:
        where.append("pr.id_departamento = :depto_id")
        params["depto_id"] = departamento_id

    where_sql = ""
    if where:
        where_sql = "\nWHERE " + " AND ".join(where)

    sql = f"""\
SELECT
    pr.id_profesor,
    pr.nombre_normalizado,
    pr.orcid,
    pr.h_index,
    pr.h_index_fecha,
    pr.activo,
    pr.id_departamento,
    d.nombre  AS nombre_departamento,
    d.codigo  AS codigo_departamento
FROM {_S}.profesor pr
JOIN {_S}.departamento d
    ON pr.id_departamento = d.id_departamento{where_sql}
ORDER BY d.nombre, pr.nombre_normalizado"""

    try:
        df = _exec(sql, params)
    except Exception as exc:
        logger.error("Error en get_profesores: %s", exc)
        return _empty(cols)

    logger.info(
        "get_profesores: %d registros (depto=%s, solo_activos=%s)",
        len(df), departamento_id, solo_activos,
    )
    return df


def get_departamentos() -> pd.DataFrame:
    """Lista de departamentos academicos.

    Returns
    -------
    pd.DataFrame
        Columnas: ``id_departamento``, ``nombre``, ``codigo``,
        ``division``.
    """
    cols = ["id_departamento", "nombre", "codigo", "division"]

    sql = f"""\
SELECT id_departamento, nombre, codigo, division
FROM {_S}.departamento
ORDER BY nombre"""

    try:
        df = _exec(sql)
    except Exception as exc:
        logger.error("Error en get_departamentos: %s", exc)
        return _empty(cols)

    logger.info("get_departamentos: %d registros", len(df))
    return df


def get_fuentes(
    con_metricas: bool = False,
    anio_metrica: Optional[int] = None,
) -> pd.DataFrame:
    """Lista de fuentes (revistas), opcionalmente con metricas.

    Parameters
    ----------
    con_metricas:
        Si ``True``, agrega columnas de metricas bibliometricas.
    anio_metrica:
        Anio de las metricas.  Si es ``None`` y ``con_metricas=True``,
        se usa el anio mas reciente disponible para cada fuente
        (subconsulta correlacionada con ``MAX(anio)``).

    Returns
    -------
    pd.DataFrame
        Columnas base: ``id_fuente``, ``source_title``, ``issn``,
        ``tipo_fuente``, ``publisher``.  Con metricas agrega:
        ``sjr``, ``citescore``, ``snip``, ``cuartil_sjr``,
        ``percentil_sjr``.
    """
    base_cols = [
        "id_fuente", "source_title", "issn", "tipo_fuente", "publisher",
    ]
    metric_cols = ["sjr", "citescore", "snip", "cuartil_sjr", "percentil_sjr"]
    expected = base_cols + metric_cols if con_metricas else base_cols

    if not con_metricas:
        sql = f"""\
SELECT id_fuente, source_title, issn, tipo_fuente, publisher
FROM {_S}.fuente
ORDER BY source_title"""
        params: dict = {}
    elif anio_metrica is not None:
        # Metricas de un anio especifico
        sql = f"""\
SELECT
    f.id_fuente, f.source_title, f.issn, f.tipo_fuente, f.publisher,
    fm.sjr, fm.citescore, fm.snip, fm.cuartil_sjr, fm.percentil_sjr
FROM {_S}.fuente f
LEFT JOIN {_S}.fuente_metrica fm
    ON f.id_fuente = fm.id_fuente
    AND fm.anio = :anio
ORDER BY f.source_title"""
        params = {"anio": anio_metrica}
    else:
        # Metricas del anio mas reciente por fuente
        sql = f"""\
SELECT
    f.id_fuente, f.source_title, f.issn, f.tipo_fuente, f.publisher,
    fm.sjr, fm.citescore, fm.snip, fm.cuartil_sjr, fm.percentil_sjr
FROM {_S}.fuente f
LEFT JOIN {_S}.fuente_metrica fm
    ON f.id_fuente = fm.id_fuente
    AND fm.anio = (
        SELECT MAX(fm2.anio)
        FROM {_S}.fuente_metrica fm2
        WHERE fm2.id_fuente = f.id_fuente
    )
ORDER BY f.source_title"""
        params = {}

    try:
        df = _exec(sql, params)
    except Exception as exc:
        logger.error("Error en get_fuentes: %s", exc)
        return _empty(expected)

    logger.info(
        "get_fuentes: %d registros (con_metricas=%s, anio=%s)",
        len(df), con_metricas, anio_metrica,
    )
    return df


def get_publicaciones_por_profesor(profesor_id: int) -> pd.DataFrame:
    """Todas las publicaciones de un profesor, con fuente y metricas.

    Wrapper de :func:`get_publicaciones` con filtro por profesor.

    Parameters
    ----------
    profesor_id:
        ID del profesor.

    Returns
    -------
    pd.DataFrame
        Mismas columnas que :func:`get_publicaciones` con columnas
        de profesor incluidas.
    """
    return get_publicaciones(profesor_id=profesor_id)


def get_top_fuentes(
    n: int = 10,
    departamento_id: Optional[int] = None,
    profesor_id: Optional[int] = None,
) -> pd.DataFrame:
    """Top N fuentes (revistas) donde mas se publica.

    Cuenta publicaciones por ``source_title`` y agrega las metricas
    del anio mas reciente disponible para cada fuente (subconsulta
    correlacionada).

    Parameters
    ----------
    n:
        Cantidad de fuentes a retornar (default 10).
    departamento_id:
        Filtrar publicaciones por departamento.
    profesor_id:
        Filtrar publicaciones por profesor.

    Returns
    -------
    pd.DataFrame
        Columnas: ``source_title``, ``issn``, ``publicaciones_count``,
        ``proporcion``, ``sjr``, ``cuartil_sjr``.
    """
    cols = [
        "source_title", "issn", "publicaciones_count",
        "proporcion", "sjr", "cuartil_sjr",
    ]

    # --- Filtro por departamento/profesor --------------------------------
    filter_join = ""
    where: List[str] = ["p.id_fuente IS NOT NULL"]
    params: dict = {"top_n": n}

    if profesor_id is not None:
        filter_join = f"""\
JOIN {_S}.publicacion_profesor pp
    ON p.id_publicacion = pp.id_publicacion"""
        where.append("pp.id_profesor = :prof_id")
        params["prof_id"] = profesor_id
    elif departamento_id is not None:
        filter_join = f"""\
JOIN {_S}.publicacion_profesor pp
    ON p.id_publicacion = pp.id_publicacion
JOIN {_S}.profesor pr
    ON pp.id_profesor = pr.id_profesor"""
        where.append("pr.id_departamento = :depto_id")
        params["depto_id"] = departamento_id

    where_sql = "\nWHERE " + " AND ".join(where)

    sql = f"""\
WITH conteo AS (
    SELECT
        f.id_fuente,
        f.source_title,
        f.issn,
        COUNT(DISTINCT p.id_publicacion) AS publicaciones_count
    FROM {_S}.publicacion p
    JOIN {_S}.fuente f
        ON p.id_fuente = f.id_fuente
    {filter_join}{where_sql}
    GROUP BY f.id_fuente, f.source_title, f.issn
    ORDER BY publicaciones_count DESC
    LIMIT :top_n
)
SELECT
    c.source_title,
    c.issn,
    c.publicaciones_count,
    fm.sjr,
    fm.cuartil_sjr
FROM conteo c
LEFT JOIN {_S}.fuente_metrica fm
    ON fm.id_fuente = c.id_fuente
    AND fm.anio = (
        SELECT MAX(fm2.anio)
        FROM {_S}.fuente_metrica fm2
        WHERE fm2.id_fuente = c.id_fuente
    )
ORDER BY c.publicaciones_count DESC"""

    try:
        df = _exec(sql, params)
    except Exception as exc:
        logger.error("Error en get_top_fuentes: %s", exc)
        return _empty(cols)

    # Calcular proporcion sobre el total retornado
    total = int(df["publicaciones_count"].sum()) if not df.empty else 0
    df["proporcion"] = (
        df["publicaciones_count"] / total if total > 0 else 0.0
    )

    logger.info(
        "get_top_fuentes: %d fuentes (top %d, depto=%s, prof=%s)",
        len(df), n, departamento_id, profesor_id,
    )
    return df


def get_keywords_summary(
    anio_min: Optional[int] = None,
    anio_max: Optional[int] = None,
    departamento_id: Optional[int] = None,
    top_n: int = 20,
) -> pd.DataFrame:
    """Resumen de indexed keywords mas frecuentes.

    Trae las publicaciones filtradas, splitea el campo
    ``indexed_keywords`` por ``";"`` y cuenta la frecuencia de
    cada keyword.

    Parameters
    ----------
    anio_min:
        Anio minimo (inclusive).
    anio_max:
        Anio maximo (inclusive).
    departamento_id:
        Filtrar por departamento.
    top_n:
        Cantidad de keywords a retornar (default 20).

    Returns
    -------
    pd.DataFrame
        Columnas: ``keyword``, ``frecuencia``, ``proporcion``.
    """
    cols = ["keyword", "frecuencia", "proporcion"]

    # Traer solo indexed_keywords de publicaciones filtradas
    where: List[str] = ["p.indexed_keywords IS NOT NULL"]
    params: dict = {}

    if anio_min is not None:
        where.append("p.anio_publicacion >= :anio_min")
        params["anio_min"] = anio_min

    if anio_max is not None:
        where.append("p.anio_publicacion <= :anio_max")
        params["anio_max"] = anio_max

    filter_join = ""
    if departamento_id is not None:
        filter_join = f"""\
JOIN {_S}.publicacion_profesor pp
    ON p.id_publicacion = pp.id_publicacion
JOIN {_S}.profesor pr
    ON pp.id_profesor = pr.id_profesor"""
        where.append("pr.id_departamento = :depto_id")
        params["depto_id"] = departamento_id

    where_sql = "\nWHERE " + " AND ".join(where)

    sql = f"""\
SELECT DISTINCT p.id_publicacion, p.indexed_keywords
FROM {_S}.publicacion p
{filter_join}{where_sql}"""

    try:
        df_raw = _exec(sql, params)
    except Exception as exc:
        logger.error("Error en get_keywords_summary: %s", exc)
        return _empty(cols)

    if df_raw.empty:
        logger.info("get_keywords_summary: 0 keywords (sin datos)")
        return _empty(cols)

    # Splitear por ";" y contar
    counter: Counter = Counter()
    for kw_str in df_raw["indexed_keywords"].dropna():
        keywords = [k.strip() for k in str(kw_str).split(";") if k.strip()]
        counter.update(keywords)

    if not counter:
        return _empty(cols)

    top_items = counter.most_common(top_n)
    total = sum(counter.values())

    df = pd.DataFrame(top_items, columns=["keyword", "frecuencia"])
    df["proporcion"] = df["frecuencia"] / total if total > 0 else 0.0

    logger.info(
        "get_keywords_summary: %d keywords unicas, retornando top %d "
        "(filtros: %s)",
        len(counter), len(df), params if params else "ninguno",
    )
    return df


def get_evolucion_anual(
    departamento_id: Optional[int] = None,
    profesor_id: Optional[int] = None,
) -> pd.DataFrame:
    """Serie temporal de publicaciones y citas por anio.

    Recupera las publicaciones individuales y agrega en Python
    para calcular conteo, suma, promedio y mediana de citas por anio.

    Parameters
    ----------
    departamento_id:
        Filtrar por departamento.  Agrega columna
        ``nombre_departamento`` al resultado.
    profesor_id:
        Filtrar por profesor.

    Returns
    -------
    pd.DataFrame
        Columnas: ``anio``, ``publicaciones``, ``citas_totales``,
        ``citas_promedio``, ``citas_mediana``.
        Si ``departamento_id`` esta definido, agrega
        ``nombre_departamento``.
    """
    add_depto = departamento_id is not None
    base_cols = [
        "anio", "publicaciones", "citas_totales",
        "citas_promedio", "citas_mediana",
    ]
    expected = base_cols + ["nombre_departamento"] if add_depto else base_cols

    # --- SELECT / FROM ---------------------------------------------------
    extra_select = ""
    if add_depto:
        extra_select = ", d.nombre AS nombre_departamento"

    filter_join = ""
    where: List[str] = []
    params: dict = {}

    if profesor_id is not None:
        filter_join = f"""\
JOIN {_S}.publicacion_profesor pp
    ON p.id_publicacion = pp.id_publicacion"""
        where.append("pp.id_profesor = :prof_id")
        params["prof_id"] = profesor_id
    elif departamento_id is not None:
        filter_join = f"""\
JOIN {_S}.publicacion_profesor pp
    ON p.id_publicacion = pp.id_publicacion
JOIN {_S}.profesor pr
    ON pp.id_profesor = pr.id_profesor
JOIN {_S}.departamento d
    ON pr.id_departamento = d.id_departamento"""
        where.append("d.id_departamento = :depto_id")
        params["depto_id"] = departamento_id

    where_sql = ""
    if where:
        where_sql = "\nWHERE " + " AND ".join(where)

    # Traer registros individuales (DISTINCT evita duplicados por
    # multiples profesores del mismo departamento).
    sql = f"""\
SELECT DISTINCT
    p.id_publicacion,
    p.anio_publicacion AS anio,
    p.cited_by_count{extra_select}
FROM {_S}.publicacion p
{filter_join}{where_sql}
ORDER BY p.anio_publicacion"""

    try:
        df_raw = _exec(sql, params)
    except Exception as exc:
        logger.error("Error en get_evolucion_anual: %s", exc)
        return _empty(expected)

    if df_raw.empty:
        logger.info("get_evolucion_anual: sin datos")
        return _empty(expected)

    # --- Agregar en Python -----------------------------------------------
    group_cols = ["anio"]
    if add_depto:
        group_cols.append("nombre_departamento")

    grouped = (
        df_raw
        .groupby(group_cols)
        .agg(
            publicaciones=("id_publicacion", "nunique"),
            citas_totales=("cited_by_count", "sum"),
            citas_promedio=("cited_by_count", "mean"),
            citas_mediana=("cited_by_count", "median"),
        )
        .reset_index()
    )
    grouped["citas_promedio"] = grouped["citas_promedio"].round(2)
    grouped["citas_mediana"] = grouped["citas_mediana"].round(2)
    grouped = grouped.sort_values("anio").reset_index(drop=True)

    logger.info(
        "get_evolucion_anual: %d anios (depto=%s, prof=%s)",
        len(grouped), departamento_id, profesor_id,
    )
    return grouped


def get_distribucion_cuartiles(
    departamento_id: Optional[int] = None,
    profesor_id: Optional[int] = None,
) -> pd.DataFrame:
    """Distribucion de publicaciones por cuartil SJR.

    Cruza publicaciones con ``fuente_metrica`` del anio
    correspondiente y cuenta por cuartil (Q1, Q2, Q3, Q4 o
    ``Sin dato``).

    Parameters
    ----------
    departamento_id:
        Filtrar por departamento.
    profesor_id:
        Filtrar por profesor.

    Returns
    -------
    pd.DataFrame
        Columnas: ``cuartil``, ``count``, ``proporcion``.
    """
    cols = ["cuartil", "count", "proporcion"]

    # --- Filtros ---------------------------------------------------------
    filter_join = ""
    where: List[str] = []
    params: dict = {}

    if profesor_id is not None:
        filter_join = f"""\
JOIN {_S}.publicacion_profesor pp
    ON p.id_publicacion = pp.id_publicacion"""
        where.append("pp.id_profesor = :prof_id")
        params["prof_id"] = profesor_id
    elif departamento_id is not None:
        filter_join = f"""\
JOIN {_S}.publicacion_profesor pp
    ON p.id_publicacion = pp.id_publicacion
JOIN {_S}.profesor pr
    ON pp.id_profesor = pr.id_profesor"""
        where.append("pr.id_departamento = :depto_id")
        params["depto_id"] = departamento_id

    where_sql = ""
    if where:
        where_sql = "\nWHERE " + " AND ".join(where)

    sql = f"""\
SELECT
    COALESCE(fm.cuartil_sjr, 'Sin dato') AS cuartil,
    COUNT(DISTINCT p.id_publicacion) AS count
FROM {_S}.publicacion p
LEFT JOIN {_S}.fuente f
    ON p.id_fuente = f.id_fuente
LEFT JOIN {_S}.fuente_metrica fm
    ON f.id_fuente = fm.id_fuente
    AND fm.anio = p.anio_publicacion
{filter_join}{where_sql}
GROUP BY COALESCE(fm.cuartil_sjr, 'Sin dato')
ORDER BY cuartil"""

    try:
        df = _exec(sql, params)
    except Exception as exc:
        logger.error("Error en get_distribucion_cuartiles: %s", exc)
        return _empty(cols)

    # Calcular proporcion
    total = int(df["count"].sum()) if not df.empty else 0
    df["proporcion"] = df["count"] / total if total > 0 else 0.0

    logger.info(
        "get_distribucion_cuartiles: %d categorias (depto=%s, prof=%s)",
        len(df), departamento_id, profesor_id,
    )
    return df


def get_coautoria_entre_profesores(
    departamento_id: Optional[int] = None,
) -> pd.DataFrame:
    """Pares de profesores que co-publicaron dentro de la División.

    Returns
    -------
    pd.DataFrame
        Columnas: ``id_prof_a``, ``id_prof_b``, ``n_copubs``.
    """
    cols = ["id_prof_a", "id_prof_b", "n_copubs"]

    dept_filter = ""
    params: dict = {}

    if departamento_id is not None:
        dept_filter = f"""
JOIN {_S}.profesor pr_f ON pp1.id_profesor = pr_f.id_profesor
WHERE pr_f.id_departamento = :depto_id"""
        params["depto_id"] = departamento_id

    sql = f"""\
SELECT
    pp1.id_profesor AS id_prof_a,
    pp2.id_profesor AS id_prof_b,
    COUNT(DISTINCT pp1.id_publicacion) AS n_copubs
FROM {_S}.publicacion_profesor pp1
JOIN {_S}.publicacion_profesor pp2
    ON pp1.id_publicacion = pp2.id_publicacion
    AND pp1.id_profesor < pp2.id_profesor
{dept_filter}
GROUP BY pp1.id_profesor, pp2.id_profesor
HAVING COUNT(DISTINCT pp1.id_publicacion) >= 1
ORDER BY n_copubs DESC"""

    try:
        df = _exec(sql, params)
    except Exception as exc:
        logger.error("Error en get_coautoria_entre_profesores: %s", exc)
        return _empty(cols)

    logger.info("get_coautoria_entre_profesores: %d pares", len(df))
    return df


def get_calidad_matching() -> pd.DataFrame:
    """Calidad del matching: perfil Scopus vs publicaciones extraídas.

    Compara ``SUM(autor_scopus.numero_documentos_scopus)`` con
    el conteo real de publicaciones vinculadas en ``publicacion_profesor``.

    Returns
    -------
    pd.DataFrame
        Columnas: ``nombre_normalizado``, ``orcid``, ``departamento``,
        ``pubs_perfil``, ``pubs_extraidas``, ``diferencia``,
        ``cobertura``, ``estado``, ``accion``.
    """
    cols = [
        "nombre_normalizado", "orcid", "departamento",
        "pubs_perfil", "pubs_extraidas", "diferencia",
        "cobertura", "estado", "accion",
    ]

    sql = f"""\
SELECT
    pr.nombre_normalizado,
    pr.orcid,
    d.codigo AS departamento,
    COALESCE((
        SELECT SUM(au.numero_documentos_scopus)
        FROM {_S}.autor_scopus au
        WHERE au.id_profesor = pr.id_profesor
          AND au.numero_documentos_scopus IS NOT NULL
    ), 0) AS pubs_perfil,
    COUNT(DISTINCT pp.id_publicacion) AS pubs_extraidas
FROM {_S}.profesor pr
JOIN {_S}.departamento d ON pr.id_departamento = d.id_departamento
LEFT JOIN {_S}.publicacion_profesor pp ON pp.id_profesor = pr.id_profesor
GROUP BY pr.id_profesor, pr.nombre_normalizado, pr.orcid, d.codigo
ORDER BY pr.nombre_normalizado"""

    try:
        df = _exec(sql)
    except Exception as exc:
        logger.error("Error en get_calidad_matching: %s", exc)
        return _empty(cols)

    if df.empty:
        return _empty(cols)

    df["pubs_perfil"]   = pd.to_numeric(df["pubs_perfil"],   errors="coerce").fillna(0).astype(int)
    df["pubs_extraidas"]= pd.to_numeric(df["pubs_extraidas"],errors="coerce").fillna(0).astype(int)
    df["diferencia"]    = df["pubs_extraidas"] - df["pubs_perfil"]

    def _cobertura(row):
        perfil = row["pubs_perfil"]
        ext    = row["pubs_extraidas"]
        if perfil == 0:
            return 1.0 if ext > 0 else 0.0
        return min(1.0, ext / perfil)

    def _estado(row):
        cob = row["cobertura"]
        if cob >= 0.70:  return "OK"
        if cob >= 0.30:  return "REVISAR"
        return "CRITICO"

    def _accion(row):
        if row["estado"] == "OK":
            return "Sin acción requerida"
        if row["pubs_extraidas"] == 0:
            return "Verificar Auth_ID en CSV de profesores"
        return "Revisar perfiles Scopus y Auth_IDs asociados"

    df["cobertura"] = df.apply(_cobertura, axis=1)
    df["estado"]    = df.apply(_estado, axis=1)
    df["accion"]    = df.apply(_accion, axis=1)

    logger.info(
        "get_calidad_matching: %d profesores, %d OK, %d REVISAR, %d CRITICO",
        len(df),
        (df["estado"] == "OK").sum(),
        (df["estado"] == "REVISAR").sum(),
        (df["estado"] == "CRITICO").sum(),
    )
    return df
