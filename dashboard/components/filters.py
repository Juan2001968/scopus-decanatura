from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

_ANIO_MIN: int = 2014
_ANIO_MAX: int = 2025

_YEAR_OPTIONS: list[dict] = [
    {"label": str(y), "value": y} for y in range(_ANIO_MIN, _ANIO_MAX + 1)
]

_CUARTIL_OPTIONS = [
    {"label": "Q1", "value": "Q1"},
    {"label": "Q2", "value": "Q2"},
    {"label": "Q3", "value": "Q3"},
    {"label": "Q4", "value": "Q4"},
    {"label": "Sin clasificar", "value": "Sin dato"},
]


def create_filters() -> dbc.Card:
    """Franja horizontal de filtros globales."""
    col_depto = dbc.Col(
        html.Div(
            [
                html.Label("Departamento", className="filter-label", htmlFor="filter-departamento"),
                dcc.Dropdown(
                    id="filter-departamento",
                    placeholder="Todos los departamentos",
                    clearable=True,
                    searchable=True,
                    className="filter-dropdown",
                ),
            ],
            className="filter-group",
        ),
        lg=3, md=6,
    )

    col_profesor = dbc.Col(
        html.Div(
            [
                html.Label("Profesor", className="filter-label", htmlFor="filter-profesor"),
                dcc.Dropdown(
                    id="filter-profesor",
                    placeholder="Todos los profesores",
                    clearable=True,
                    searchable=True,
                    className="filter-dropdown",
                ),
            ],
            className="filter-group",
        ),
        lg=3, md=6,
    )

    col_anios = dbc.Col(
        html.Div(
            [
                html.Label("Desde", className="filter-label", htmlFor="filter-anio-desde"),
                dcc.Dropdown(
                    id="filter-anio-desde",
                    options=_YEAR_OPTIONS,
                    value=_ANIO_MIN,
                    clearable=False,
                    searchable=False,
                    className="filter-dropdown",
                ),
                html.Label(
                    "Hasta",
                    className="filter-label",
                    htmlFor="filter-anio-hasta",
                    style={"marginTop": "8px"},
                ),
                dcc.Dropdown(
                    id="filter-anio-hasta",
                    options=_YEAR_OPTIONS,
                    value=_ANIO_MAX,
                    clearable=False,
                    searchable=False,
                    className="filter-dropdown",
                ),
            ],
            className="filter-group",
        ),
        lg=3, md=6,
    )

    col_tipo = dbc.Col(
        html.Div(
            [
                html.Label("Tipo documental", className="filter-label", htmlFor="filter-tipo-doc"),
                dcc.Dropdown(
                    id="filter-tipo-doc",
                    placeholder="Todos los tipos",
                    clearable=True,
                    searchable=True,
                    multi=True,
                    className="filter-dropdown",
                ),
            ],
            className="filter-group",
        ),
        lg=2, md=6,
    )

    col_cuartil = dbc.Col(
        html.Div(
            [
                html.Label("Cuartil SJR", className="filter-label", htmlFor="filter-cuartil"),
                dcc.Dropdown(
                    id="filter-cuartil",
                    options=_CUARTIL_OPTIONS,
                    placeholder="Todos",
                    clearable=True,
                    multi=True,
                    className="filter-dropdown",
                ),
            ],
            className="filter-group",
        ),
        lg=1, md=6,
    )

    return dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.H5("Panel de filtros", className="pretty-section-title"),
                    html.Div(
                        "Refina la vista por departamento, profesor, años, tipo y cuartil.",
                        className="pretty-section-subtitle",
                    ),
                ])
            ),
            dbc.CardBody(
                dbc.Row(
                    [col_depto, col_profesor, col_anios, col_tipo, col_cuartil],
                    className="g-2 align-items-stretch",
                )
            ),
        ],
        className="section-card filter-card",
    )
