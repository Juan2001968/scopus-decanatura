"""
Callbacks globales del dashboard bibliométrico.

Responsabilidades:
1. Poblar dinámicamente los filtros globales.
2. Actualizar la fila superior de KPIs.
3. Renderizar el contenido dinámico de cada tab según los filtros.
"""

from __future__ import annotations

from typing import Optional

import dash_bootstrap_components as dbc
import pandas as pd
from dash import ALL, Input, Output, State, callback_context, html, no_update

from dashboard.app import app
from dashboard.components.kpi_cards import create_kpi_row, create_kpi_row_custom
from dashboard.pages.analisis_impacto import layout_impacto
from dashboard.pages.benchmarking import (
    build_ranking_table_body,
    layout_benchmarking,
    ranking_caption,
)
from dashboard.pages.calidad_fuente import layout_fuentes
from dashboard.pages.calidad_matching import layout_matching
from dashboard.pages.colaboracion_tematicas import layout_colaboracion
from dashboard.pages.explorador_datos import layout_explorador
from dashboard.pages.perfil_profesor import layout_profesor
from dashboard.pages.resumen_division import layout_resumen
from src.services import metrics, queries
from src.utils.logger import get_logger
from src.utils.text_normalization import parse_authors_field

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers generales
# ---------------------------------------------------------------------------


def _safe_int(value: object) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_year_range(value: object) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return 2014, 2025
    try:
        y0, y1 = int(value[0]), int(value[1])
        return min(y0, y1), max(y0, y1)
    except (TypeError, ValueError):
        return 2014, 2025


def _year_suffix(anios: object) -> str:
    y0, y1 = _safe_year_range(anios)
    if y0 == 2014 and y1 == 2025:
        return ""
    if y0 == y1:
        return f" ({y0})"
    return f" ({y0}–{y1})"


def _df_error(df: object) -> Optional[str]:
    """Mensaje de error adjuntado por la capa de datos (``queries.py``).

    Las funciones ``get_*`` marcan en ``df.attrs["error"]`` cuando la
    consulta fallo; asi la UI puede distinguir "sin datos" de "la BD no
    respondio" en vez de mostrar ceros enganosos.
    """
    if isinstance(df, pd.DataFrame):
        err = df.attrs.get("error")
        return str(err) if err else None
    return None


def _normalize_multi(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)]


def _to_options(
    df: pd.DataFrame,
    value_col: str,
    label_col: Optional[str] = None,
) -> list[dict]:
    if df.empty or value_col not in df.columns:
        return []

    label_col = label_col or value_col
    if label_col not in df.columns:
        label_col = value_col

    work = (
        df[[value_col, label_col]]
        .dropna(subset=[value_col])
        .drop_duplicates()
        .copy()
    )
    if work.empty:
        return []

    work[label_col] = work[label_col].astype(str).str.strip()
    work = work.sort_values(label_col)

    options = []
    for _, row in work.iterrows():
        raw_value = row[value_col]
        try:
            if pd.notna(raw_value):
                raw_value = int(raw_value)
        except Exception:
            pass
        options.append({"label": str(row[label_col]), "value": raw_value})
    return options


def _tipo_options(df: pd.DataFrame) -> list[dict]:
    if df.empty or "tipo_documental" not in df.columns:
        return []
    values = sorted([
        v for v in df["tipo_documental"].dropna().astype(str).str.strip().unique().tolist()
        if v
    ])
    return [{"label": v, "value": v} for v in values]


def _apply_tipo_filter(df: pd.DataFrame, tipos: list[str]) -> pd.DataFrame:
    if df.empty or not tipos or "tipo_documental" not in df.columns:
        return df.copy()
    return df[df["tipo_documental"].astype(str).isin(tipos)].copy()


def _apply_cuartil_filter(df: pd.DataFrame, cuartiles: list[str]) -> pd.DataFrame:
    """Post-filter por cuartil SJR."""
    if df.empty or not cuartiles or "cuartil_sjr" not in df.columns:
        return df.copy()
    return df[df["cuartil_sjr"].fillna("Sin dato").astype(str).isin(cuartiles)].copy()


def _get_departamentos_df() -> pd.DataFrame:
    df = queries.get_departamentos()
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _get_profesores_df(departamento_id: Optional[int] = None) -> pd.DataFrame:
    df = queries.get_profesores(departamento_id=departamento_id, solo_activos=False)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _get_departamento_nombre(departamento_id: Optional[int]) -> str:
    if departamento_id is None:
        return "Área de investigación"
    df = _get_departamentos_df()
    if df.empty:
        return "Área de investigación"
    row = df[df["id_departamento"] == departamento_id]
    if row.empty:
        return "Área de investigación"
    return str(row.iloc[0]["nombre"])


def _get_profesor_row(profesor_id: Optional[int]) -> Optional[pd.Series]:
    if profesor_id is None:
        return None
    df = queries.get_profesores(solo_activos=False)
    if df.empty:
        return None
    row = df[df["id_profesor"] == profesor_id]
    if row.empty:
        return None
    return row.iloc[0]


# NOTA h-index: todo h-index mostrado en el dashboard se CALCULA por
# ordenamiento de citas sobre las publicaciones que pasan los filtros activos
# (metrics.calcular_h_index_desde_publicaciones):
#
#   c(1) >= c(2) >= ... >= c(n)   (citas por publicación, orden descendente)
#   h = max { i : c(i) >= i }
#
# El h-index del perfil Scopus (columna profesor.h_index) ya NO se muestra;
# solo se conserva en BD como referencia.


def _fetch_publicaciones(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> pd.DataFrame:
    anio_min, anio_max = _safe_year_range(anios)
    # El filtro de profesor prevalece sobre el de area: el selector de
    # profesores ya esta restringido al area elegida, y un desfase transitorio
    # entre ambos dropdowns no debe dejar el perfil en cero por el AND en SQL.
    if profesor_id is not None:
        departamento_id = None
    # Cuando no hay filtro de departamento ni de profesor, el agregado
    # representa la Division completa.  Como la tabla ``publicacion`` contiene
    # todas las publicaciones de la Universidad del Norte, restringimos a las
    # vinculadas a profesores de la Division mediante ``solo_division``.
    solo_division = departamento_id is None and profesor_id is None
    df = queries.get_publicaciones(
        anio_min=anio_min, anio_max=anio_max,
        departamento_id=departamento_id, profesor_id=profesor_id,
        solo_division=solo_division,
    )
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    error = _df_error(df)
    n_sql = len(df)
    df = _apply_tipo_filter(df, tipos)
    n_tipo = len(df)
    if cuartiles:
        df = _apply_cuartil_filter(df, cuartiles)
    n_cuartil = len(df)
    logger.info(
        "_fetch_publicaciones: SQL=%d -> tras tipo=%d -> tras cuartil=%d "
        "(depto=%s, prof=%s, anios=%s-%s, tipos=%s, cuartiles=%s)",
        n_sql, n_tipo, n_cuartil, departamento_id, profesor_id,
        anio_min, anio_max, tipos or "-", cuartiles or "-",
    )
    df = df.reset_index(drop=True)
    if error:
        df.attrs["error"] = error
    df.attrs["etapas"] = {
        "consulta_sql": n_sql,
        "tras_tipo": n_tipo,
        "tras_cuartil": n_cuartil,
    }
    return df


def _get_department_contexts(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> list[dict]:
    contexts: list[dict] = []

    if profesor_id is not None:
        prof_row = _get_profesor_row(profesor_id)
        did = (_safe_int(prof_row.get("id_departamento"))
               if prof_row is not None else departamento_id)
        dname = (
            str(prof_row.get("nombre_departamento"))
            if prof_row is not None and pd.notna(prof_row.get("nombre_departamento"))
            else _get_departamento_nombre(did)
        )
        df = _fetch_publicaciones(did, profesor_id, anios, tipos, cuartiles)
        contexts.append({"id_departamento": did, "departamento": dname, "df": df})
        return contexts

    if departamento_id is not None:
        dname = _get_departamento_nombre(departamento_id)
        df = _fetch_publicaciones(departamento_id, None, anios, tipos, cuartiles)
        contexts.append({"id_departamento": departamento_id, "departamento": dname, "df": df})
        return contexts

    deptos = _get_departamentos_df()
    if deptos.empty:
        return []

    for _, row in deptos.iterrows():
        did   = _safe_int(row.get("id_departamento"))
        dname = str(row.get("nombre", "Área de investigación"))
        df    = _fetch_publicaciones(did, None, anios, tipos, cuartiles)
        contexts.append({"id_departamento": did, "departamento": dname, "df": df})

    return contexts


def _build_top_fuentes_df(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    cols = ["source_title", "count", "proporcion", "issn", "sjr", "citescore", "snip", "cuartil_sjr"]
    if df.empty or "source_title" not in df.columns:
        return pd.DataFrame(columns=cols)

    work = df.copy()
    work["source_title"] = work["source_title"].fillna("Sin fuente")

    grouped = (
        work.groupby(["source_title", "issn"], dropna=False)
        .agg(
            count=("id_publicacion", "nunique"),
            sjr=("sjr", "mean"),
            citescore=("citescore", "mean"),
            snip=("snip", "mean"),
        )
        .reset_index()
        .sort_values("count", ascending=False)
        .head(top_n)
    )

    total = int(grouped["count"].sum()) if not grouped.empty else 0
    grouped["proporcion"] = grouped["count"] / total if total > 0 else 0.0

    quartil_map = work[["source_title", "cuartil_sjr"]].dropna(subset=["source_title"]).copy()
    if quartil_map.empty:
        grouped["cuartil_sjr"] = None
    else:
        quartil_mode = (
            quartil_map.groupby("source_title")["cuartil_sjr"]
            .agg(lambda s: s.dropna().mode().iloc[0] if not s.dropna().empty else None)
            .reset_index()
        )
        grouped = grouped.merge(quartil_mode, on="source_title", how="left")

    for col in ["sjr", "citescore", "snip"]:
        if col in grouped.columns:
            grouped[col] = pd.to_numeric(grouped[col], errors="coerce").round(3)

    return grouped[cols].reset_index(drop=True)


def _build_evolucion_por_departamento(contexts: list[dict]) -> pd.DataFrame:
    partes: list[pd.DataFrame] = []
    for ctx in contexts:
        df = ctx["df"]
        if df.empty:
            continue
        evo = metrics.calcular_citas_por_anio(df)
        if evo.empty:
            continue
        evo = evo.copy()
        evo["nombre_departamento"] = ctx["departamento"]
        partes.append(evo[["anio", "nombre_departamento", "publicaciones", "citas_totales"]])

    if not partes:
        return pd.DataFrame(columns=["anio", "nombre_departamento", "publicaciones", "citas_totales"])

    return (
        pd.concat(partes, ignore_index=True)
        .sort_values(["anio", "nombre_departamento"])
        .reset_index(drop=True)
    )


def _build_tabla_departamentos(
    contexts: list[dict],
    profesor_id: Optional[int],
) -> pd.DataFrame:
    cols = [
        "nombre_departamento", "profesores", "publicaciones_total",
        "publicaciones_3_anios", "citas_totales", "h_index_area", "sjr_promedio",
    ]
    rows: list[dict] = []

    for ctx in contexts:
        did   = ctx["id_departamento"]
        dname = ctx["departamento"]
        df    = ctx["df"]

        if profesor_id is not None:
            n_profesores = 1
        else:
            profs_df = _get_profesores_df(departamento_id=did)
            n_profesores = len(profs_df)

        fuente_stats = metrics.calcular_metricas_fuente_promedio(df)

        rows.append({
            "nombre_departamento": dname,
            "profesores":          n_profesores,
            "publicaciones_total": metrics.contar_publicaciones(df),
            "publicaciones_3_anios": metrics.contar_publicaciones_ventana(df),
            "citas_totales":       int(df["cited_by_count"].fillna(0).sum()) if not df.empty else 0,
            # h-index del ámbito calculado por sort de citas de sus
            # publicaciones filtradas (coincide con el KPI "H-index Depto.").
            "h_index_area":        metrics.calcular_h_index_desde_publicaciones(df),
            "sjr_promedio":        fuente_stats.get("sjr_promedio", 0.0),
        })

    if not rows:
        return pd.DataFrame(columns=cols)

    return (
        pd.DataFrame(rows, columns=cols)
        .sort_values("publicaciones_3_anios", ascending=False)
        .reset_index(drop=True)
    )


def _build_profesor_data(
    departamento_id: Optional[int],
    profesor_id: int,
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> dict:
    prof_row = _get_profesor_row(profesor_id)

    df = _fetch_publicaciones(departamento_id, profesor_id, anios, tipos, cuartiles)

    info = {
        "nombre":      prof_row.get("nombre_normalizado", "Profesor") if prof_row is not None else "Profesor",
        "orcid":       prof_row.get("orcid")                          if prof_row is not None else None,
        "departamento":prof_row.get("nombre_departamento", "")        if prof_row is not None else "",
        # h-index calculado por sort de citas sobre las publicaciones del
        # período filtrado (no el h-index del perfil Scopus).
        "h_index":     metrics.calcular_h_index_desde_publicaciones(df),
        "id_profesor": profesor_id,
    }

    return {
        "info":                   info,
        "error":                  _df_error(df),
        # h_index=None -> generar_kpis_resumen lo calcula desde el df filtrado.
        "kpis":                   metrics.generar_kpis_resumen(df, h_index=None),
        "publicaciones":          df,
        "top_fuentes":            _build_top_fuentes_df(df, top_n=10),
        "distribucion_tipos":     metrics.calcular_distribucion_tipos(df),
        "distribucion_cuartiles": metrics.calcular_distribucion_cuartiles(df),
        "evolucion_anual":        metrics.calcular_citas_por_anio(df),
    }


def _build_resumen_data(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> dict:
    base_df  = _fetch_publicaciones(departamento_id, profesor_id, anios, tipos, cuartiles)
    contexts = _get_department_contexts(departamento_id, profesor_id, anios, tipos, cuartiles)

    return {
        "tabla_departamentos":        _build_tabla_departamentos(contexts, profesor_id),
        "evolucion_por_departamento": _build_evolucion_por_departamento(contexts),
        "distribucion_tipos":         metrics.calcular_distribucion_tipos(base_df),
        "distribucion_cuartiles":     metrics.calcular_distribucion_cuartiles(base_df),
        "top_fuentes":                _build_top_fuentes_df(base_df, top_n=10),
        "comparativa_profesores":     _build_profesor_comparativa(departamento_id, profesor_id, anios, tipos, cuartiles),
    }


def _build_profesor_comparativa(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> pd.DataFrame:
    cols = ["id_profesor", "nombre_normalizado", "departamento", "publicaciones_total", "citas_totales", "h_index", "pct_q1q2"]

    if profesor_id is not None:
        profs = queries.get_profesores(solo_activos=False)
        profs = profs[profs["id_profesor"] == profesor_id]
    else:
        profs = _get_profesores_df(departamento_id=departamento_id)

    if profs.empty:
        return pd.DataFrame(columns=cols)

    rows: list[dict] = []
    for _, prof in profs.iterrows():
        pid = _safe_int(prof.get("id_profesor"))
        if pid is None:
            continue
        df_prof = _fetch_publicaciones(None, pid, anios, tipos, cuartiles)

        if not df_prof.empty and "cuartil_sjr" in df_prof.columns:
            total = len(df_prof)
            q1q2  = df_prof["cuartil_sjr"].isin(["Q1", "Q2"]).sum()
            pct   = q1q2 / total if total > 0 else 0.0
        else:
            pct = 0.0

        rows.append({
            "id_profesor":         pid,
            "nombre_normalizado":  prof.get("nombre_normalizado", ""),
            "departamento":        prof.get("nombre_departamento", ""),
            "publicaciones_total": metrics.contar_publicaciones(df_prof),
            "citas_totales":       int(df_prof["cited_by_count"].fillna(0).sum()) if not df_prof.empty else 0,
            # h-index calculado por sort de citas del período filtrado
            # (no el h-index del perfil Scopus).
            "h_index":             metrics.calcular_h_index_desde_publicaciones(df_prof),
            "pct_q1q2":            pct,
        })

    return pd.DataFrame(rows, columns=cols)


def _build_evolucion_comparativa(contexts: list[dict]) -> pd.DataFrame:
    partes: list[pd.DataFrame] = []
    for ctx in contexts:
        df = ctx["df"]
        if df.empty:
            continue
        evo = metrics.calcular_citas_por_anio(df)
        if evo.empty:
            continue
        evo = evo.copy()
        evo["departamento"] = ctx["departamento"]
        partes.append(evo[["anio", "departamento", "publicaciones", "citas_totales"]])

    if not partes:
        return pd.DataFrame(columns=["anio", "departamento", "publicaciones", "citas_totales"])

    return (
        pd.concat(partes, ignore_index=True)
        .sort_values(["anio", "departamento"])
        .reset_index(drop=True)
    )


def _build_top_publicaciones(df: pd.DataFrame, top_n: int = 25) -> pd.DataFrame:
    cols = ["titulo", "anio_publicacion", "cited_by_count", "source_title",
            "tipo_documental", "doi", "autores_asociados", "cuartil_sjr"]

    if df.empty:
        return pd.DataFrame(columns=cols)

    work = df.copy()
    work["autores_asociados"] = work.get("authors_raw", pd.Series("", index=work.index)).fillna("")
    work = work.sort_values("cited_by_count", ascending=False).head(top_n)

    for c in cols:
        if c not in work.columns:
            work[c] = ""

    return work[cols].reset_index(drop=True)


def _build_citas_por_departamento(contexts: list[dict]) -> pd.DataFrame:
    """Citas por área contando cada publicación UNA sola vez.

    Los DataFrames de ``contexts`` provienen de ``get_publicaciones`` con
    filtro de departamento (EXISTS ⇒ publicaciones únicas), por lo que la
    suma de ``cited_by_count`` no repite co-autorías internas.  Es la misma
    base que usan los KPIs y la tabla de Visión General.

    Nota: sumar en su lugar las citas de la comparativa por profesor
    inflaría el total (+19–22 % medido), porque una publicación con k
    profesores del área aparece k veces.
    """
    cols = ["departamento", "publicaciones", "citas_totales"]
    rows: list[dict] = []
    for ctx in contexts:
        df = ctx["df"]
        rows.append({
            "departamento":  ctx["departamento"],
            "publicaciones": int(df["id_publicacion"].nunique()) if not df.empty else 0,
            "citas_totales": int(df["cited_by_count"].fillna(0).sum()) if not df.empty else 0,
        })
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols)


def _build_impacto_data(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> dict:
    base_df  = _fetch_publicaciones(departamento_id, profesor_id, anios, tipos, cuartiles)
    contexts = _get_department_contexts(departamento_id, profesor_id, anios, tipos, cuartiles)

    return {
        "citas_por_anio":           metrics.calcular_citas_por_anio(base_df),
        "citas_autocitas_por_anio": metrics.calcular_citas_por_anio_con_autocitas(base_df),
        "top_publicaciones":        _build_top_publicaciones(base_df, top_n=25),
        "comparativa_profesores":   _build_profesor_comparativa(departamento_id, profesor_id, anios, tipos, cuartiles),
        "evolucion_comparativa":    _build_evolucion_comparativa(contexts),
        "citas_por_departamento":   _build_citas_por_departamento(contexts),
    }


def _build_cuartiles_por_departamento(contexts: list[dict]) -> pd.DataFrame:
    partes: list[pd.DataFrame] = []
    for ctx in contexts:
        dist = metrics.calcular_distribucion_cuartiles(ctx["df"])
        if dist.empty:
            continue
        dist = dist.copy()
        dist["departamento"] = ctx["departamento"]
        partes.append(dist[["departamento", "cuartil", "count"]])

    if not partes:
        return pd.DataFrame(columns=["departamento", "cuartil", "count"])
    return pd.concat(partes, ignore_index=True)


def _build_sjr_por_departamento(contexts: list[dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for ctx in contexts:
        stats = metrics.calcular_metricas_fuente_promedio(ctx["df"])
        rows.append({"departamento": ctx["departamento"],
                     "sjr_promedio": stats.get("sjr_promedio", 0.0)})
    if not rows:
        return pd.DataFrame(columns=["departamento", "sjr_promedio"])
    return (
        pd.DataFrame(rows)
        .sort_values("sjr_promedio", ascending=False)
        .reset_index(drop=True)
    )


def _build_fuentes_data(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> dict:
    base_df  = _fetch_publicaciones(departamento_id, profesor_id, anios, tipos, cuartiles)
    contexts = _get_department_contexts(departamento_id, profesor_id, anios, tipos, cuartiles)

    return {
        "distribucion_cuartiles":      metrics.calcular_distribucion_cuartiles(base_df),
        "cuartiles_por_departamento":  _build_cuartiles_por_departamento(contexts),
        "top_fuentes":                 _build_top_fuentes_df(base_df, top_n=20),
        "sjr_por_departamento":        _build_sjr_por_departamento(contexts),
        # TODO: "publicaciones_sin_clasificar": queries.get_publicaciones_sin_clasificar(...)
    }


def _normalize_oa_category(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Closed"
    text = str(value).strip()
    if not text:
        return "Closed"
    lower = text.lower()
    if "green"  in lower: return "Green"
    if "gold"   in lower: return "Gold"
    if "hybrid" in lower: return "Hybrid"
    if "bronze" in lower: return "Bronze"
    return text.title()


def _build_histograma_autores(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "authors_raw" not in df.columns:
        return pd.DataFrame(columns=["n_autores"])
    counts: list[int] = []
    for raw in df["authors_raw"].fillna(""):
        autores = parse_authors_field(str(raw))
        n = len(autores) if autores else 0
        if n > 0:
            counts.append(n)
    if not counts:
        return pd.DataFrame(columns=["n_autores"])
    return pd.DataFrame({"n_autores": counts})


def _build_open_access_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["anio", "categoria_oa", "count", "proporcion"]
    if df.empty or "anio_publicacion" not in df.columns:
        return pd.DataFrame(columns=cols)
    work = df[["anio_publicacion", "open_access"]].copy()
    work["categoria_oa"] = work["open_access"].apply(_normalize_oa_category)
    grouped = (
        work.groupby(["anio_publicacion", "categoria_oa"])
        .size().reset_index(name="count")
        .rename(columns={"anio_publicacion": "anio"})
    )
    totals = grouped.groupby("anio")["count"].transform("sum")
    grouped["proporcion"] = grouped["count"] / totals
    return grouped[cols].sort_values(["anio", "categoria_oa"]).reset_index(drop=True)


def _build_idiomas_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["idioma", "count"]
    if df.empty or "idioma" not in df.columns:
        return pd.DataFrame(columns=cols)
    result = (
        df["idioma"].fillna("Sin dato").astype(str).str.strip()
        .replace("", "Sin dato").value_counts().reset_index()
    )
    result.columns = ["idioma", "count"]
    return result


def _build_red_coautoria(
    base_df: pd.DataFrame,
    departamento_id: Optional[int],
    profesor_id: Optional[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aristas y nodos de la red de co-autoría, coherentes con los filtros.

    La red se construye desde ``base_df`` (las publicaciones que ya pasaron
    por los filtros de área/profesor/período/tipo/cuartil), de modo que el
    grafo reacciona a TODOS los filtros igual que el resto de indicadores.
    Antes se usaba ``get_coautoria_entre_profesores`` sin período/tipo/
    cuartil y con un filtro de área asimétrico (solo el miembro de menor
    id), por lo que el grafo apenas cambiaba al filtrar.

    Reglas:
    - Área seleccionada: solo pares con AMBOS profesores del área
      (los nodos del grafo son los profesores del área).
    - Profesor seleccionado: red ego — el profesor y sus co-autores de la
      División en las publicaciones filtradas.
    """
    vacio = pd.DataFrame(columns=["id_prof_a", "id_prof_b", "n_copubs"])

    links = queries.get_publicacion_profesor_links()
    if _df_error(links) or links.empty or base_df.empty:
        profesores = queries.get_profesores(departamento_id=departamento_id, solo_activos=False)
        return vacio, profesores

    ids_filtrados = set(base_df["id_publicacion"].dropna())
    links = links[links["id_publicacion"].isin(ids_filtrados)]
    if departamento_id is not None:
        links = links[links["id_departamento"] == departamento_id]

    coautoria = metrics.calcular_coautoria_pares(links)

    if profesor_id is not None:
        coautoria = coautoria[
            (coautoria["id_prof_a"] == profesor_id)
            | (coautoria["id_prof_b"] == profesor_id)
        ].reset_index(drop=True)

    profesores = queries.get_profesores(departamento_id=departamento_id, solo_activos=False)
    if profesor_id is not None and not profesores.empty:
        # Red ego: mostrar solo el profesor y sus co-autores.
        participantes = (
            set(coautoria["id_prof_a"]) | set(coautoria["id_prof_b"]) | {profesor_id}
        )
        profesores = profesores[profesores["id_profesor"].isin(participantes)]

    # Tamaño de nodo = h-index calculado por sort de citas sobre las
    # publicaciones visibles con los filtros activos (se reemplaza el
    # h-index del perfil Scopus que trae get_profesores).
    if not profesores.empty:
        citas_prof = links.merge(
            base_df[["id_publicacion", "cited_by_count"]].drop_duplicates("id_publicacion"),
            on="id_publicacion", how="left",
        )
        h_calc = (
            citas_prof.groupby("id_profesor")["cited_by_count"]
            .apply(lambda s: metrics.calcular_h_index_desde_citas(s.tolist()))
        )
        profesores = profesores.copy()
        profesores["h_index"] = (
            profesores["id_profesor"].map(h_calc).fillna(0).astype(int)
        )

    return coautoria, profesores


def _build_colaboracion_data(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> dict:
    base_df = _fetch_publicaciones(departamento_id, profesor_id, anios, tipos, cuartiles)
    hist    = _build_histograma_autores(base_df)

    try:
        coautoria, profesores = _build_red_coautoria(base_df, departamento_id, profesor_id)
    except Exception as exc:
        logger.error("Error construyendo red coautoría: %s", exc)
        coautoria  = pd.DataFrame()
        profesores = pd.DataFrame()

    return {
        "colaboracion":    metrics.calcular_estadisticas_colaboracion(base_df),
        "histograma_autores": hist,
        "top_keywords":    metrics.calcular_top_keywords(base_df, top_n=30),
        "open_access":     _build_open_access_df(base_df),
        "idiomas":         _build_idiomas_df(base_df),
        "coautoria_red":   coautoria,
        "profesores_red":  profesores,
        "filtros_descripcion": _filtros_activos_descripcion(
            departamento_id, profesor_id, anios, tipos, cuartiles,
        ),
        # TODO: "publicaciones_interinstitucionales": queries.get_publicaciones_interinstitucionales(...)
    }


def _build_benchmarking_data(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]] = None,
) -> dict:
    """Datos de la vista Rankings: comparativa de profesores para el ranking.

    El radar "Perfil multidimensional por área" se retiró de la vista el
    2026-07-07 (las fórmulas de sus dimensiones quedan en el historial de
    ``docs/definiciones_indicadores.md``).
    """
    comparativa = _build_profesor_comparativa(departamento_id, profesor_id, anios, tipos, cuartiles)
    return {"ranking": comparativa}


def _build_matching_data() -> dict:
    try:
        df = queries.get_calidad_matching()
    except Exception as exc:
        logger.error("Error en get_calidad_matching: %s", exc)
        return {"kpis": {}, "tabla": pd.DataFrame()}

    total_prof      = len(df)
    prof_con_pubs   = int((df["pubs_extraidas"] > 0).sum()) if not df.empty else 0
    prof_sin_pubs   = total_prof - prof_con_pubs
    pubs_vinculadas = int(df["pubs_extraidas"].sum()) if not df.empty else 0
    casos_revisar   = int((df["estado"].isin(["REVISAR", "CRITICO"])).sum()) if not df.empty else 0
    pct_match       = prof_con_pubs / total_prof if total_prof > 0 else 0.0

    try:
        pub_total_df = queries.get_publicaciones()
        total_pubs = len(pub_total_df)
    except Exception:
        total_pubs = 0

    kpis = {
        "total_profesores":    total_prof,
        "profesores_con_pubs": prof_con_pubs,
        "profesores_sin_pubs": prof_sin_pubs,
        "total_publicaciones": total_pubs,
        "pubs_vinculadas":     pubs_vinculadas,
        "casos_revisar":       casos_revisar,
        "pct_match":           pct_match,
        "pct_pubs_match":      pubs_vinculadas / total_pubs if total_pubs > 0 else 0.0,
    }

    tabla = df[df["estado"] != "OK"].copy() if not df.empty else pd.DataFrame()
    tabla = tabla.sort_values("cobertura") if not tabla.empty else tabla

    return {"kpis": kpis, "tabla": tabla}


def _compute_global_kpis(
    anios: object,
    tipos: list[str],
    cuartiles: list[str],
    departamento_id: Optional[int] = None,
) -> dict:
    """KPIs de la División completa (o de un departamento) ignorando el filtro de profesor."""
    df = _fetch_publicaciones(departamento_id, None, anios, tipos, cuartiles)
    kpis = metrics.generar_kpis_resumen(df, h_index=None)
    if not df.empty and "cuartil_sjr" in df.columns:
        total = len(df)
        q1q2  = df["cuartil_sjr"].isin(["Q1", "Q2"]).sum()
        kpis["pct_q1q2"] = q1q2 / total if total > 0 else 0.0
    if not df.empty and "id_profesor" in df.columns:
        kpis["profesores_activos"] = int(df["id_profesor"].nunique())
    else:
        profs_df = _get_profesores_df(departamento_id=departamento_id)
        kpis["profesores_activos"] = len(profs_df) if not profs_df.empty else None
    return kpis


_UNIVERSIDAD_KPIS_CACHE: Optional[dict] = None


def _compute_universidad_kpis() -> dict:
    """KPIs institucionales de TODA la Universidad del Norte.

    Usa la tabla ``publicacion`` completa (sin ``solo_division`` y sin filtros
    de area/profesor/periodo/tipo/cuartil): la descarga por ``AF-ID``
    institucional cubre todas las publicaciones de Uninorte, no solo las de la
    Division.  Por diseno, estos totales son fijos y NO reaccionan a los
    filtros del tablero.

    El H-index de Universidad se calcula por sort de citas sobre todas las
    publicaciones (``cited_by_count``), la misma metodologia que usan ahora
    todos los niveles (profesor/area/Division) sobre su conjunto filtrado.

    El resultado se memoiza tras la primera consulta exitosa (los datos son
    constantes durante la vida del proceso); un resultado vacio/transitorio
    -por ejemplo si la BD aun no esta lista- no se cachea.
    """
    global _UNIVERSIDAD_KPIS_CACHE
    if _UNIVERSIDAD_KPIS_CACHE is not None:
        return _UNIVERSIDAD_KPIS_CACHE

    df = queries.get_publicaciones(anio_min=_ANIO_MIN_RESET, anio_max=_ANIO_MAX_RESET)
    if not isinstance(df, pd.DataFrame) or df.empty:
        return metrics.generar_kpis_resumen(pd.DataFrame(), h_index=None)

    kpis = metrics.generar_kpis_resumen(df, h_index=None)
    if "cuartil_sjr" in df.columns:
        total = len(df)
        q1q2  = df["cuartil_sjr"].isin(["Q1", "Q2"]).sum()
        kpis["pct_q1q2"] = q1q2 / total if total > 0 else 0.0
    else:
        kpis["pct_q1q2"] = None

    _UNIVERSIDAD_KPIS_CACHE = kpis
    return kpis


def _compute_profesor_kpis(
    profesor_id: int,
    anios: object,
    tipos: list[str],
    cuartiles: list[str],
) -> dict:
    df = _fetch_publicaciones(None, profesor_id, anios, tipos, cuartiles)
    kpis = metrics.generar_kpis_resumen(df, h_index=None)
    if not df.empty and "cuartil_sjr" in df.columns:
        total = len(df)
        q1q2  = df["cuartil_sjr"].isin(["Q1", "Q2"]).sum()
        kpis["pct_q1q2"] = q1q2 / total if total > 0 else 0.0
    kpis["profesores_activos"] = 1
    return kpis


def _make_kpi_block(title: str, subtitle: str, kpis: dict) -> html.Div:
    return html.Div([
        html.Div([
            html.H4(title, className="section-header-title"),
            html.P(subtitle, className="section-header-subtitle"),
        ], className="section-header-inline"),
        create_kpi_row(kpis),
    ])


def _make_custom_kpi_block(
    title: str, subtitle: str, kpis: dict, cards: list[str],
) -> html.Div:
    """Bloque KPI con título/subtítulo propios y un subconjunto de tarjetas."""
    return html.Div([
        html.Div([
            html.H4(title, className="section-header-title"),
            html.P(subtitle, className="section-header-subtitle"),
        ], className="section-header-inline"),
        create_kpi_row_custom(kpis, cards),
    ])


def _make_division_summary_blocks(
    kpis_division: dict,
    kpis_universidad: dict,
) -> html.Div:
    """Resumen general consolidado: dos bloques apilados.

    1) "Universidad del Norte": totales institucionales completos calculados
       sobre TODA la tabla ``publicacion`` (descarga por ``AF-ID``).  No son
       reactivos a los filtros del tablero (ver ``_compute_universidad_kpis``).
    2) "División de Ciencias Básicas": los mismos cuatro KPIs restringidos a la
       División (vía ``solo_division``) y SÍ reactivos a los filtros activos.

    Ambos bloques son visualmente idénticos pero se alimentan de dicts
    distintos: ``kpis_universidad`` (constante) y ``kpis_division`` (filtrado).
    """
    upper_uni = _make_custom_kpi_block(
        "Indicadores de la Universidad del Norte",
        "Totales institucionales de producción, impacto y calidad de fuente "
        "(no afectados por los filtros).",
        kpis_universidad,
        cards=["publicaciones_uni", "citas_uni", "pct_q1q2", "h_index_uni"],
    )
    upper_div = _make_custom_kpi_block(
        "Indicadores de la División de Ciencias Básicas",
        "Vista consolidada de producción, impacto y calidad de fuente de la "
        "División (reactiva a los filtros).",
        kpis_division,
        cards=["publicaciones_div", "citas_div", "pct_q1q2", "h_index"],
    )
    return html.Div([upper_uni, upper_div])


def _data_error_banner(error: str) -> html.Div:
    """Aviso visible cuando la capa de datos fallo.

    Sustituye a los KPI en 0/"—" que antes se mostraban ante cualquier
    fallo de la BD y que eran indistinguibles de "no hay publicaciones".
    """
    return html.Div(
        dbc.Card(
            dbc.CardBody(html.Div([
                html.Div("No se pudo consultar la base de datos",
                         className="empty-state-title"),
                html.P(
                    "Los indicadores no pueden calcularse en este momento. "
                    "No es un problema de los filtros seleccionados: la fuente "
                    "de datos no está respondiendo correctamente.",
                    className="empty-state-text",
                ),
                html.P(f"Detalle técnico: {error}",
                       className="empty-state-text",
                       style={"fontSize": "12px", "opacity": 0.8}),
            ], className="empty-state")),
            className="pretty-card",
        ),
        className="page-section",
    )


def _filtros_activos_descripcion(
    departamento_id: Optional[int],
    profesor_id: Optional[int],
    anios: object,
    tipos: list[str],
    cuartiles: Optional[list[str]],
) -> str:
    partes: list[str] = []
    if profesor_id is not None:
        prof_row = _get_profesor_row(profesor_id)
        nombre = (
            str(prof_row.get("nombre_normalizado"))
            if prof_row is not None else f"id {profesor_id}"
        )
        partes.append(f"profesor: {nombre}")
    if departamento_id is not None:
        partes.append(f"área: {_get_departamento_nombre(departamento_id)}")
    y0, y1 = _safe_year_range(anios)
    partes.append(f"período: {y0}–{y1}")
    if tipos:
        partes.append("tipo: " + ", ".join(tipos))
    if cuartiles:
        partes.append("cuartil: " + ", ".join(cuartiles))
    return " · ".join(partes)


def _no_results_notice(descripcion: str) -> html.Div:
    """Mensaje claro cuando la combinación de filtros deja 0 resultados."""
    return html.Div(
        dbc.Card(
            dbc.CardBody(html.Div([
                html.Div("No hay publicaciones para esta combinación de filtros",
                         className="empty-state-title"),
                html.P(
                    f"Filtros activos → {descripcion}. Ajusta o limpia los "
                    "filtros para ampliar los resultados.",
                    className="empty-state-text",
                ),
            ], className="empty-state")),
            className="pretty-card",
        ),
        className="mb-3",
    )


# ---------------------------------------------------------------------------
# Callback 1: poblar filtros
# ---------------------------------------------------------------------------


@app.callback(
    Output("filter-departamento", "options"),
    Output("filter-profesor",     "options"),
    Output("filter-tipo-doc",     "options"),
    Output("filter-profesor",     "value"),
    Input("store-active-view",    "data"),
    Input("filter-departamento",  "value"),
    State("filter-profesor",      "value"),
)
def update_filter_options(active_view, departamento_value, profesor_actual):
    del active_view
    try:
        departamento_id = _safe_int(departamento_value)

        # Cada consulta se maneja por separado: si una falla, se conservan
        # las opciones previas del dropdown (no_update) en vez de vaciarlas.
        df_dept = _get_departamentos_df()
        dept_options = (
            no_update if _df_error(df_dept)
            else _to_options(df_dept, "id_departamento", "nombre")
        )

        df_prof = _get_profesores_df(departamento_id=departamento_id)
        profesor_id_actual = _safe_int(profesor_actual)
        if _df_error(df_prof):
            # La lista de profesores no se pudo cargar: conservar opciones y,
            # sobre todo, NO borrar la selección del usuario (antes esto
            # reseteaba el profesor a None ante cualquier fallo de la BD, lo
            # que dejaba el perfil en "Selecciona un profesor").
            logger.warning(
                "Lista de profesores no disponible; se conserva la selección "
                "actual (%s). Error: %s",
                profesor_id_actual, _df_error(df_prof),
            )
            prof_options = no_update
            profesor_value = no_update
        else:
            prof_options = _to_options(df_prof, "id_profesor", "nombre_normalizado")
            valid_prof_ids = {opt["value"] for opt in prof_options}
            profesor_value = (
                profesor_id_actual if profesor_id_actual in valid_prof_ids else None
            )

        df_tipos = queries.get_publicaciones(departamento_id=departamento_id)
        df_tipos = df_tipos if isinstance(df_tipos, pd.DataFrame) else pd.DataFrame()
        tipo_options = no_update if _df_error(df_tipos) else _tipo_options(df_tipos)

        return dept_options, prof_options, tipo_options, profesor_value

    except Exception as exc:
        # Nunca vaciar filtros ni selección por un error de este callback.
        logger.exception("Error actualizando opciones de filtros: %s", exc)
        return no_update, no_update, no_update, no_update


# ---------------------------------------------------------------------------
# Callback 2: KPIs globales + contenido dinámico de tabs
# ---------------------------------------------------------------------------


@app.callback(
    Output("kpi-upper-block",      "children"),
    Output("kpi-context-block",    "children"),
    Output("content-resumen",      "children"),
    Output("content-profesor",     "children"),
    Output("content-impacto",      "children"),
    Output("content-fuentes",      "children"),
    Output("content-colaboracion", "children"),
    Output("content-benchmarking", "children"),
    # Output("content-matching",   "children"),  # vista "Calidad de Datos" oculta
    Output("content-explorador",   "children"),
    Input("store-active-view",     "data"),
    Input("filter-departamento",   "value"),
    Input("filter-profesor",       "value"),
    Input("filter-anio-desde",     "value"),
    Input("filter-anio-hasta",     "value"),
    Input("filter-tipo-doc",       "value"),
    Input("filter-cuartil",        "value"),
)
def update_dashboard_content(
    active_tab, departamento_value, profesor_value,
    anio_desde, anio_hasta, tipos_value, cuartil_value,
):
    try:
        departamento_id = _safe_int(departamento_value)
        profesor_id     = _safe_int(profesor_value)
        tipos           = _normalize_multi(tipos_value)
        cuartiles       = _normalize_multi(cuartil_value)
        anio_desde_i    = _safe_int(anio_desde)
        anio_hasta_i    = _safe_int(anio_hasta)
        anios_value     = [
            anio_desde_i if anio_desde_i is not None else _ANIO_MIN_RESET,
            anio_hasta_i if anio_hasta_i is not None else _ANIO_MAX_RESET,
        ]

        base_df = _fetch_publicaciones(
            departamento_id=departamento_id,
            profesor_id=profesor_id,
            anios=anios_value,
            tipos=tipos,
            cuartiles=cuartiles,
        )

        # Si la capa de datos falló, mostrar un aviso claro en vez de KPIs en
        # 0/"—" que parecen datos legítimos. El tab activo recibe el mismo
        # aviso (evita que "Perfil Profesor" quede en su placeholder inicial).
        data_error = _df_error(base_df)
        if data_error:
            logger.error("Capa de datos no disponible: %s", data_error)
            contents = {t: no_update for t in _NAV_TABS}
            if active_tab in contents:
                contents[active_tab] = _data_error_banner(data_error)
            return (
                _data_error_banner(data_error),
                html.Div(style={"display": "none"}),
                contents["tab-resumen"], contents["tab-profesor"],
                contents["tab-impacto"], contents["tab-fuentes"],
                contents["tab-colaboracion"], contents["tab-benchmarking"],
                contents["tab-explorador"],
            )

        # --- Bloques KPI según jerarquía de filtros ---
        suffix = _year_suffix(anios_value)
        if profesor_id is not None:
            # Caso 3: profesor seleccionado
            prof_row = _get_profesor_row(profesor_id)
            dept_id_upper = (
                _safe_int(prof_row.get("id_departamento"))
                if prof_row is not None else departamento_id
            )
            dept_name = (
                str(prof_row.get("nombre_departamento", ""))
                if prof_row is not None and pd.notna(prof_row.get("nombre_departamento"))
                else _get_departamento_nombre(dept_id_upper)
            )
            prof_name = (
                str(prof_row.get("nombre_normalizado", "Profesor"))
                if prof_row is not None else "Profesor"
            )
            kpis_upper = _compute_global_kpis(anios_value, tipos, cuartiles, departamento_id=dept_id_upper)
            kpis_upper["h_index_label"] = f"H-index Depto.{suffix}"
            kpis_context = _compute_profesor_kpis(profesor_id, anios_value, tipos, cuartiles)
            kpis_context["h_index_label"] = f"H-index Profesor{suffix}"
            upper_block = _make_kpi_block(
                f"Indicadores · {dept_name}",
                "Indicadores del área de investigación para el período y filtros activos.",
                kpis_upper,
            )
            context_block = _make_kpi_block(
                f"Indicadores · {prof_name}",
                "Indicadores individuales del profesor para el período filtrado.",
                kpis_context,
            )

        elif departamento_id is not None:
            # Caso 2: solo departamento seleccionado
            dept_name = _get_departamento_nombre(departamento_id)
            kpis_division = _compute_global_kpis(anios_value, tipos, cuartiles)
            kpis_division["h_index_label"] = f"H-index{suffix}" if suffix else "H-index División"
            kpis_dept = _compute_global_kpis(anios_value, tipos, cuartiles, departamento_id=departamento_id)
            kpis_dept["h_index_label"] = f"H-index Depto.{suffix}"
            upper_block = _make_division_summary_blocks(kpis_division, _compute_universidad_kpis())
            context_block = _make_kpi_block(
                f"Indicadores · {dept_name}",
                "Indicadores del área de investigación para el período y filtros activos.",
                kpis_dept,
            )

        else:
            # Caso 1: sin filtro
            kpis_division = _compute_global_kpis(anios_value, tipos, cuartiles)
            kpis_division["h_index_label"] = f"H-index{suffix}" if suffix else "H-index División"
            upper_block = _make_division_summary_blocks(kpis_division, _compute_universidad_kpis())
            context_block = html.Div(style={"display": "none"})

        # Cero resultados legítimos (la BD respondió pero la combinación de
        # filtros no deja registros): avisar de forma explícita.
        if base_df.empty:
            aviso = _no_results_notice(_filtros_activos_descripcion(
                departamento_id, profesor_id, anios_value, tipos, cuartiles,
            ))
            upper_block = html.Div([aviso, upper_block])

        c_resumen = c_profesor = c_impacto = c_fuentes = no_update
        c_colab   = c_bench   = c_explorador = no_update
        c_matching = no_update  # vista "Calidad de Datos" oculta (no se emite como Output)

        if active_tab == "tab-resumen":
            c_resumen = layout_resumen(
                _build_resumen_data(departamento_id, profesor_id, anios_value, tipos, cuartiles)
            )

        elif active_tab == "tab-profesor":
            if profesor_id is None:
                c_profesor = layout_profesor(None)
            else:
                c_profesor = layout_profesor(
                    _build_profesor_data(departamento_id, profesor_id, anios_value, tipos, cuartiles)
                )

        elif active_tab == "tab-impacto":
            c_impacto = layout_impacto(
                _build_impacto_data(departamento_id, profesor_id, anios_value, tipos, cuartiles)
            )

        elif active_tab == "tab-fuentes":
            c_fuentes = layout_fuentes(
                _build_fuentes_data(departamento_id, profesor_id, anios_value, tipos, cuartiles)
            )

        elif active_tab == "tab-colaboracion":
            c_colab = layout_colaboracion(
                _build_colaboracion_data(departamento_id, profesor_id, anios_value, tipos, cuartiles)
            )

        elif active_tab == "tab-benchmarking":
            c_bench = layout_benchmarking(
                _build_benchmarking_data(departamento_id, profesor_id, anios_value, tipos, cuartiles)
            )

        # Vista "Calidad de Datos" oculta temporalmente; se conserva la lógica.
        # elif active_tab == "tab-matching":
        #     c_matching = layout_matching(_build_matching_data())

        elif active_tab == "tab-explorador":
            c_explorador = layout_explorador(base_df)

        return (
            upper_block, context_block,
            c_resumen, c_profesor, c_impacto,
            c_fuentes, c_colab, c_bench, c_explorador,
        )

    except Exception as exc:
        logger.exception("Error actualizando dashboard: %s", exc)

        # Antes este fallback pintaba los KPIs de la División con un DataFrame
        # vacío (todo 0/"—"), indistinguible de datos reales. Ahora se muestra
        # un aviso de error explícito.
        return (
            _data_error_banner(f"Error interno del dashboard: {exc}"),
            html.Div(style={"display": "none"}),
            no_update, no_update, no_update, no_update,
            no_update, no_update, no_update,
        )


# ---------------------------------------------------------------------------
# Callbacks de navegación sidebar
# ---------------------------------------------------------------------------

_NAV_TABS = [
    "tab-resumen", "tab-profesor", "tab-impacto", "tab-fuentes",
    "tab-colaboracion", "tab-benchmarking", "tab-explorador",
    # "tab-matching" oculto temporalmente (ver _NAV_ITEMS en index.py).
]

_BREADCRUMB_LABELS = {
    "tab-resumen":      "Visión General",
    "tab-profesor":     "Perfil Profesor",
    "tab-impacto":      "Impacto",
    "tab-fuentes":      "Calidad de Fuente",
    "tab-colaboracion": "Colaboración",
    "tab-benchmarking": "Rankings",
    # "tab-matching":   "Calidad de Datos",  # oculto temporalmente
    "tab-explorador":   "Explorador",
}

_ANIO_MIN_RESET = 2014
_ANIO_MAX_RESET = 2025


@app.callback(
    Output("store-active-view", "data", allow_duplicate=True),
    [Input(f"nav-{t}", "n_clicks") for t in _NAV_TABS],
    prevent_initial_call=True,
)
def _nav_click(*_):
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
    return triggered_id[4:]  # "nav-tab-resumen" → "tab-resumen"


@app.callback(
    [Output(f"nav-{t}", "className") for t in _NAV_TABS],
    Input("store-active-view", "data"),
)
def _update_nav_classes(active_view: str) -> list[str]:
    return [
        "nav-item active" if t == active_view else "nav-item"
        for t in _NAV_TABS
    ]


@app.callback(
    [Output(f"panel-{t.replace('tab-', '')}", "style") for t in _NAV_TABS],
    Input("store-active-view", "data"),
)
def _toggle_panels(active_view: str) -> list[dict]:
    return [
        {"display": "block"} if t == active_view else {"display": "none"}
        for t in _NAV_TABS
    ]


@app.callback(
    Output("breadcrumb-current", "children"),
    Input("store-active-view", "data"),
)
def _update_breadcrumb(active_view: str) -> str:
    return _BREADCRUMB_LABELS.get(active_view, "Visión General")


# ---------------------------------------------------------------------------
# Sidebar móvil (drawer): abrir con la hamburguesa, cerrar con el overlay o al
# navegar a otra vista. En escritorio el CSS ignora estas clases.
# ---------------------------------------------------------------------------


@app.callback(
    Output("store-sidebar-open", "data"),
    Input("sidebar-toggle",  "n_clicks"),
    Input("sidebar-overlay", "n_clicks"),
    *[Input(f"nav-{t}", "n_clicks") for t in _NAV_TABS],
    State("store-sidebar-open", "data"),
    prevent_initial_call=True,
)
def _toggle_sidebar(*args):
    is_open = bool(args[-1])
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    # La hamburguesa alterna; cualquier otro disparador (overlay o navegación)
    # cierra el drawer.
    return (not is_open) if trigger == "sidebar-toggle" else False


@app.callback(
    Output("sidebar",         "className"),
    Output("sidebar-overlay", "className"),
    Input("store-sidebar-open", "data"),
)
def _apply_sidebar_state(is_open: bool) -> tuple[str, str]:
    if is_open:
        return "sidebar-open", "sidebar-overlay visible"
    return "", "sidebar-overlay"


@app.callback(
    Output("filter-departamento",  "value", allow_duplicate=True),
    Output("filter-profesor",      "value", allow_duplicate=True),
    Output("filter-anio-desde",    "value", allow_duplicate=True),
    Output("filter-anio-hasta",    "value", allow_duplicate=True),
    Output("filter-tipo-doc",      "value", allow_duplicate=True),
    Output("filter-cuartil",       "value", allow_duplicate=True),
    Input("btn-reset-filters",     "n_clicks"),
    prevent_initial_call=True,
)
def _reset_filters(_: int):
    return None, None, _ANIO_MIN_RESET, _ANIO_MAX_RESET, None, None


@app.callback(
    Output("filter-anio-hasta", "options"),
    Output("filter-anio-hasta", "value"),
    Input("filter-anio-desde",  "value"),
    State("filter-anio-hasta",  "value"),
)
def _constrain_hasta_options(desde_value, hasta_value):
    desde = desde_value if desde_value is not None else _ANIO_MIN_RESET
    hasta = hasta_value if hasta_value is not None else _ANIO_MAX_RESET
    options = [{"label": str(y), "value": y} for y in range(desde, _ANIO_MAX_RESET + 1)]
    return options, max(hasta, desde)


# ---------------------------------------------------------------------------
# Callback: reordenar el ranking de Rankings/Benchmarking
#
# El ranking se renderiza dentro del Output "content-benchmarking" del callback
# principal. Para evitar una dependencia circular (el selector vive dentro de
# ese mismo Output), el DataFrame se guarda en "store-ranking-data" al construir
# la tarjeta y este callback dedicado reordena la tabla a partir del Store y del
# selector, sin reconsultar datos.
# ---------------------------------------------------------------------------


@app.callback(
    Output("ranking-table-body",   "children"),
    Output("ranking-sort-caption", "children"),
    Input("ranking-sort-metric",   "value"),
    Input("store-ranking-data",    "data"),
)
def _update_ranking_table(sort_by, data):
    df = pd.DataFrame(data) if data else pd.DataFrame()
    return build_ranking_table_body(df, sort_by), ranking_caption(sort_by)


# ---------------------------------------------------------------------------
# Callback: acción de detalle en las tablas de ranking → navegar a perfil
#
# Dos patrones porque las pestañas inactivas conservan su contenido en el DOM
# (no_update): el nombre-enlace del Resumen ("prof-ranking-link") y el botón
# de detalle de Rankings ("prof-detail-btn") deben tener IDs distintos aunque
# apunten al mismo profesor.
# ---------------------------------------------------------------------------


@app.callback(
    Output("store-active-view", "data", allow_duplicate=True),
    Output("filter-profesor",   "value", allow_duplicate=True),
    Input({"type": "prof-ranking-link", "index": ALL}, "n_clicks"),
    Input({"type": "prof-detail-btn",   "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _navigate_to_professor(n_clicks_list, n_clicks_btns):
    import json

    ctx = callback_context
    if not ctx.triggered:
        return no_update, no_update

    triggered = ctx.triggered[0]
    if not triggered["value"]:
        return no_update, no_update

    prop_id_str = triggered["prop_id"].rsplit(".", 1)[0]
    try:
        id_dict = json.loads(prop_id_str)
        prof_id = id_dict["index"]
    except Exception:
        return no_update, no_update

    return "tab-profesor", prof_id
