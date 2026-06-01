"""
Tab: Rankings y Benchmarking.

Ranking de profesores con índice compuesto + radar chart por departamento.
"""
from __future__ import annotations

from typing import Dict, List

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

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

COLORES_DEPT: Dict[str, str] = {
    "Departamento de Matemáticas y Estadística": _PRIMARY,
    "Departamento de Química y Biología":        _SECONDARY,
    "Departamento de Física y Geociencias":      _ACCENT,
}
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
                "Índice de impacto compuesto por profesor y comparativa multidimensional por departamento.",
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
# Tabla de ranking con índice compuesto
# ---------------------------------------------------------------------------

def _card_ranking(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Ranking de profesores", "Sin datos para construir el ranking.")

    # Normalizar (0-1) para el índice compuesto
    def _norm(col: pd.Series) -> pd.Series:
        mx = col.max()
        if mx == 0 or pd.isna(mx):
            return pd.Series(0.0, index=col.index)
        return col.fillna(0) / mx

    h_norm   = _norm(pd.to_numeric(df.get("h_index", 0), errors="coerce"))
    c_norm   = _norm(pd.to_numeric(df.get("citas_totales", 0), errors="coerce"))
    q_norm   = _norm(pd.to_numeric(df.get("pct_q1q2", 0), errors="coerce"))

    df = df.copy()
    df["indice"] = (0.4 * h_norm + 0.3 * c_norm + 0.3 * q_norm).round(3)
    df = df.sort_values("indice", ascending=False).reset_index(drop=True)
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
        html.Th("Índice"),
        html.Th(""),
    ]))

    rows = []
    for _, row in df.iterrows():
        rank = int(row["rank"])
        medal = _MEDALS.get(rank, "")
        dept  = str(row.get("departamento", ""))
        short_dept = dept.split()[-1][:6] if dept else "—"

        h_val = row.get("h_index")
        c_val = row.get("citas_totales")
        q_val = row.get("pct_q1q2")
        ind   = row.get("indice", 0)
        tend  = row.get("tendencia", "→")

        # Barra de índice (anchura proporcional)
        bar_w = max(4, int(ind * 60))

        cells = [
            html.Td(html.Span(f"{medal} {rank}" if medal else str(rank),
                              className="rank-number")),
            html.Td(str(row.get("nombre_normalizado", ""))[:30],
                    style={"fontWeight": "500"}),
            html.Td(html.Span(short_dept, style={"fontSize": "11px", "color": "#6B7280"})),
            html.Td(f"{int(h_val):,}" if pd.notna(h_val) else "—"),
            html.Td(f"{int(c_val):,}" if pd.notna(c_val) else "—"),
            html.Td(f"{q_val:.0%}" if pd.notna(q_val) else "—"),
            html.Td(html.Div([
                html.Span(f"{ind:.3f}", style={"fontWeight": "600", "marginRight": "6px"}),
                html.Span(className="indice-bar", style={"width": f"{bar_w}px"}),
            ], style={"display": "flex", "alignItems": "center"})),
            html.Td(html.Span(tend, className=_tend_class(tend))),
        ]
        rows.append(html.Tr(cells))

    return dbc.Card([
        html.Div([
            html.Div([
                html.H5("Ranking de profesores", className="table-toolbar-title"),
                html.P(
                    "Índice compuesto = 0.4×h-index + 0.3×citas + 0.3×%Q1Q2 (normalizados).",
                    className="table-toolbar-subtitle",
                ),
            ]),
        ], className="table-toolbar"),
        dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, hover=True, striped=False,
            responsive=True, size="sm", className="mb-0 align-middle",
        ),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Radar / Spider chart por departamento
# ---------------------------------------------------------------------------

def _card_radar(radar: dict) -> dbc.Card:
    """
    radar = {
        "departamentos": [...],
        "dimensiones": ["Volumen","Impacto","Calidad","h-index","Colaboración","Tendencia"],
        "valores": [[d1_dim1,...,d1_dim6], [d2_dim1,...], ...]
    }
    """
    deptos = radar.get("departamentos", [])
    dims   = radar.get("dimensiones", [])
    vals   = radar.get("valores", [])

    if not deptos or not dims or not vals:
        return _card_vacia("Radar comparativo", "Sin datos para el radar chart.")

    fig = go.Figure()

    for i, (dept, row_vals) in enumerate(zip(deptos, vals)):
        color = PALETA[i % len(PALETA)]
        # Cerrar el polígono repitiendo el primer valor
        r_closed = list(row_vals) + [row_vals[0]]
        t_closed = list(dims) + [dims[0]]

        # Formato corto del nombre de departamento
        short = dept.split()[-2] if len(dept.split()) >= 2 else dept[:10]

        fig.add_trace(go.Scatterpolar(
            r=r_closed,
            theta=t_closed,
            fill="toself",
            fillcolor=color,
            line=dict(color=color, width=2.5),
            opacity=0.25,
            name=short,
            hovertemplate="<b>%{theta}</b>: %{r:.2f}<extra></extra>",
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
            "Perfil multidimensional por departamento",
            "6 dimensiones normalizadas (0–1): Volumen · Impacto · Calidad · h-index · Colaboración · Tendencia",
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
