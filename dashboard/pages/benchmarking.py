"""
Tab: Rankings y Benchmarking.

Ranking de profesores con índice compuesto + radar chart por departamento.
"""
from __future__ import annotations

import json

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from dashboard.area_style import pill_area
from src.utils.logger import get_logger

logger = get_logger(__name__)

_PRIMARY   = "#003865"
_SECONDARY = "#0066B3"
_ACCENT    = "#F5A800"
_SUCCESS   = "#10B981"
_FONT      = "'DM Sans', 'Segoe UI', Arial, sans-serif"
_TEXT      = "#1A1A2E"
_GRID      = "#F3F4F6"
_PAPER     = "#FFFFFF"

PALETA = [_PRIMARY, _SECONDARY, _ACCENT, _SUCCESS, "#8B5CF6", "#EF4444"]

_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def layout_benchmarking(data: dict) -> html.Div:
    logger.info("Renderizando layout_benchmarking")

    ranking = data.get("ranking", pd.DataFrame())
    radar   = data.get("radar", {})

    return html.Div([
        html.Div([
            html.H4("Rankings y Benchmarking", className="section-header-title"),
            html.P(
                "Índice de impacto compuesto por profesor y comparativa multidimensional por área de investigación.",
                className="section-header-subtitle",
            ),
        ], className="section-header-inline"),

        html.Div([
            dbc.Row([
                dbc.Col(_card_ranking(ranking), md=7),
                dbc.Col(_card_radar(radar), md=5),
            ], className="g-3 mb-3"),
        ], className="page-section section-stack"),
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
    ``citas_totales`` o ``pct_q1q2``. Recalcula posiciones (#, medallas) tras
    ordenar de mayor a menor. Tolera DataFrames vacíos (datos sin BD).
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

    # Tendencia: comparar pubs últimas ventana vs anterior
    if "pubs_recientes" in df.columns and "pubs_anteriores" in df.columns:
        def _tend(row):
            r, a = row["pubs_recientes"], row["pubs_anteriores"]
            if a == 0:
                return "↑" if r > 0 else "→"
            d = (r - a) / a
            if d > 0.1:   return "↑"
            if d < -0.1:  return "↓"
            return "→"
        df["tendencia"] = df.apply(_tend, axis=1)
    else:
        df["tendencia"] = "→"

    def _tend_class(t):
        return {"↑": "trend-up", "↓": "trend-down", "→": "trend-flat"}.get(t, "trend-flat")

    header = html.Thead(html.Tr([
        html.Th("#"),
        html.Th("Profesor"),
        html.Th("Dept."),
        html.Th("h-index"),
        html.Th("Citas"),
        html.Th("% Q1+Q2"),
        html.Th(""),
    ]))

    rows = []
    for _, row in df.iterrows():
        rank = int(row["rank"])
        medal = _MEDALS.get(rank, "")
        dept  = str(row.get("departamento", ""))
        short_dept = pill_area(dept)[0] if dept else "—"

        h_val = row.get("h_index")
        c_val = row.get("citas_totales")
        q_val = row.get("pct_q1q2")
        tend  = row.get("tendencia", "→")

        cells = [
            html.Td(html.Span(f"{medal} {rank}" if medal else str(rank),
                              className="rank-number")),
            html.Td(str(row.get("nombre_normalizado", ""))[:30],
                    style={"fontWeight": "500"}),
            html.Td(html.Span(short_dept, style={"fontSize": "11px", "color": "#6B7280"})),
            html.Td(f"{int(h_val):,}" if pd.notna(h_val) else "—"),
            html.Td(f"{int(c_val):,}" if pd.notna(c_val) else "—"),
            html.Td(f"{q_val:.0%}" if pd.notna(q_val) else "—"),
            html.Td(html.Span(tend, className=_tend_class(tend))),
        ]
        rows.append(html.Tr(cells))

    return dbc.Table(
        [header, html.Tbody(rows)],
        bordered=False, hover=True, striped=False,
        responsive=True, size="sm", className="mb-0 align-middle",
    )


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


# ---------------------------------------------------------------------------
# Radar / Spider chart por departamento
# ---------------------------------------------------------------------------

def _card_radar(radar: dict) -> dbc.Card:
    """
    radar = {
        "departamentos": [...],
        "dimensiones": ["Volumen","Impacto","Calidad","h-index","Tendencia"],
        "valores": [[d1_dim1,...,d1_dim5], ...],   # normalizados 0-1 (/ máximo)
        "crudos":  [[d1_dim1,...,d1_dim5], ...],   # valores sin normalizar
    }

    Las definiciones y la normalización de cada dimensión están
    documentadas en ``filter_callbacks._build_benchmarking_data`` y en
    ``docs/definiciones_indicadores.md``.
    """
    deptos = radar.get("departamentos", [])
    dims   = radar.get("dimensiones", [])
    vals   = radar.get("valores", [])
    crudos = radar.get("crudos", [])

    if not deptos or not dims or not vals:
        return _card_vacia("Radar comparativo", "Sin datos para el radar chart.")

    fig = go.Figure()

    for i, (dept, row_vals) in enumerate(zip(deptos, vals)):
        color = PALETA[i % len(PALETA)]
        # Cerrar el polígono repitiendo el primer valor
        r_closed = list(row_vals) + [row_vals[0]]
        t_closed = list(dims) + [dims[0]]
        raw = list(crudos[i]) if i < len(crudos) else [None] * len(row_vals)
        raw_closed = raw + raw[:1]

        fig.add_trace(go.Scatterpolar(
            r=r_closed,
            theta=t_closed,
            fill="toself",
            fillcolor=color,
            line=dict(color=color, width=2.5),
            opacity=0.25,
            name=dept,
            customdata=[[f"{v:,.2f}" if isinstance(v, (int, float)) else "—"]
                        for v in raw_closed],
            hovertemplate=("<b>%{theta}</b>: %{r:.2f} "
                           "(valor real: %{customdata[0]})<extra>" + str(dept) + "</extra>"),
        ))
        # Línea sólida sin fill encima
        fig.add_trace(go.Scatterpolar(
            r=r_closed, theta=t_closed,
            mode="lines",
            line=dict(color=color, width=2.5),
            showlegend=False,
            hoverinfo="skip",
        ))

    fig.update_layout(
        polar=dict(
            bgcolor="white",
            radialaxis=dict(
                visible=True, range=[0, 1],
                tickfont=dict(size=9, family=_FONT, color="#9CA3AF"),
                gridcolor="#E5E7EB", linecolor="#E5E7EB",
                tickvals=[0, 0.25, 0.5, 0.75, 1],
                ticktext=["0", "0.25", "0.5", "0.75", "1"],
            ),
            angularaxis=dict(
                tickfont=dict(size=11, family=_FONT, color=_TEXT),
                gridcolor="#E5E7EB", linecolor="#E5E7EB",
            ),
        ),
        paper_bgcolor=_PAPER,
        height=420,
        font=dict(family=_FONT, color=_TEXT, size=12),
        margin=dict(t=36, b=36, l=48, r=48),
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.12,
            xanchor="center", x=0.5,
            font=dict(size=11),
        ),
        hoverlabel=dict(bgcolor="#1A1A2E", font_color="white", font_size=12),
    )

    return dbc.Card([
        _pretty_header(
            "Perfil multidimensional por área de investigación",
            "Compara siempre las 3 áreas con los filtros de período/tipo/cuartil. "
            "Cada eje se normaliza por el máximo entre áreas (1.0 = área líder del eje). "
            "Volumen = publicaciones · Impacto = citas/publicación · Calidad = % Q1+Q2 · "
            "h-index = h-index del área calculado del período · "
            "Tendencia = pubs último trienio / trienio anterior",
        ),
        dbc.CardBody(html.Div(
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            className="plot-shell",
        )),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pretty_header(title: str, subtitle: str) -> dbc.CardHeader:
    return dbc.CardHeader(html.Div([
        html.H5(title, className="card-title-main"),
        html.P(subtitle, className="card-title-sub"),
    ], className="card-title-block"))


def _card_vacia(title: str, message: str) -> dbc.Card:
    return dbc.Card([
        _pretty_header(title, "Estado del componente"),
        dbc.CardBody(html.Div([
            html.Div("Sin datos disponibles", className="empty-state-title"),
            html.P(message, className="empty-state-text"),
        ], className="empty-state")),
    ], className="pretty-card")
