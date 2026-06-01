from __future__ import annotations

from typing import Union

import dash_bootstrap_components as dbc
from dash import html

# Clase CSS de color por semántica → gradiente en ::before (ver styles.css)
_COLOR_CLASS = {
    "primary":   "c-blue",
    "secondary": "c-violet",
    "success":   "c-green",
    "warning":   "c-amber",
    "danger":    "c-rose",
    "info":      "c-indigo",
}


def _format_number(value: Union[int, float, None], decimals: int = 0) -> str:
    if value is None:
        return "—"
    try:
        if decimals > 0:
            return f"{float(value):,.{decimals}f}"
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return "—"


def create_kpi_card(
    title: str,
    value: str,
    subtitle: str = "",
    color: str = "primary",
    icon_class: str = "bi-bar-chart",
) -> dbc.Card:
    color_class = _COLOR_CLASS.get(color, "c-blue")

    return dbc.Card(
        dbc.CardBody(
            html.Div(
                [
                    html.P(title, className="kpi-title"),
                    html.H3(value, className="kpi-value"),
                    html.P(subtitle, className="kpi-subtitle"),
                ],
                className="kpi-inner",
            ),
            className="kpi-card-body",
        ),
        className=f"kpi-card h-100 {color_class}",
    )


def create_kpi_row(kpis: dict) -> dbc.Row:
    """
    KPIs para Decanatura:
    1. Publicaciones 2014–2025
    2. Total citas
    3. Citas excluyendo autocitas
    4. H-index promedio División
    5. % publicaciones Q1 o Q2
    6. Profesores activos
    """
    citas    = kpis.get("citas", {})
    metricas = kpis.get("metricas_fuente", {})

    pct_q1q2 = kpis.get("pct_q1q2")
    q1q2_val = f"{pct_q1q2:.1%}" if pct_q1q2 is not None else "—"
    q1q2_sub = "Publicaciones en Q1 o Q2" if pct_q1q2 is not None else "Sin datos de cuartil"

    citas_autocitas = kpis.get("autocitas_intragrupo")
    citas_auto_val  = _format_number(citas_autocitas) if citas_autocitas is not None else "—"
    citas_auto_sub  = "Citas dentro del grupo" if citas_autocitas is not None else "Dato no disponible"

    profesores_activos = kpis.get("profesores_activos")
    prof_val = _format_number(profesores_activos) if profesores_activos is not None else "—"

    cards = [
        dbc.Col(
            create_kpi_card(
                title="Publicaciones Uninorte",
                value=_format_number(kpis.get("publicaciones_3_anios")),
                subtitle="Producción del período",
                color="primary",
                icon_class="bi-journals",
            ),
            xl=2, lg=4, md=4, sm=6, xs=12,
        ),
        dbc.Col(
            create_kpi_card(
                title="Citas totales",
                value=_format_number(citas.get("total")),
                subtitle="Impacto acumulado",
                color="secondary",
                icon_class="bi-chat-quote",
            ),
            xl=2, lg=4, md=4, sm=6, xs=12,
        ),
        dbc.Col(
            create_kpi_card(
                title="Autocitas",
                value=citas_auto_val,
                subtitle=citas_auto_sub,
                color="info",
                icon_class="bi-filter-circle",
            ),
            xl=2, lg=4, md=4, sm=6, xs=12,
        ),
        dbc.Col(
            create_kpi_card(
                title=kpis.get("h_index_label", "H-index División"),
                value=_format_number(kpis.get("h_index")),
                subtitle="Período filtrado",
                color="success",
                icon_class="bi-trophy",
            ),
            xl=2, lg=4, md=4, sm=6, xs=12,
        ),
        dbc.Col(
            create_kpi_card(
                title="% en Q1 o Q2",
                value=q1q2_val,
                subtitle=q1q2_sub,
                color="warning",
                icon_class="bi-award",
            ),
            xl=2, lg=4, md=4, sm=6, xs=12,
        ),
        dbc.Col(
            create_kpi_card(
                title="Profesores activos",
                value=prof_val,
                subtitle="Con ≥1 publicación",
                color="danger",
                icon_class="bi-people",
            ),
            xl=2, lg=4, md=4, sm=6, xs=12,
        ),
    ]

    return dbc.Row(cards, className="g-3 kpi-wrapper")
