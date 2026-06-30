from __future__ import annotations

from dash import dcc, html

from config.settings import FECHA_CORTE_DATOS
from dashboard.app import app
from dashboard.callbacks import filter_callbacks  # noqa: F401  — registra todos los callbacks

_ANIO_MIN = 2014
_ANIO_MAX = 2025

# (tab_id, icono, etiqueta breadcrumb)
_NAV_ITEMS = [
    ("tab-resumen",      "🏠", "Visión General"),
    ("tab-profesor",     "👤", "Perfil Profesor"),
    ("tab-impacto",      "🔥", "Impacto"),
    ("tab-fuentes",      "⭐", "Calidad de Fuente"),
    ("tab-colaboracion", "🌐", "Colaboración"),
    ("tab-benchmarking", "📊", "Rankings"),
    # Oculto temporalmente: la vista "Calidad de Datos" (matching) no se muestra
    # en la navegación por ahora. El código de la página y sus callbacks se
    # conservan intactos; para reactivarla, descomentar esta línea y la entrada
    # correspondiente en _NAV_TABS / _BREADCRUMB_LABELS / el callback principal
    # de dashboard/callbacks/filter_callbacks.py.
    # ("tab-matching",     "🔍", "Calidad de Datos"),
    ("tab-explorador",   "🗂",  "Explorador"),
]

_CUARTIL_OPTIONS = [
    {"label": "Q1", "value": "Q1"},
    {"label": "Q2", "value": "Q2"},
    {"label": "Q3", "value": "Q3"},
    {"label": "Q4", "value": "Q4"},
    {"label": "Sin clasificar", "value": "Sin dato"},
]


def _sidebar() -> html.Aside:
    nav_items = [
        html.Div(
            [html.Span(icon, className="nav-icon"), html.Span(label)],
            id=f"nav-{tab_id}",
            className="nav-item active" if i == 0 else "nav-item",
            n_clicks=0,
        )
        for i, (tab_id, icon, label) in enumerate(_NAV_ITEMS)
    ]

    _year_opts = [{"label": str(y), "value": y} for y in range(_ANIO_MIN, _ANIO_MAX + 1)]

    filters = html.Div(
        [
            html.Div("Filtros", className="f-section"),

            html.Label("Área de investigación", className="f-label"),
            dcc.Dropdown(
                id="filter-departamento",
                placeholder="Todas las áreas de investigación",
                clearable=True,
                searchable=True,
            ),

            html.Label("Profesor / Investigador", className="f-label"),
            dcc.Dropdown(
                id="filter-profesor",
                placeholder="Todos los profesores",
                clearable=True,
                searchable=True,
            ),

            html.Label("Desde", className="f-label"),
            dcc.Dropdown(
                id="filter-anio-desde",
                options=_year_opts,
                value=_ANIO_MIN,
                clearable=False,
                searchable=False,
            ),

            html.Label("Hasta", className="f-label"),
            dcc.Dropdown(
                id="filter-anio-hasta",
                options=_year_opts,
                value=_ANIO_MAX,
                clearable=False,
                searchable=False,
            ),

            html.Label("Tipo documental", className="f-label"),
            dcc.Dropdown(
                id="filter-tipo-doc",
                placeholder="Todos los tipos",
                clearable=True,
                multi=True,
            ),

            html.Label("Cuartil SJR", className="f-label"),
            dcc.Dropdown(
                id="filter-cuartil",
                options=_CUARTIL_OPTIONS,
                placeholder="Todos",
                clearable=True,
                multi=True,
            ),

            html.Button(
                "↺  Limpiar filtros",
                id="btn-reset-filters",
                className="btn-reset",
                n_clicks=0,
            ),
        ],
        className="sb-filters",
    )

    return html.Aside(
        id="sidebar",
        children=[
            html.Div(
                [
                    html.Div("📊", className="sb-icon"),
                    html.Div("Monitor Bibliométrico", className="sb-title"),
                    html.Div("División de Ciencias Básicas · 2014–2025", className="sb-sub"),
                html.Div(f"Datos descargados: {FECHA_CORTE_DATOS}", className="sb-cutoff"),
                ],
                className="sb-brand",
            ),
            html.Nav(
                [html.Div("Vistas", className="nav-lbl")] + nav_items,
                className="sb-nav",
            ),
            filters,
            html.Div(
                ["Datos Scopus · ETL PostgreSQL", html.Br(), "Actualizado: mayo 2026 · v2.0"],
                className="sb-foot",
            ),
        ],
    )


def _main() -> html.Main:
    panels = [
        html.Div(
            html.Div(id=f"content-{tab_id.replace('tab-', '')}"),
            id=f"panel-{tab_id.replace('tab-', '')}",
            style={"display": "block" if tab_id == "tab-resumen" else "none"},
            className="content-panel",
        )
        for tab_id, _, _ in _NAV_ITEMS
    ]

    return html.Main(
        id="main",
        children=[
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("División de Ciencias Básicas", style={"color": "#64748b"}),
                            html.Span(" › ", className="breadcrumb-sep"),
                            html.Span(
                                "Visión General",
                                id="breadcrumb-current",
                                className="breadcrumb-current",
                            ),
                        ],
                        className="breadcrumb-nav",
                    ),
                ],
                className="top-bar",
            ),
            html.Div(
                [
                    html.Div(id="kpi-upper-block", className="mb-2"),
                    html.Div(id="kpi-context-block", className="mb-3"),
                ] + panels,
                className="main-content",
            ),
        ],
    )


app.layout = html.Div(
    className="dashboard-shell",
    children=[
        dcc.Store(id="store-active-view", data="tab-resumen"),
        _sidebar(),
        _main(),
    ],
)

server = app.server

if __name__ == "__main__":
    app.run(debug=True, port=8050)
