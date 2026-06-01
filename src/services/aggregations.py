"""
Agregaciones de datos por profesor, departamento y Division.

Modulo de alto nivel que combina ``queries.py`` (acceso a datos) y
``metrics.py`` (calculos puros) para producir las tablas y KPIs que
el dashboard Dash consumira directamente.

Principio de diseno
-------------------
Cada funcion consulta la BD (via ``queries``), aplica calculos (via
``metrics``) y retorna un ``dict`` o ``pd.DataFrame`` listo para
visualizar.  Estas son las funciones de mas alto nivel que el
dashboard llamara.

Niveles de agregacion (segun Propuesta Seminario):

- **Profesor**: perfil individual completo (Tab 2).
- **Departamento**: resumen con ranking de profesores.
- **Division**: vision global comparativa (Tab 1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config.settings import ROLLING_WINDOW_YEARS
from src.services import metrics, queries
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _safe_h_index(value: object) -> Optional[int]:
    """Convierte un valor de h_index a int o None.

    Maneja NaN, None y valores numericos de forma segura.

    Parameters
    ----------
    value:
        Valor crudo del h_index (puede ser int, float, NaN, None).

    Returns
    -------
    int or None
        h_index como entero, o ``None`` si no disponible.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def _proporcion_q1(df_pubs: pd.DataFrame) -> float:
    """Calcula la proporcion de publicaciones en cuartil Q1.

    Parameters
    ----------
    df_pubs:
        DataFrame de publicaciones con columna ``cuartil_sjr``.

    Returns
    -------
    float
        Proporcion de publicaciones Q1 (0.0 a 1.0).
    """
    if df_pubs.empty:
        return 0.0
    n = len(df_pubs)
    q1 = int((df_pubs["cuartil_sjr"] == "Q1").sum())
    return round(q1 / n, 4) if n > 0 else 0.0


# ---------------------------------------------------------------------------
# Nivel 1: Profesor
# ---------------------------------------------------------------------------


def perfil_profesor(profesor_id: int) -> dict:
    """Genera el perfil completo de un profesor para el Tab 2 del dashboard.

    Consulta datos del profesor, sus publicaciones y calcula todos los
    KPIs e indicadores requeridos por la Propuesta Seminario.

    Parameters
    ----------
    profesor_id:
        ID del profesor en la base de datos.

    Returns
    -------
    dict
        Claves:

        - ``info`` (dict): datos del profesor (nombre, orcid,
          departamento, h_index).
        - ``kpis`` (dict): KPIs generados por
          :func:`~src.services.metrics.generar_kpis_resumen`.
        - ``publicaciones`` (pd.DataFrame): publicaciones del profesor.
        - ``top_fuentes`` (pd.DataFrame): top fuentes donde publica.
        - ``distribucion_tipos`` (pd.DataFrame): distribucion por tipo
          documental.
        - ``distribucion_cuartiles`` (pd.DataFrame): distribucion por
          cuartil SJR.
        - ``evolucion_anual`` (pd.DataFrame): citas por anio.

    Example
    -------
    >>> perfil = perfil_profesor(42)
    >>> perfil["info"]["nombre"]
    'Garcia Lopez, Juan Carlos'
    >>> perfil["kpis"]["total_publicaciones"]
    35
    """
    logger.info("perfil_profesor: generando perfil para id=%d", profesor_id)

    # --- Datos del profesor ------------------------------------------------
    df_profesores = queries.get_profesores()
    prof_row = df_profesores[
        df_profesores["id_profesor"] == profesor_id
    ]

    if prof_row.empty:
        logger.warning(
            "perfil_profesor: profesor id=%d no encontrado", profesor_id,
        )
        info: Dict[str, object] = {
            "nombre": "No encontrado",
            "orcid": None,
            "departamento": None,
            "h_index": None,
            "id_profesor": profesor_id,
        }
    else:
        row = prof_row.iloc[0]
        info = {
            "nombre": row.get("nombre_normalizado", ""),
            "orcid": row.get("orcid"),
            "departamento": row.get("nombre_departamento", ""),
            "h_index": _safe_h_index(row.get("h_index")),
            "id_profesor": profesor_id,
        }

    # --- Publicaciones -----------------------------------------------------
    df_pubs = queries.get_publicaciones(profesor_id=profesor_id)

    # --- KPIs --------------------------------------------------------------
    kpis = metrics.generar_kpis_resumen(df_pubs, h_index=info["h_index"])

    # --- Tablas auxiliares --------------------------------------------------
    top_fuentes = queries.get_top_fuentes(profesor_id=profesor_id)
    dist_tipos = metrics.calcular_distribucion_tipos(df_pubs)
    dist_cuartiles = metrics.calcular_distribucion_cuartiles(df_pubs)
    evolucion = metrics.calcular_citas_por_anio(df_pubs)

    resultado = {
        "info": info,
        "kpis": kpis,
        "publicaciones": df_pubs,
        "top_fuentes": top_fuentes,
        "distribucion_tipos": dist_tipos,
        "distribucion_cuartiles": dist_cuartiles,
        "evolucion_anual": evolucion,
    }

    logger.info(
        "perfil_profesor: id=%d, pubs=%d, h_index=%s",
        profesor_id, len(df_pubs), info["h_index"],
    )
    return resultado


# ---------------------------------------------------------------------------
# Nivel 2: Departamento
# ---------------------------------------------------------------------------


def resumen_departamento(departamento_id: int) -> dict:
    """Genera el resumen de un departamento.

    Incluye KPIs agregados, ranking de profesores y distribuciones
    para visualizacion en el dashboard.

    Parameters
    ----------
    departamento_id:
        ID del departamento.

    Returns
    -------
    dict
        Claves:

        - ``info`` (dict): datos del departamento (nombre, cantidad
          de profesores).
        - ``kpis`` (dict): KPIs agregados del departamento.
        - ``ranking_profesores`` (pd.DataFrame): ranking con
          publicaciones, citas, h_index por profesor.
        - ``top_fuentes`` (pd.DataFrame): top fuentes del departamento.
        - ``distribucion_tipos`` (pd.DataFrame).
        - ``distribucion_cuartiles`` (pd.DataFrame).
        - ``evolucion_anual`` (pd.DataFrame).
    """
    logger.info(
        "resumen_departamento: generando resumen para depto_id=%d",
        departamento_id,
    )

    # --- Profesores del departamento ---------------------------------------
    df_profesores = queries.get_profesores(departamento_id=departamento_id)

    # --- Info departamento -------------------------------------------------
    df_deptos = queries.get_departamentos()
    depto_row = df_deptos[
        df_deptos["id_departamento"] == departamento_id
    ]

    depto_nombre = (
        depto_row.iloc[0]["nombre"] if not depto_row.empty else "Desconocido"
    )

    info = {
        "nombre": depto_nombre,
        "cantidad_profesores": len(df_profesores),
        "id_departamento": departamento_id,
    }

    # --- Publicaciones del departamento ------------------------------------
    df_pubs = queries.get_publicaciones(departamento_id=departamento_id)

    # --- KPIs agregados ----------------------------------------------------
    h_values = df_profesores["h_index"].dropna()
    h_index_promedio = (
        round(float(h_values.mean()), 1) if not h_values.empty else None
    )

    kpis = metrics.generar_kpis_resumen(df_pubs, h_index=h_index_promedio)

    # --- Ranking de profesores ---------------------------------------------
    ranking = _build_ranking_profesores(df_profesores, departamento_id)

    # --- Tablas auxiliares --------------------------------------------------
    top_fuentes = queries.get_top_fuentes(departamento_id=departamento_id)
    dist_tipos = metrics.calcular_distribucion_tipos(df_pubs)
    dist_cuartiles = metrics.calcular_distribucion_cuartiles(df_pubs)
    evolucion = queries.get_evolucion_anual(departamento_id=departamento_id)

    resultado = {
        "info": info,
        "kpis": kpis,
        "ranking_profesores": ranking,
        "top_fuentes": top_fuentes,
        "distribucion_tipos": dist_tipos,
        "distribucion_cuartiles": dist_cuartiles,
        "evolucion_anual": evolucion,
    }

    logger.info(
        "resumen_departamento: depto=%s, profesores=%d, pubs=%d",
        depto_nombre, len(df_profesores), len(df_pubs),
    )
    return resultado


def _build_ranking_profesores(
    df_profesores: pd.DataFrame,
    departamento_id: int,
) -> pd.DataFrame:
    """Construye el ranking de profesores de un departamento.

    Para cada profesor calcula publicaciones totales, publicaciones
    ultimos 3 anios, citas totales y h_index.  Ordena por
    publicaciones de los ultimos 3 anios descendente.

    Parameters
    ----------
    df_profesores:
        DataFrame de profesores del departamento (de
        ``queries.get_profesores``).
    departamento_id:
        ID del departamento (para logging).

    Returns
    -------
    pd.DataFrame
        Columnas: ``nombre_normalizado``, ``publicaciones_total``,
        ``publicaciones_3_anios``, ``citas_totales``, ``h_index``,
        ``orcid``.
    """
    cols = [
        "nombre_normalizado", "publicaciones_total",
        "publicaciones_3_anios", "citas_totales", "h_index", "orcid",
    ]

    if df_profesores.empty:
        return pd.DataFrame(columns=cols)

    filas: List[dict] = []
    for _, prof in df_profesores.iterrows():
        pid = int(prof["id_profesor"])
        df_pubs = queries.get_publicaciones(profesor_id=pid)

        filas.append({
            "nombre_normalizado": prof["nombre_normalizado"],
            "publicaciones_total": metrics.contar_publicaciones(df_pubs),
            "publicaciones_3_anios": metrics.contar_publicaciones_ventana(
                df_pubs,
            ),
            "citas_totales": int(
                df_pubs["cited_by_count"].fillna(0).sum()
            ) if not df_pubs.empty else 0,
            "h_index": _safe_h_index(prof.get("h_index")),
            "orcid": prof.get("orcid"),
        })

    ranking = pd.DataFrame(filas, columns=cols)
    ranking = ranking.sort_values(
        "publicaciones_3_anios", ascending=False,
    ).reset_index(drop=True)

    logger.debug(
        "_build_ranking_profesores: %d profesores (depto_id=%d)",
        len(ranking), departamento_id,
    )
    return ranking


# ---------------------------------------------------------------------------
# Nivel 3: Division (global)
# ---------------------------------------------------------------------------


def resumen_division() -> dict:
    """Genera el resumen de toda la Division (Tab 1 del dashboard).

    Incluye KPIs globales, tabla comparativa de departamentos,
    evolucion temporal por departamento y distribuciones globales.

    Returns
    -------
    dict
        Claves:

        - ``kpis`` (dict): KPIs globales de toda la Division.
        - ``tabla_departamentos`` (pd.DataFrame): comparativa con
          publicaciones, citas, profesores, h_index, SJR por depto.
        - ``evolucion_por_departamento`` (pd.DataFrame): serie temporal
          por departamento (formato largo).
        - ``distribucion_tipos`` (pd.DataFrame): distribucion global.
        - ``distribucion_cuartiles`` (pd.DataFrame): distribucion
          global.
        - ``top_fuentes`` (pd.DataFrame): top fuentes de la Division.
    """
    logger.info("resumen_division: generando resumen global")

    # --- Publicaciones globales --------------------------------------------
    df_pubs = queries.get_publicaciones()

    # --- KPIs globales -----------------------------------------------------
    df_todos_prof = queries.get_profesores()
    h_values = df_todos_prof["h_index"].dropna()
    h_index_promedio = (
        round(float(h_values.mean()), 1) if not h_values.empty else None
    )

    kpis = metrics.generar_kpis_resumen(df_pubs, h_index=h_index_promedio)

    # --- Tabla comparativa de departamentos --------------------------------
    tabla_deptos = _build_tabla_departamentos(df_todos_prof)

    # --- Evolucion por departamento ----------------------------------------
    evolucion = _build_evolucion_por_departamento(df_todos_prof)

    # --- Distribuciones globales -------------------------------------------
    dist_tipos = metrics.calcular_distribucion_tipos(df_pubs)
    dist_cuartiles = metrics.calcular_distribucion_cuartiles(df_pubs)
    top_fuentes = queries.get_top_fuentes()

    resultado = {
        "kpis": kpis,
        "tabla_departamentos": tabla_deptos,
        "evolucion_por_departamento": evolucion,
        "distribucion_tipos": dist_tipos,
        "distribucion_cuartiles": dist_cuartiles,
        "top_fuentes": top_fuentes,
    }

    logger.info(
        "resumen_division: pubs=%d, deptos=%d",
        len(df_pubs), len(tabla_deptos),
    )
    return resultado


def _build_tabla_departamentos(
    df_todos_prof: pd.DataFrame,
) -> pd.DataFrame:
    """Construye la tabla comparativa de departamentos.

    Para cada departamento calcula: publicaciones totales,
    publicaciones ultimos 3 anios, citas totales, cantidad de
    profesores, h_index promedio y SJR promedio.

    Parameters
    ----------
    df_todos_prof:
        DataFrame de todos los profesores (de
        ``queries.get_profesores``).

    Returns
    -------
    pd.DataFrame
        Columnas: ``nombre_departamento``, ``profesores``,
        ``publicaciones_total``, ``publicaciones_3_anios``,
        ``citas_totales``, ``h_index_promedio``, ``sjr_promedio``.
        Ordenado por publicaciones_3_anios descendente.
    """
    cols = [
        "nombre_departamento", "profesores", "publicaciones_total",
        "publicaciones_3_anios", "citas_totales",
        "h_index_promedio", "sjr_promedio",
    ]

    if df_todos_prof.empty:
        return pd.DataFrame(columns=cols)

    deptos = df_todos_prof.groupby("id_departamento").first()[
        ["nombre_departamento"]
    ].reset_index()

    filas: List[dict] = []
    for _, depto in deptos.iterrows():
        did = int(depto["id_departamento"])
        nombre = depto["nombre_departamento"]

        profs_depto = df_todos_prof[
            df_todos_prof["id_departamento"] == did
        ]
        df_pubs = queries.get_publicaciones(departamento_id=did)

        h_vals = profs_depto["h_index"].dropna()
        sjr_mean = metrics.calcular_metricas_fuente_promedio(df_pubs)

        filas.append({
            "nombre_departamento": nombre,
            "profesores": len(profs_depto),
            "publicaciones_total": metrics.contar_publicaciones(df_pubs),
            "publicaciones_3_anios": metrics.contar_publicaciones_ventana(
                df_pubs,
            ),
            "citas_totales": int(
                df_pubs["cited_by_count"].fillna(0).sum()
            ) if not df_pubs.empty else 0,
            "h_index_promedio": round(float(h_vals.mean()), 1)
            if not h_vals.empty else None,
            "sjr_promedio": sjr_mean["sjr_promedio"],
        })

    tabla = pd.DataFrame(filas, columns=cols)
    tabla = tabla.sort_values(
        "publicaciones_3_anios", ascending=False,
    ).reset_index(drop=True)

    return tabla


def _build_evolucion_por_departamento(
    df_todos_prof: pd.DataFrame,
) -> pd.DataFrame:
    """Construye la evolucion temporal por departamento.

    Usa ``queries.get_evolucion_anual`` para cada departamento y
    concatena los resultados en formato largo.

    Parameters
    ----------
    df_todos_prof:
        DataFrame de todos los profesores (para extraer IDs de
        departamento unicos).

    Returns
    -------
    pd.DataFrame
        Columnas: ``anio``, ``nombre_departamento``, ``publicaciones``,
        ``citas_totales``.  Formato largo listo para Plotly.
    """
    cols = [
        "anio", "nombre_departamento", "publicaciones", "citas_totales",
    ]

    if df_todos_prof.empty:
        return pd.DataFrame(columns=cols)

    depto_ids = df_todos_prof["id_departamento"].dropna().unique()
    partes: List[pd.DataFrame] = []

    for did in depto_ids:
        did = int(did)
        evol = queries.get_evolucion_anual(departamento_id=did)
        if not evol.empty:
            partes.append(
                evol[
                    [c for c in cols if c in evol.columns]
                ]
            )

    if not partes:
        return pd.DataFrame(columns=cols)

    resultado = pd.concat(partes, ignore_index=True)
    resultado = resultado.sort_values(
        ["anio", "nombre_departamento"],
    ).reset_index(drop=True)

    return resultado


# ---------------------------------------------------------------------------
# Tablas transversales
# ---------------------------------------------------------------------------


def tabla_comparativa_profesores(
    departamento_id: Optional[int] = None,
) -> pd.DataFrame:
    """Tabla completa de profesores con sus metricas para ranking.

    Para cada profesor calcula publicaciones, citas, h_index, SJR
    promedio y proporcion en Q1.  Pensada para comparacion y ranking
    en el dashboard.

    Parameters
    ----------
    departamento_id:
        Si se proporciona, filtra por departamento.  Si es ``None``,
        incluye todos los profesores.

    Returns
    -------
    pd.DataFrame
        Columnas: ``nombre_normalizado``, ``departamento``,
        ``publicaciones_total``, ``publicaciones_3_anios``,
        ``citas_totales``, ``citas_promedio``, ``h_index``,
        ``sjr_promedio``, ``proporcion_q1``, ``orcid``.
        Ordenado por publicaciones_3_anios descendente.

    Example
    -------
    >>> df = tabla_comparativa_profesores(departamento_id=3)
    >>> df.columns.tolist()
    ['nombre_normalizado', 'departamento', 'publicaciones_total', ...]
    """
    cols = [
        "nombre_normalizado", "departamento", "publicaciones_total",
        "publicaciones_3_anios", "citas_totales", "citas_promedio",
        "h_index", "sjr_promedio", "proporcion_q1", "orcid",
    ]

    logger.info(
        "tabla_comparativa_profesores: depto_id=%s", departamento_id,
    )

    df_profesores = queries.get_profesores(
        departamento_id=departamento_id,
    )

    if df_profesores.empty:
        return pd.DataFrame(columns=cols)

    filas: List[dict] = []
    for _, prof in df_profesores.iterrows():
        pid = int(prof["id_profesor"])
        df_pubs = queries.get_publicaciones(profesor_id=pid)

        citas = df_pubs["cited_by_count"].fillna(0) if not df_pubs.empty \
            else pd.Series(dtype=float)

        sjr_stats = metrics.calcular_metricas_fuente_promedio(df_pubs)

        filas.append({
            "nombre_normalizado": prof["nombre_normalizado"],
            "departamento": prof.get("nombre_departamento", ""),
            "publicaciones_total": metrics.contar_publicaciones(df_pubs),
            "publicaciones_3_anios": metrics.contar_publicaciones_ventana(
                df_pubs,
            ),
            "citas_totales": int(citas.sum()) if len(citas) > 0 else 0,
            "citas_promedio": round(float(citas.mean()), 2)
            if len(citas) > 0 else 0.0,
            "h_index": _safe_h_index(prof.get("h_index")),
            "sjr_promedio": sjr_stats["sjr_promedio"],
            "proporcion_q1": _proporcion_q1(df_pubs),
            "orcid": prof.get("orcid"),
        })

    tabla = pd.DataFrame(filas, columns=cols)
    tabla = tabla.sort_values(
        "publicaciones_3_anios", ascending=False,
    ).reset_index(drop=True)

    logger.info(
        "tabla_comparativa_profesores: %d profesores",
        len(tabla),
    )
    return tabla


def evolucion_temporal_comparativa() -> pd.DataFrame:
    """Serie temporal completa para grafico de barras apiladas (Tab 1).

    Para cada anio y departamento, cuenta publicaciones y suma citas.
    Retorna en formato largo (long format), listo para Plotly.

    Returns
    -------
    pd.DataFrame
        Columnas: ``anio``, ``departamento``, ``publicaciones``,
        ``citas_totales``.  Formato largo ordenado por anio y
        departamento.
    """
    cols = ["anio", "departamento", "publicaciones", "citas_totales"]

    logger.info("evolucion_temporal_comparativa: generando serie temporal")

    df_profesores = queries.get_profesores()

    if df_profesores.empty:
        return pd.DataFrame(columns=cols)

    depto_ids = df_profesores["id_departamento"].dropna().unique()
    partes: List[pd.DataFrame] = []

    for did in depto_ids:
        did = int(did)
        evol = queries.get_evolucion_anual(departamento_id=did)
        if not evol.empty and "nombre_departamento" in evol.columns:
            parte = evol[
                ["anio", "nombre_departamento", "publicaciones",
                 "citas_totales"]
            ].rename(columns={"nombre_departamento": "departamento"})
            partes.append(parte)

    if not partes:
        return pd.DataFrame(columns=cols)

    resultado = pd.concat(partes, ignore_index=True)
    resultado = resultado.sort_values(
        ["anio", "departamento"],
    ).reset_index(drop=True)

    logger.info(
        "evolucion_temporal_comparativa: %d filas, %d deptos",
        len(resultado),
        resultado["departamento"].nunique() if not resultado.empty else 0,
    )
    return resultado


def top_publicaciones_citadas(
    n: int = 20,
    departamento_id: Optional[int] = None,
) -> pd.DataFrame:
    """Top N publicaciones mas citadas.

    Retorna las publicaciones con mayor ``cited_by_count``, incluyendo
    los nombres de los profesores de la Division que son coautores.

    Parameters
    ----------
    n:
        Cantidad de publicaciones a retornar (default 20).
    departamento_id:
        Si se proporciona, filtra por departamento.

    Returns
    -------
    pd.DataFrame
        Columnas: ``titulo``, ``anio_publicacion``, ``cited_by_count``,
        ``source_title``, ``tipo_documental``, ``doi``,
        ``autores_asociados``.
        Ordenado por cited_by_count descendente.
    """
    cols = [
        "titulo", "anio_publicacion", "cited_by_count", "source_title",
        "tipo_documental", "doi", "autores_asociados",
    ]

    logger.info(
        "top_publicaciones_citadas: n=%d, depto_id=%s", n, departamento_id,
    )

    df_pubs = queries.get_publicaciones(departamento_id=departamento_id)

    if df_pubs.empty:
        return pd.DataFrame(columns=cols)

    # Ordenar por citas y tomar top N
    df_sorted = df_pubs.sort_values(
        "cited_by_count", ascending=False,
    ).head(n).copy()

    # Obtener nombres de profesores asociados a cada publicacion
    # Necesitamos buscar los profesores vinculados de la Division
    df_all_prof = queries.get_profesores(
        departamento_id=departamento_id,
        solo_activos=False,
    )

    autores_map: Dict[int, List[str]] = {}
    if not df_all_prof.empty:
        for _, prof in df_all_prof.iterrows():
            pid = int(prof["id_profesor"])
            pubs_prof = queries.get_publicaciones(profesor_id=pid)
            if not pubs_prof.empty:
                for pub_id in pubs_prof["id_publicacion"].unique():
                    autores_map.setdefault(int(pub_id), []).append(
                        prof["nombre_normalizado"],
                    )

    # Asignar autores asociados
    df_sorted["autores_asociados"] = df_sorted["id_publicacion"].apply(
        lambda pid: "; ".join(autores_map.get(int(pid), []))
        if pd.notna(pid) else ""
    )

    result = df_sorted[cols].reset_index(drop=True)

    logger.info(
        "top_publicaciones_citadas: retornando %d publicaciones", len(result),
    )
    return result


def analisis_open_access(
    departamento_id: Optional[int] = None,
) -> pd.DataFrame:
    """Evolucion de open access por anio.

    Para cada anio cuenta publicaciones por categoria de
    ``open_access``.  Retorna en formato largo.

    Parameters
    ----------
    departamento_id:
        Si se proporciona, filtra por departamento.

    Returns
    -------
    pd.DataFrame
        Columnas: ``anio``, ``categoria_oa``, ``count``,
        ``proporcion``.  Formato largo ordenado por anio y categoria.
    """
    cols = ["anio", "categoria_oa", "count", "proporcion"]

    logger.info(
        "analisis_open_access: depto_id=%s", departamento_id,
    )

    df_pubs = queries.get_publicaciones(departamento_id=departamento_id)

    if df_pubs.empty:
        return pd.DataFrame(columns=cols)

    # Normalizar campo open_access
    work = df_pubs[["anio_publicacion", "open_access"]].copy()
    work["categoria_oa"] = (
        work["open_access"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "No OA")
    )

    # Agrupar por anio y categoria
    grouped = (
        work
        .groupby(["anio_publicacion", "categoria_oa"])
        .size()
        .reset_index(name="count")
        .rename(columns={"anio_publicacion": "anio"})
    )

    # Calcular proporcion por anio
    totales_anio = grouped.groupby("anio")["count"].transform("sum")
    grouped["proporcion"] = (grouped["count"] / totales_anio).round(4)

    grouped = grouped.sort_values(
        ["anio", "categoria_oa"],
    ).reset_index(drop=True)

    logger.info(
        "analisis_open_access: %d filas, %d anios, %d categorias",
        len(grouped),
        grouped["anio"].nunique() if not grouped.empty else 0,
        grouped["categoria_oa"].nunique() if not grouped.empty else 0,
    )
    return grouped
