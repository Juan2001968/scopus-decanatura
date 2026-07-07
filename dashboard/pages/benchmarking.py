"""
Tab: Rankings y Benchmarking.

Ranking de profesores de la División con métrica de orden seleccionable.
"""
from __future__ import annotations

import json

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html

from dashboard.area_style import abreviar_area, pill_area
from src.utils.logger import get_logger

logger = get_logger(__name__)


def layout_benchmarking(data: dict) -> html.Div:
    logger.info("Renderizando layout_benchmarking")

    ranking = data.get("ranking", pd.DataFrame())

    return html.Div([
        html.Div([
            html.H4("Rankings y Benchmarking", className="section-header-title"),
            html.P(
                "Ranking de profesores de la División según las métricas de impacto del período filtrado.",
                className="section-header-subtitle",
            ),
        ], className="section-header-inline"),

        html.Div(
            _card_ranking(ranking),
            className="page-section section-stack",
        ),
    ])


# ---------------------------------------------------------------------------
# Tabla de ranking con métrica de orden seleccionable
# ---------------------------------------------------------------------------

# Métricas por las que se puede ordenar el ranking. La clave (value) mapea a la
# columna real del DataFrame; la etiqueta (label) es lo que ve el usuario.
_SORT_OPTIONS = [
    {"label": "h-index", "value": "h_index"},
    {"label": "Citas",   "value": "citas_totales"},
    {"label": "% Q1+Q2", "value": "pct_q1q2"},
]
_SORT_LABELS = {opt["value"]: opt["label"] for opt in _SORT_OPTIONS}
_DEFAULT_SORT = "h_index"


def ranking_caption(sort_by: str) -> str:
    """Subtítulo de la tarjeta del ranking según la métrica de orden."""
    label = _SORT_LABELS.get(sort_by, _SORT_LABELS[_DEFAULT_SORT])
    return (f"Ordenado por: {label} · h-index calculado del período "
            "(mayor h con h publicaciones de ≥ h citas)")


def build_ranking_table_body(df: pd.DataFrame, sort_by: str = _DEFAULT_SORT):
    """Construye el cuerpo de la tabla de ranking ordenado por la métrica dada.

    ``sort_by`` debe ser una de las columnas reales: ``h_index``,
    ``citas_totales`` o ``pct_q1q2``. Recalcula posiciones (#) tras ordenar
    de mayor a menor. Tolera DataFrames vacíos (datos sin BD).
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return html.Div([
            html.Div("Sin datos disponibles", className="empty-state-title"),
            html.P("Sin datos para construir el ranking.", className="empty-state-text"),
        ], className="empty-state")

    sort_col = sort_by if sort_by in _SORT_LABELS else _DEFAULT_SORT

    df = df.copy()
    df[sort_col] = pd.to_numeric(df.get(sort_col, 0), errors="coerce")
    df = df.sort_values(sort_col, ascending=False, na_position="last").reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    header = html.Thead(html.Tr([
        html.Th("#", scope="col", className="col-rank"),
        html.Th("Profesor", scope="col"),
        html.Th("h-index", scope="col", className="col-num"),
        html.Th("Citas", scope="col", className="col-num"),
        html.Th("% Q1+Q2", scope="col", className="col-num"),
        html.Th(html.Span("Ver perfil", className="visually-hidden"),
                scope="col", className="col-action"),
    ]))

    rows = [_ranking_row(row) for _, row in df.iterrows()]

    table = dbc.Table(
        [header, html.Tbody(rows)],
        bordered=False, hover=False, striped=False,
        size="sm", className="ranking-table mb-0",
    )
    # El div exterior es el contenedor de scroll: fija la altura para el
    # header sticky y da scroll horizontal en pantallas angostas.
    return html.Div(table, className="ranking-table-scroll")


def _ranking_row(row: pd.Series) -> html.Tr:
    rank   = int(row["rank"])
    nombre = str(row.get("nombre_normalizado", "") or "")
    dept   = str(row.get("departamento", "") or "")

    prof_id = row.get("id_profesor")
    prof_id = int(prof_id) if pd.notna(prof_id) else None

    h_val = row.get("h_index")
    c_val = row.get("citas_totales")
    q_val = row.get("pct_q1q2")

    # Columna Profesor: nombre dominante + área como etiqueta discreta.
    prof_children: list = [html.Span(nombre, className="prof-name")]
    if dept:
        _, area_color, area_bg = pill_area(dept)
        prof_children.append(html.Span(
            abreviar_area(dept),
            className="area-tag",
            style={"color": area_color, "background": area_bg},
        ))

    # % Q1+Q2: valor numérico siempre visible + barra fina monocroma
    # (decorativa: oculta a lectores de pantalla).
    if pd.notna(q_val):
        pct = min(max(float(q_val), 0.0), 1.0)
        q_children = [
            html.Span(f"{float(q_val):.0%}", className="q-value"),
            html.Span(
                html.Span(className="q-bar-fill", style={"width": f"{pct:.0%}"}),
                className="q-bar",
                **{"aria-hidden": "true"},
            ),
        ]
    else:
        q_children = [html.Span("—", className="q-value")]

    # Acción de detalle: navega al perfil del profesor (callback
    # filter_callbacks._navigate_to_professor, patrón "prof-detail-btn").
    action = html.Button(
        "→",
        id={"type": "prof-detail-btn", "index": prof_id},
        n_clicks=0,
        className="row-action",
        title=f"Ver perfil de {nombre}",
        **{"aria-label": f"Ver perfil de {nombre}"},
    ) if prof_id else None

    return html.Tr([
        html.Td(str(rank), className="cell-rank"),
        html.Td(html.Div(prof_children, className="prof-cell")),
        html.Td(f"{int(h_val):,}" if pd.notna(h_val) else "—",
                className="cell-num cell-hindex"),
        html.Td(f"{int(c_val):,}" if pd.notna(c_val) else "—",
                className="cell-num"),
        html.Td(html.Div(q_children, className="q-cell"), className="cell-num"),
        html.Td(action, className="cell-action"),
    ], className="rank-top" if rank <= 3 else None)


def _card_ranking(df: pd.DataFrame) -> dbc.Card:
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()

    # El DataFrame se guarda en un dcc.Store; el reordenamiento lo hace un
    # callback dedicado (ver filter_callbacks._update_ranking_table) para evitar
    # dependencias circulares con el callback que renderiza esta tarjeta.
    records = json.loads(df.to_json(orient="records")) if not df.empty else []

    return dbc.Card([
        dcc.Store(id="store-ranking-data", data=records),
        html.Div([
            html.Div([
                html.H5("Ranking de profesores", className="table-toolbar-title"),
                html.P(
                    ranking_caption(_DEFAULT_SORT),
                    id="ranking-sort-caption",
                    className="table-toolbar-subtitle",
                ),
            ]),
            html.Div([
                html.Label("Ordenar por", className="ranking-sort-label"),
                dcc.Dropdown(
                    id="ranking-sort-metric",
                    options=_SORT_OPTIONS,
                    value=_DEFAULT_SORT,
                    clearable=False,
                    searchable=False,
                    style={"minWidth": "150px"},
                ),
            ], className="ranking-sort-control"),
        ], className="table-toolbar"),
        html.Div(
            build_ranking_table_body(df, _DEFAULT_SORT),
            id="ranking-table-body",
        ),
    ], className="pretty-card table-card")
