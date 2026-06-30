"""
Tab: Calidad de Datos (Matching).

Diagnóstico del matching publicación-profesor:
semáforo de cobertura, KPIs de calidad y tabla de casos problemáticos.
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html

from src.utils.logger import get_logger

logger = get_logger(__name__)

_PRIMARY   = "#003865"
_SECONDARY = "#0066B3"
_ACCENT    = "#F5A800"
_SUCCESS   = "#10B981"
_WARNING   = "#F59E0B"
_DANGER    = "#EF4444"
_FONT      = "'DM Sans', 'Segoe UI', Arial, sans-serif"
_TEXT      = "#1A1A2E"


def layout_matching(data: dict) -> html.Div:
    logger.info("Renderizando layout_matching")

    kpis  = data.get("kpis", {})
    tabla = data.get("tabla", pd.DataFrame())

    pct_match = kpis.get("pct_match", 0.0)

    return html.Div([
        html.Div([
            html.H4("Calidad de datos y matching", className="section-header-title"),
            html.P(
                "Diagnóstico de la cobertura de vinculación publicación-profesor.",
                className="section-header-subtitle",
            ),
        ], className="section-header-inline"),

        html.Div([
            # Semáforo + KPIs en fila
            dbc.Row([
                dbc.Col(_card_semaforo(pct_match), md=4),
                dbc.Col(_card_kpis_matching(kpis), md=8),
            ], className="g-3 mb-3"),

            # Tabla de casos problemáticos
            _card_tabla_matching(tabla),
        ], className="page-section section-stack"),
    ])


# ---------------------------------------------------------------------------
# Semáforo visual
# ---------------------------------------------------------------------------

def _card_semaforo(pct_match: float) -> dbc.Card:
    if pct_match >= 0.90:
        estado, clase = "Cobertura alta", "verde"
        msg = f"{pct_match:.1%} de profesores con publicaciones vinculadas."
        text_color = _SUCCESS
    elif pct_match >= 0.70:
        estado, clase = "Cobertura media", "ambar"
        msg = f"{pct_match:.1%} de profesores con publicaciones vinculadas."
        text_color = _WARNING
    else:
        estado, clase = "Cobertura baja", "rojo"
        msg = f"{pct_match:.1%} de profesores con publicaciones vinculadas. Revisar casos críticos."
        text_color = _DANGER

    semaforo = html.Div([
        html.Div([
            html.Div(className=f"semaforo-light verde {'active' if clase=='verde' else ''}"),
            html.Div(className=f"semaforo-light ambar {'active' if clase=='ambar' else ''}"),
            html.Div(className=f"semaforo-light rojo  {'active' if clase=='rojo'  else ''}"),
        ], className="semaforo-wrap"),
        html.P(estado, className="semaforo-label", style={"color": text_color}),
        html.P(msg, style={"fontSize": "12px", "color": "#6B7280",
                           "textAlign": "center", "marginTop": "4px"}),
    ])

    return dbc.Card([
        _pretty_header("Estado del matching", "Semáforo de cobertura"),
        dbc.CardBody(semaforo),
    ], className="pretty-card")


# ---------------------------------------------------------------------------
# KPI cards de calidad
# ---------------------------------------------------------------------------

def _card_kpis_matching(kpis: dict) -> dbc.Card:
    total_prof     = kpis.get("total_profesores", 0)
    prof_con_pubs  = kpis.get("profesores_con_pubs", 0)
    prof_sin_pubs  = kpis.get("profesores_sin_pubs", 0)
    total_pubs     = kpis.get("total_publicaciones", 0)
    pubs_vinculadas= kpis.get("pubs_vinculadas", 0)
    casos_revisar  = kpis.get("casos_revisar", 0)
    pct_match      = kpis.get("pct_match", 0.0)
    pct_pubs       = kpis.get("pct_pubs_match", 0.0)

    def _kpi_mini(icon, label, value, color):
        return html.Div([
            html.I(className=f"bi {icon}", style={"color": color, "fontSize": "1.3rem",
                                                   "marginBottom": "6px", "display": "block"}),
            html.P(label, className="mini-kpi-label"),
            html.P(str(value), className="mini-kpi-value", style={"color": color}),
        ], className="mini-kpi", style={"borderLeft": f"3px solid {color}"})

    items = html.Div([
        _kpi_mini("bi-people-fill",     "Total profesores",       f"{total_prof}", _PRIMARY),
        _kpi_mini("bi-check-circle",    "Con publicaciones",      f"{prof_con_pubs}", _SUCCESS),
        _kpi_mini("bi-x-circle",        "Sin publicaciones",      f"{prof_sin_pubs}", _DANGER),
        _kpi_mini("bi-percent",         "Cobertura profesores",   f"{pct_match:.1%}", _PRIMARY),
        _kpi_mini("bi-journal-text",    "Pubs vinculadas",        f"{pubs_vinculadas:,}", _SECONDARY),
        _kpi_mini("bi-exclamation-triangle", "Casos a revisar",   f"{casos_revisar}", _WARNING),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "10px"})

    return dbc.Card([
        _pretty_header("Métricas de calidad", "Cobertura y casos problemáticos"),
        dbc.CardBody(items),
    ], className="pretty-card")


# ---------------------------------------------------------------------------
# Tabla de casos problemáticos
# ---------------------------------------------------------------------------

def _card_tabla_matching(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return dbc.Card([
            _pretty_header("Casos a revisar", ""),
            dbc.CardBody(html.Div([
                html.Div("Sin casos problemáticos detectados", className="empty-state-title"),
                html.P("Todos los profesores tienen cobertura aceptable (≥70%).",
                       className="empty-state-text"),
            ], className="empty-state")),
        ], className="pretty-card")

    _PILL = {
        "OK":      "pill-ok",
        "REVISAR": "pill-revisar",
        "CRITICO": "pill-critico",
    }

    col_labels = {
        "nombre_normalizado": "Profesor",
        "departamento":       "Área de investigación",
        "pubs_perfil":        "Pubs Scopus",
        "pubs_extraidas":     "Pubs extraídas",
        "diferencia":         "Diferencia",
        "cobertura":          "Cobertura",
        "estado":             "Estado",
        "accion":             "Acción sugerida",
    }

    header = html.Thead(html.Tr([
        html.Th(v, style={"whiteSpace": "nowrap"}) for v in col_labels.values()
    ]))

    rows = []
    for _, row in df.iterrows():
        cells = []
        for col in col_labels:
            val = row.get(col, "—")
            if col == "estado" and str(val) in _PILL:
                cells.append(html.Td(html.Span(str(val), className=_PILL[str(val)])))
            elif col == "cobertura" and pd.notna(val):
                try:
                    cells.append(html.Td(f"{float(val):.0%}"))
                except Exception:
                    cells.append(html.Td(str(val)))
            elif isinstance(val, float):
                cells.append(html.Td(f"{int(val):,}" if val == val else "—"))
            elif pd.isna(val) if not isinstance(val, str) else False:
                cells.append(html.Td("—"))
            else:
                cells.append(html.Td(str(val)[:50]))
        rows.append(html.Tr(cells))

    return dbc.Card([
        html.Div([
            html.Div([
                html.H5("Profesores con cobertura insuficiente", className="table-toolbar-title"),
                html.P("Casos donde las publicaciones extraídas son < 70% del perfil Scopus.",
                       className="table-toolbar-subtitle"),
            ]),
        ], className="table-toolbar"),
        dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, hover=True, striped=False,
            responsive=True, size="sm", className="mb-0 align-middle",
        ),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pretty_header(title: str, subtitle: str) -> dbc.CardHeader:
    return dbc.CardHeader(html.Div([
        html.H5(title, className="card-title-main"),
        html.P(subtitle, className="card-title-sub"),
    ], className="card-title-block"))
