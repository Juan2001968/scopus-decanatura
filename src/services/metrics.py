"""
Calculo de indicadores bibliometricos individuales.

Modulo de funciones puras que operan sobre DataFrames (no sobre la BD
directamente).  Recibe datos de ``queries.py`` y retorna metricas
calculadas como valores escalares, diccionarios o DataFrames.

Principio de diseno
-------------------
Cada funcion es **pura**: recibe un ``pd.DataFrame``, retorna un valor,
un ``dict`` o un ``pd.DataFrame``.  No hace queries a la base de datos.
Esto permite testear las metricas independientemente de la base de datos.

Todas las funciones manejan DataFrames vacios sin fallar, retornando 0,
diccionarios con ceros o DataFrames vacios segun corresponda.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

from config.settings import PUB_YEAR_FIN, PUB_YEAR_INICIO, ROLLING_WINDOW_YEARS
from src.utils.logger import get_logger
from src.utils.text_normalization import parse_authors_field

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Conteos de publicaciones
# ---------------------------------------------------------------------------


def contar_publicaciones(df: pd.DataFrame) -> int:
    """Retorna el numero de publicaciones en el DataFrame.

    Parameters
    ----------
    df:
        DataFrame de publicaciones (de ``queries.get_publicaciones``).

    Returns
    -------
    int
        Numero de filas en el DataFrame.

    Example
    -------
    >>> import pandas as pd
    >>> df = pd.DataFrame({"id_publicacion": [1, 2, 3]})
    >>> contar_publicaciones(df)
    3
    """
    return len(df)


def contar_publicaciones_ventana(
    df: pd.DataFrame,
    anio_inicio: int = PUB_YEAR_INICIO,
    anio_fin: int = PUB_YEAR_FIN,
) -> int:
    """Retorna el numero de publicaciones en el rango [anio_inicio, anio_fin].

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columna ``anio_publicacion``.
    anio_inicio:
        Primer año incluido (default: ``PUB_YEAR_INICIO`` = 2014).
    anio_fin:
        Último año incluido (default: ``PUB_YEAR_FIN`` = 2025).

    Returns
    -------
    int
        Numero de publicaciones dentro del rango.

    Example
    -------
    >>> import pandas as pd
    >>> df = pd.DataFrame({"anio_publicacion": [2013, 2014, 2020, 2025, 2026]})
    >>> contar_publicaciones_ventana(df)  # 2014-2025
    3
    """
    if df.empty:
        return 0

    mask = (df["anio_publicacion"] >= anio_inicio) & (df["anio_publicacion"] <= anio_fin)
    return int(mask.sum())


# ---------------------------------------------------------------------------
# Citas
# ---------------------------------------------------------------------------


def calcular_citas_totales(df: pd.DataFrame) -> Dict[str, Union[int, float]]:
    """Retorna estadisticas descriptivas de citas.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columna ``cited_by_count``.

    Returns
    -------
    dict
        Claves:

        - ``total`` (int): suma de cited_by_count.
        - ``promedio`` (float): media, redondeada a 2 decimales.
        - ``mediana`` (float): mediana.
        - ``max`` (int): valor maximo.
        - ``publicaciones_sin_citas`` (int): registros con
          cited_by_count == 0.
        - ``porcentaje_sin_citas`` (float): proporcion de
          publicaciones sin citas (0.0 a 1.0).

    Example
    -------
    >>> import pandas as pd
    >>> df = pd.DataFrame({"cited_by_count": [0, 5, 10, 0]})
    >>> stats = calcular_citas_totales(df)
    >>> stats["total"]
    15
    >>> stats["publicaciones_sin_citas"]
    2
    """
    zeros: Dict[str, Union[int, float]] = {
        "total": 0,
        "promedio": 0.0,
        "mediana": 0.0,
        "max": 0,
        "publicaciones_sin_citas": 0,
        "porcentaje_sin_citas": 0.0,
    }

    if df.empty:
        return zeros

    citas = df["cited_by_count"].fillna(0)
    n = len(citas)
    sin_citas = int((citas == 0).sum())

    return {
        "total": int(citas.sum()),
        "promedio": round(float(citas.mean()), 2),
        "mediana": float(citas.median()),
        "max": int(citas.max()),
        "publicaciones_sin_citas": sin_citas,
        "porcentaje_sin_citas": round(sin_citas / n, 4) if n > 0 else 0.0,
    }


def calcular_citas_por_anio(df: pd.DataFrame) -> pd.DataFrame:
    """Retorna citas agregadas por anio de publicacion.

    Incluye una columna de normalizacion por antiguedad del paper:
    ``citas_ajustadas_antiguedad = citas_promedio / (anio_actual - anio + 1)``.
    Un paper de 2020 ha tenido mas tiempo para acumular citas que uno
    de 2024, por lo que este ajuste permite comparar impacto relativo.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columnas ``anio_publicacion``
        y ``cited_by_count``.

    Returns
    -------
    pd.DataFrame
        Columnas: ``anio``, ``publicaciones``, ``citas_totales``,
        ``citas_promedio``, ``citas_mediana``,
        ``citas_ajustadas_antiguedad``.  Ordenado por anio ascendente.
    """
    cols = [
        "anio", "publicaciones", "citas_totales",
        "citas_promedio", "citas_mediana", "citas_ajustadas_antiguedad",
    ]

    if df.empty:
        return pd.DataFrame(columns=cols)

    work = df[["anio_publicacion", "cited_by_count"]].copy()
    work["cited_by_count"] = work["cited_by_count"].fillna(0)

    grouped = (
        work
        .groupby("anio_publicacion")
        .agg(
            publicaciones=("cited_by_count", "count"),
            citas_totales=("cited_by_count", "sum"),
            citas_promedio=("cited_by_count", "mean"),
            citas_mediana=("cited_by_count", "median"),
        )
        .reset_index()
        .rename(columns={"anio_publicacion": "anio"})
    )

    grouped["citas_promedio"] = grouped["citas_promedio"].round(2)
    grouped["citas_mediana"] = grouped["citas_mediana"].round(2)

    anio_actual = datetime.now().year
    grouped["citas_ajustadas_antiguedad"] = (
        grouped["citas_promedio"] / (anio_actual - grouped["anio"] + 1)
    ).round(4)

    grouped = grouped.sort_values("anio").reset_index(drop=True)

    logger.debug(
        "calcular_citas_por_anio: %d anios (%d-%d)",
        len(grouped),
        int(grouped["anio"].min()),
        int(grouped["anio"].max()),
    )
    return grouped


def calcular_hindex(citas: List[int]) -> int:
    """H-index a partir de una lista de citas (versión canónica).

    Alias directo de :func:`calcular_h_index_desde_citas` con la
    implementación explícita solicitada para verificación.
    """
    citas_ordenadas = sorted(
        [int(c) for c in citas if c is not None and str(c) != 'nan'],
        reverse=True,
    )
    h = 0
    for i, c in enumerate(citas_ordenadas, start=1):
        if i <= c:
            h = i
        else:
            break
    return h


def calcular_h_index_desde_citas(citas: List[object]) -> Optional[int]:
    """Calcula el h-index a partir de una lista de citas por publicación.

    El h-index es el mayor valor h tal que existen al menos h publicaciones
    con h o más citas cada una.

    Parameters
    ----------
    citas:
        Lista de conteos de citas (puede contener None, NaN, strings, etc.).

    Returns
    -------
    int or None
        h-index calculado. Retorna 0 si no hay publicaciones válidas.
    """
    if citas is None:
        return 0

    serie = pd.to_numeric(pd.Series(citas), errors="coerce").fillna(0).astype(int)
    if serie.empty:
        return 0

    citas_ordenadas = sorted(serie.tolist(), reverse=True)

    h = 0
    for i, c in enumerate(citas_ordenadas, start=1):
        if c >= i:
            h = i
        else:
            break

    return int(h)


def calcular_h_index_desde_publicaciones(df: pd.DataFrame) -> Optional[int]:
    """Calcula el h-index a partir de un DataFrame de publicaciones.

    Requiere la columna ``cited_by_count``.

    Parameters
    ----------
    df:
        DataFrame de publicaciones.

    Returns
    -------
    int or None
        h-index calculado a partir de ``cited_by_count``.
    """
    if df.empty or "cited_by_count" not in df.columns:
        return 0

    return calcular_h_index_desde_citas(df["cited_by_count"].tolist())
# ---------------------------------------------------------------------------
# Distribuciones
# ---------------------------------------------------------------------------


def calcular_distribucion_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Distribucion de publicaciones por tipo documental.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columna ``tipo_documental``.

    Returns
    -------
    pd.DataFrame
        Columnas: ``tipo_documental``, ``count``, ``proporcion``.
        Ordenado por count descendente.
    """
    cols = ["tipo_documental", "count", "proporcion"]

    if df.empty:
        return pd.DataFrame(columns=cols)

    conteo = (
        df["tipo_documental"]
        .fillna("Sin tipo")
        .value_counts()
        .reset_index()
    )
    conteo.columns = ["tipo_documental", "count"]

    total = int(conteo["count"].sum())
    conteo["proporcion"] = (
        (conteo["count"] / total).round(4) if total > 0 else 0.0
    )

    logger.debug(
        "calcular_distribucion_tipos: %d tipos, total=%d",
        len(conteo), total,
    )
    return conteo


def calcular_distribucion_cuartiles(df: pd.DataFrame) -> pd.DataFrame:
    """Distribucion de publicaciones por cuartil SJR.

    Los valores nulos de ``cuartil_sjr`` se categorizan como
    ``"Sin dato"``.  El resultado se ordena: Q1, Q2, Q3, Q4, Sin dato.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columna ``cuartil_sjr``.

    Returns
    -------
    pd.DataFrame
        Columnas: ``cuartil``, ``count``, ``proporcion``.
        Ordenado: Q1, Q2, Q3, Q4, Sin dato.
    """
    cols = ["cuartil", "count", "proporcion"]

    if df.empty:
        return pd.DataFrame(columns=cols)

    cuartiles = df["cuartil_sjr"].fillna("Sin dato").copy()

    conteo = cuartiles.value_counts().reset_index()
    conteo.columns = ["cuartil", "count"]

    total = int(conteo["count"].sum())
    conteo["proporcion"] = (
        (conteo["count"] / total).round(4) if total > 0 else 0.0
    )

    # Orden fijo: Q1, Q2, Q3, Q4, Sin dato
    orden = ["Q1", "Q2", "Q3", "Q4", "Sin dato"]
    conteo["cuartil"] = pd.Categorical(
        conteo["cuartil"], categories=orden, ordered=True,
    )
    conteo = conteo.sort_values("cuartil").reset_index(drop=True)

    # Eliminar categorias sin datos (Categorical puede introducir filas NaN)
    conteo = conteo.dropna(subset=["cuartil"]).reset_index(drop=True)
    # Restaurar a string para evitar problemas de tipo Categorical aguas abajo
    conteo["cuartil"] = conteo["cuartil"].astype(str)

    logger.debug(
        "calcular_distribucion_cuartiles: %d categorias, total=%d",
        len(conteo), total,
    )
    return conteo


# ---------------------------------------------------------------------------
# Metricas de fuente
# ---------------------------------------------------------------------------


def calcular_metricas_fuente_promedio(
    df: pd.DataFrame,
) -> Dict[str, Union[int, float]]:
    """Promedio de metricas de fuente de las publicaciones.

    Calcula promedios de SJR, CiteScore y SNIP ignorando valores
    nulos.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columnas ``sjr``, ``citescore``
        y ``snip``.

    Returns
    -------
    dict
        Claves:

        - ``sjr_promedio`` (float): redondeado a 3 decimales.
        - ``citescore_promedio`` (float): redondeado a 2 decimales.
        - ``snip_promedio`` (float): redondeado a 3 decimales.
        - ``publicaciones_con_sjr`` (int): publicaciones con SJR
          no nulo.
        - ``cobertura_sjr`` (float): porcentaje de publicaciones
          con SJR disponible (0.0 a 1.0).
    """
    zeros: Dict[str, Union[int, float]] = {
        "sjr_promedio": 0.0,
        "citescore_promedio": 0.0,
        "snip_promedio": 0.0,
        "publicaciones_con_sjr": 0,
        "cobertura_sjr": 0.0,
    }

    if df.empty:
        return zeros

    n = len(df)
    con_sjr = int(df["sjr"].notna().sum())

    return {
        "sjr_promedio": round(float(df["sjr"].mean()), 3)
        if con_sjr > 0 else 0.0,
        "citescore_promedio": round(float(df["citescore"].mean()), 2)
        if df["citescore"].notna().any() else 0.0,
        "snip_promedio": round(float(df["snip"].mean()), 3)
        if df["snip"].notna().any() else 0.0,
        "publicaciones_con_sjr": con_sjr,
        "cobertura_sjr": round(con_sjr / n, 4) if n > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Open access
# ---------------------------------------------------------------------------


def calcular_proporcion_open_access(
    df: pd.DataFrame,
) -> Dict[str, Union[int, float, dict]]:
    """Proporcion de publicaciones en open access.

    El campo ``open_access`` de Scopus puede tener valores como
    ``"All Open Access"``, ``"Green"``, ``"Gold"``, vacio, etc.
    Se considera open access cualquier publicacion con un valor
    no nulo y no vacio en dicho campo.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columna ``open_access``.

    Returns
    -------
    dict
        Claves:

        - ``total`` (int): total de publicaciones.
        - ``open_access`` (int): publicaciones con valor OA no vacio.
        - ``proporcion`` (float): proporcion de OA (0.0 a 1.0).
        - ``detalle_por_tipo`` (dict): conteo por cada valor distinto
          del campo open_access.
    """
    result: Dict[str, Union[int, float, dict]] = {
        "total": 0,
        "open_access": 0,
        "proporcion": 0.0,
        "detalle_por_tipo": {},
    }

    if df.empty:
        return result

    n = len(df)

    # Normalizar: NaN y cadenas vacias se tratan como "sin OA"
    oa = df["open_access"].fillna("").astype(str).str.strip()

    # Detalle por tipo (solo valores no vacios)
    detalle: Dict[str, int] = {}
    for valor, conteo in oa.value_counts().items():
        if valor:  # excluir cadena vacia
            detalle[str(valor)] = int(conteo)

    oa_count = int((oa != "").sum())

    result["total"] = n
    result["open_access"] = oa_count
    result["proporcion"] = round(oa_count / n, 4) if n > 0 else 0.0
    result["detalle_por_tipo"] = detalle

    logger.debug(
        "calcular_proporcion_open_access: %d/%d OA (%.1f%%)",
        oa_count, n, result["proporcion"] * 100,
    )
    return result


# ---------------------------------------------------------------------------
# Colaboracion
# ---------------------------------------------------------------------------


def calcular_estadisticas_colaboracion(
    df: pd.DataFrame,
) -> Dict[str, Union[int, float]]:
    """Estadisticas de colaboracion basadas en numero de autores.

    Parsea el campo ``authors_raw`` con
    :func:`~src.utils.text_normalization.parse_authors_field` para
    contar autores por publicacion y calcular estadisticas descriptivas.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columna ``authors_raw``.

    Returns
    -------
    dict
        Claves:

        - ``promedio_autores`` (float): media de autores por
          publicacion, redondeada a 2 decimales.
        - ``mediana_autores`` (float): mediana.
        - ``max_autores`` (int): maximo de autores en una publicacion.
        - ``publicaciones_un_autor`` (int): publicaciones con un solo
          autor.
        - ``proporcion_un_autor`` (float): proporcion de publicaciones
          de un solo autor (0.0 a 1.0).
    """
    zeros: Dict[str, Union[int, float]] = {
        "promedio_autores": 0.0,
        "mediana_autores": 0.0,
        "max_autores": 0,
        "publicaciones_un_autor": 0,
        "proporcion_un_autor": 0.0,
    }

    if df.empty:
        return zeros

    # Contar autores por publicacion
    conteos: List[int] = []
    for raw in df["authors_raw"].fillna(""):
        autores = parse_authors_field(str(raw))
        conteos.append(len(autores) if autores else 0)

    if not conteos or all(c == 0 for c in conteos):
        return zeros

    serie = pd.Series(conteos)
    # Filtrar publicaciones sin autores parseables para las estadisticas
    serie_valida = serie[serie > 0]

    if serie_valida.empty:
        return zeros

    un_autor = int((serie_valida == 1).sum())
    n = len(serie_valida)

    return {
        "promedio_autores": round(float(serie_valida.mean()), 2),
        "mediana_autores": float(serie_valida.median()),
        "max_autores": int(serie_valida.max()),
        "publicaciones_un_autor": un_autor,
        "proporcion_un_autor": round(un_autor / n, 4) if n > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


def calcular_top_keywords(
    df: pd.DataFrame,
    top_n: int = 20,
) -> pd.DataFrame:
    """Top N indexed keywords mas frecuentes.

    Splitea ``indexed_keywords`` por ``"; "``, normaliza cada keyword
    (strip, title case) y cuenta frecuencias.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columna ``indexed_keywords``.
    top_n:
        Cantidad de keywords a retornar (default 20).

    Returns
    -------
    pd.DataFrame
        Columnas: ``keyword``, ``frecuencia``, ``proporcion``.
        Ordenado por frecuencia descendente.
    """
    cols = ["keyword", "frecuencia", "proporcion"]

    if df.empty:
        return pd.DataFrame(columns=cols)

    counter: Counter = Counter()
    for kw_str in df["indexed_keywords"].dropna():
        keywords = [
            k.strip().title()
            for k in str(kw_str).split(";")
            if k.strip()
        ]
        counter.update(keywords)

    if not counter:
        return pd.DataFrame(columns=cols)

    top_items = counter.most_common(top_n)
    total = sum(counter.values())

    result = pd.DataFrame(top_items, columns=["keyword", "frecuencia"])
    result["proporcion"] = (
        (result["frecuencia"] / total).round(4) if total > 0 else 0.0
    )

    logger.debug(
        "calcular_top_keywords: %d unicas, retornando top %d",
        len(counter), len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Autocitas intragrupo
# ---------------------------------------------------------------------------

_autocitas_cache: Optional[pd.DataFrame] = None


def _load_autocitas() -> pd.DataFrame:
    """Carga (y cachea) el CSV de autocitas intragrupo calculado por ETL.

    Returns
    -------
    pd.DataFrame
        Columnas: ``eid``, ``autocitas_intragrupo``,
        ``citaciones_intragrupo_total``.  DataFrame vacío si el archivo
        no existe.
    """
    global _autocitas_cache
    if _autocitas_cache is not None:
        return _autocitas_cache

    try:
        from config.settings import DATA_PROCESSED_DIR
        path = DATA_PROCESSED_DIR / "autocitas_v1.csv"
        if path.exists():
            _autocitas_cache = pd.read_csv(path)
            logger.info(
                "_load_autocitas: %d registros cargados desde %s",
                len(_autocitas_cache), path,
            )
        else:
            logger.warning("_load_autocitas: archivo no encontrado en %s", path)
            _autocitas_cache = pd.DataFrame(
                columns=["eid", "autocitas_intragrupo", "citaciones_intragrupo_total"]
            )
    except Exception as exc:
        logger.error("_load_autocitas: error cargando CSV: %s", exc)
        _autocitas_cache = pd.DataFrame(
            columns=["eid", "autocitas_intragrupo", "citaciones_intragrupo_total"]
        )

    return _autocitas_cache


def calcular_autocitas_intragrupo(df: pd.DataFrame) -> int:
    """Suma de autocitas intragrupo para las publicaciones del DataFrame.

    Cruza los EID del DataFrame con el archivo precalculado
    ``autocitas_v1.csv``.  Representa cuántas citas provienen de otras
    publicaciones de la misma División.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columna ``eid``.

    Returns
    -------
    int
        Total de autocitas intragrupo.  0 si no hay datos.
    """
    if df.empty or "eid" not in df.columns:
        return 0

    df_auto = _load_autocitas()
    if df_auto.empty:
        return 0

    eids = df["eid"].dropna().unique()
    mask = df_auto["eid"].isin(eids)
    total = int(df_auto.loc[mask, "autocitas_intragrupo"].sum())

    logger.debug(
        "calcular_autocitas_intragrupo: %d EIDs, %d autocitas",
        len(eids), total,
    )
    return total


def calcular_citas_por_anio_con_autocitas(df: pd.DataFrame) -> pd.DataFrame:
    """Citas y autocitas intragrupo agregadas por año de publicación.

    Extiende :func:`calcular_citas_por_anio` con columnas
    ``autocitas_intragrupo`` y ``citas_externas``.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columnas ``anio_publicacion``,
        ``cited_by_count`` y ``eid``.

    Returns
    -------
    pd.DataFrame
        Columnas: ``anio``, ``publicaciones``, ``citas_totales``,
        ``autocitas_intragrupo``, ``citas_externas``,
        ``citas_promedio``, ``citas_ajustadas_antiguedad``.
    """
    base = calcular_citas_por_anio(df)
    if base.empty:
        return base

    df_auto = _load_autocitas()
    if df_auto.empty or "eid" not in df.columns:
        base["autocitas_intragrupo"] = 0
        base["citas_externas"] = base["citas_totales"]
        return base

    work = df[["anio_publicacion", "eid"]].copy()
    work = work.merge(
        df_auto[["eid", "autocitas_intragrupo"]],
        on="eid", how="left",
    )
    work["autocitas_intragrupo"] = work["autocitas_intragrupo"].fillna(0).astype(int)

    auto_por_anio = (
        work.groupby("anio_publicacion")["autocitas_intragrupo"]
        .sum()
        .reset_index()
        .rename(columns={"anio_publicacion": "anio"})
    )

    base = base.merge(auto_por_anio, on="anio", how="left")
    base["autocitas_intragrupo"] = base["autocitas_intragrupo"].fillna(0).astype(int)
    base["citas_externas"] = (base["citas_totales"] - base["autocitas_intragrupo"]).clip(lower=0)

    return base


# ---------------------------------------------------------------------------
# KPIs resumen
# ---------------------------------------------------------------------------

def generar_kpis_resumen(
    df: pd.DataFrame,
    h_index: Optional[int] = None,
) -> Dict[str, object]:
    """Genera el diccionario completo de KPIs para una tarjeta de resumen.

    Si ``h_index`` es None, se calcula desde las publicaciones usando
    ``cited_by_count``.
    """
    h_index_final = (
        h_index if h_index is not None
        else calcular_h_index_desde_publicaciones(df)
    )

    citas_stats = calcular_citas_totales(df)
    autocitas   = calcular_autocitas_intragrupo(df)
    citas_total = citas_stats.get("total", 0)

    kpis = {
        "total_publicaciones":  contar_publicaciones(df),
        "publicaciones_3_anios": contar_publicaciones_ventana(df),
        "citas":                citas_stats,
        "h_index":              h_index_final,
        "metricas_fuente":      calcular_metricas_fuente_promedio(df),
        "open_access":          calcular_proporcion_open_access(df),
        "colaboracion":         calcular_estadisticas_colaboracion(df),
        "autocitas_intragrupo": autocitas,
        "citas_sin_autocitas":  max(0, citas_total - autocitas),
    }

    logger.info(
        "generar_kpis_resumen: %d publicaciones, h_index=%s, "
        "citas=%d, autocitas=%d",
        kpis["total_publicaciones"], h_index_final,
        citas_total, autocitas,
    )
    return kpis


def calcular_citas_por_anio_con_autocitas(df: pd.DataFrame) -> pd.DataFrame:
    """Citas y autocitas intragrupo agregadas por año de publicación.

    Extiende :func:`calcular_citas_por_anio` con columnas
    ``autocitas_intragrupo`` y ``citas_externas``.

    Parameters
    ----------
    df:
        DataFrame de publicaciones con columnas ``anio_publicacion``,
        ``cited_by_count`` y ``eid``.

    Returns
    -------
    pd.DataFrame
        Columnas: ``anio``, ``publicaciones``, ``citas_totales``,
        ``autocitas_intragrupo``, ``citas_externas``,
        ``citas_promedio``, ``citas_ajustadas_antiguedad``.
    """
    base = calcular_citas_por_anio(df)
    if base.empty:
        return base

    df_auto = _load_autocitas()
    if df_auto.empty or "eid" not in df.columns:
        base["autocitas_intragrupo"] = 0
        base["citas_externas"] = base["citas_totales"]
        return base

    work = df[["anio_publicacion", "eid"]].copy()
    work = work.merge(
        df_auto[["eid", "autocitas_intragrupo"]],
        on="eid", how="left",
    )
    work["autocitas_intragrupo"] = work["autocitas_intragrupo"].fillna(0).astype(int)

    auto_por_anio = (
        work.groupby("anio_publicacion")["autocitas_intragrupo"]
        .sum()
        .reset_index()
        .rename(columns={"anio_publicacion": "anio"})
    )

    base = base.merge(auto_por_anio, on="anio", how="left")
    base["autocitas_intragrupo"] = base["autocitas_intragrupo"].fillna(0).astype(int)
    base["citas_externas"] = (base["citas_totales"] - base["autocitas_intragrupo"]).clip(lower=0)

    return base


# ---------------------------------------------------------------------------
# KPIs resumen
# ---------------------------------------------------------------------------

def generar_kpis_resumen(
    df: pd.DataFrame,
    h_index: Optional[int] = None,
) -> Dict[str, object]:
    """Genera el diccionario completo de KPIs para una tarjeta de resumen.

    Si ``h_index`` es None, se calcula desde las publicaciones usando
    ``cited_by_count``.
    """
    h_index_final = (
        h_index if h_index is not None
        else calcular_h_index_desde_publicaciones(df)
    )

    citas_stats = calcular_citas_totales(df)
    autocitas   = calcular_autocitas_intragrupo(df)
    citas_total = citas_stats.get("total", 0)

    kpis = {
        "total_publicaciones":  contar_publicaciones(df),
        "publicaciones_3_anios": contar_publicaciones_ventana(df),
        "citas":                citas_stats,
        "h_index":              h_index_final,
        "metricas_fuente":      calcular_metricas_fuente_promedio(df),
        "open_access":          calcular_proporcion_open_access(df),
        "colaboracion":         calcular_estadisticas_colaboracion(df),
        "autocitas_intragrupo": autocitas,
        "citas_sin_autocitas":  max(0, citas_total - autocitas),
    }

    logger.info(
        "generar_kpis_resumen: %d publicaciones, h_index=%s, "
        "citas=%d, autocitas=%d",
        kpis["total_publicaciones"], h_index_final,
        citas_total, autocitas,
    )
    return kpis
