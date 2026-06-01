from __future__ import annotations

from typing import Optional

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from dashboard.components.data_table import create_data_table
from dashboard.components.kpi_cards import create_kpi_row
from src.utils.logger import get_logger

logger = get_logger(__name__)

_PRIMARY   = "#1a3a5c"
_SECONDARY = "#2563a8"
_SUCCESS   = "#1a7f5a"
_WARNING   = "#b45309"
_DANGER    = "#b91c1c"
_FONT      = "'Inter', 'Segoe UI', system-ui, sans-serif"
_TEXT      = "#1e293b"
_MUTED     = "#64748b"
_GRID      = "#e2e8f0"
_PAPER     = "#ffffff"

PALETA = [_PRIMARY, _SECONDARY, _WARNING, _SUCCESS, "#7c3aed", _DANGER]


def _apply_layout(fig, height: int = 380):
    fig.update_layout(
        template="plotly_white",
        height=height,
        paper_bgcolor=_PAPER,
        plot_bgcolor=_PAPER,
        font=dict(family=_FONT, color=_TEXT, size=13),
        margin=dict(t=32, b=28, l=24, r=24),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="left", x=0, title=None,
            bgcolor="rgba(0,0,0,0)", font=dict(size=11),
        ),
        hoverlabel=dict(bgcolor=_PRIMARY, font_size=12, font_family=_FONT, font_color="white"),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=_GRID, tickfont=dict(size=11))
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, gridwidth=1,
                     zeroline=False, tickfont=dict(size=11))
    return fig


def layout_profesor(data: Optional[dict] = None) -> html.Div:
    if data is None:
        return _placeholder_sin_profesor()

    logger.info("Renderizando layout_profesor")

    info           = data.get("info", {})
    kpis           = data.get("kpis", {})
    evolucion      = data.get("evolucion_anual", pd.DataFrame())
    top_fuentes    = data.get("top_fuentes", pd.DataFrame())
    dist_cuartiles = data.get("distribucion_cuartiles", pd.DataFrame())
    publicaciones  = data.get("publicaciones", pd.DataFrame())

    return html.Div([
        _header_profesor(info),
        create_kpi_row(kpis),
        html.Div([
            # Combo bar+line de evolución
            _card_evolucion_combo(evolucion),
            dbc.Row([
                dbc.Col(_card_top_fuentes(top_fuentes), md=6),
                dbc.Col(_card_cuartiles(dist_cuartiles), md=6),
            ], className="g-3 mb-3"),
            # Tabla de publicaciones mejorada
            _card_publicaciones(publicaciones),
            # Co-autores frecuentes
            _card_coautores(data.get("coautores_frecuentes", pd.DataFrame())),
        ], className="page-section section-stack"),
    ])


def _header_profesor(info: dict) -> dbc.Card:
    nombre = info.get("nombre", "Profesor")
    depto  = info.get("departamento", "")
    orcid  = info.get("orcid")
    h_idx  = info.get("h_index")

    chips = []
    if depto:
        chips.append(html.Span(depto, className="professor-chip"))
    if h_idx is not None:
        chips.append(html.Span(f"h-index: {h_idx}", className="professor-chip"))
    if orcid:
        chips.append(
            html.A(f"ORCID: {orcid}", href=f"https://orcid.org/{orcid}",
                   target="_blank", className="professor-chip text-decoration-none")
        )

    mini_stats = html.Div([
        html.Div([
            html.Div("Perfil", className="mini-kpi-label"),
            html.P("Docente investigador", className="mini-kpi-value"),
        ], className="mini-kpi"),
        html.Div([
            html.Div("Fuente", className="mini-kpi-label"),
            html.P("Scopus", className="mini-kpi-value"),
        ], className="mini-kpi"),
    ], className="mini-kpi-row")

    return dbc.Card(
        dbc.CardBody([
            html.H3(nombre, className="professor-name"),
            html.P("Perfil consolidado con principales indicadores bibliométricos.", className="professor-meta"),
            html.Div(chips),
            mini_stats,
        ], className="professor-hero-body"),
        className="professor-hero",
    )


# ---------------------------------------------------------------------------
# Gráfico combinado: barras publicaciones + línea citas
# ---------------------------------------------------------------------------

def _card_evolucion_combo(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Trayectoria anual", "No hay datos de trayectoria anual para este profesor.")

    anios = df["anio"].tolist() if "anio" in df.columns else []
    pubs  = df["publicaciones"].tolist() if "publicaciones" in df.columns else []
    citas = df["citas_totales"].tolist() if "citas_totales" in df.columns else []

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=anios, y=pubs,
        name="Publicaciones",
        marker_color=_SECONDARY,
        marker_line_color="white", marker_line_width=1.5,
        yaxis="y1",
        hovertemplate="<b>%{x}</b>: %{y} publicaciones<extra></extra>",
    ))
    if citas:
        fig.add_trace(go.Scatter(
            x=anios, y=citas,
            name="Citas",
            line=dict(color=_DANGER, width=3),
            mode="lines+markers",
            marker=dict(size=7, color=_DANGER),
            yaxis="y2",
            hovertemplate="<b>%{x}</b>: %{y} citas<extra></extra>",
        ))

    fig.update_layout(
        yaxis=dict(title="Publicaciones", showgrid=True, gridcolor=_GRID),
        yaxis2=dict(title="Citas", overlaying="y", side="right", showgrid=False),
        barmode="group",
    )
    _apply_layout(fig, height=380)

    return dbc.Card([
        _pretty_header("Trayectoria anual", "Barras = publicaciones · línea = citas"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card")


# ---------------------------------------------------------------------------
# Gráfico: Top fuentes (barras horizontales)
# ---------------------------------------------------------------------------

def _card_top_fuentes(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Top fuentes", "No hay fuentes disponibles para este profesor.")

    df_top = df.head(10).copy()
    x_col  = "count" if "count" in df_top.columns else df_top.columns[1]
    y_col  = df_top.columns[0]

    fig = go.Figure(go.Bar(
        x=df_top[x_col],
        y=df_top[y_col].astype(str).str[:40],
        orientation="h",
        marker_color=_PRIMARY,
        marker_line_color="white", marker_line_width=1.5,
        hovertemplate="<b>%{y}</b>: %{x} artículos<extra></extra>",
    ))
    fig.update_layout(yaxis=dict(autorange="reversed"))
    _apply_layout(fig, height=360)

    return dbc.Card([
        _pretty_header("Top fuentes de publicación",
                       "Revistas donde más publica el profesor"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Gráfico: Distribución cuartiles (donut)
# ---------------------------------------------------------------------------

def _card_cuartiles(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Cuartiles SJR", "No hay datos de cuartiles para este profesor.")

    import plotly.express as px
    colores = {"Q1": _SUCCESS, "Q2": _SECONDARY, "Q3": _WARNING, "Q4": _DANGER, "Sin dato": "#94a3b8"}
    fig = px.pie(df, names="cuartil", values="count", hole=0.55,
                 color="cuartil", color_discrete_map=colores)
    fig.update_traces(
        textposition="inside", textinfo="percent",
        insidetextfont=dict(size=12),
        marker=dict(line=dict(color="white", width=2)),
        hovertemplate="<b>%{label}</b>: %{value} (%{percent})<extra></extra>",
    )
    fig.update_layout(
        paper_bgcolor=_PAPER, height=360,
        font=dict(family=_FONT, color=_TEXT, size=12),
        margin=dict(t=20, b=20, l=20, r=20),
        legend=dict(orientation="v", x=1.02, xanchor="left", y=0.5,
                    yanchor="middle", font=dict(size=11)),
        hoverlabel=dict(bgcolor=_PRIMARY, font_color="white", font_size=12),
    )

    return dbc.Card([
        _pretty_header("Calidad de fuente", "Distribución del perfil del profesor según cuartil SJR"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Tabla: Publicaciones del profesor (columnas seleccionadas)
# ---------------------------------------------------------------------------

def _card_publicaciones(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Publicaciones del Profesor", "No hay publicaciones asociadas.")

    _PILL_Q = {"Q1": "pill-q1", "Q2": "pill-q2", "Q3": "pill-q3", "Q4": "pill-q4"}

    col_map = {
        "anio_publicacion": "Año",
        "titulo":           "Título",
        "source_title":     "Revista",
        "cuartil_sjr":      "Cuartil",
        "cited_by_count":   "Citas",
        "tipo_documental":  "Tipo",
    }

    cols_available = [c for c in col_map if c in df.columns]
    work = df[cols_available].copy().sort_values("anio_publicacion", ascending=False) \
        if "anio_publicacion" in df.columns else df[cols_available].copy()

    header = html.Thead(html.Tr([
        html.Th(col_map[c], style={"whiteSpace": "nowrap"}) for c in cols_available
    ]))

    rows = []
    for _, row in work.iterrows():
        q = str(row.get("cuartil_sjr", "")) if "cuartil_sjr" in cols_available else ""
        is_q1 = (q == "Q1")
        cells = []
        for col in cols_available:
            val = row.get(col, "—")
            if col == "cuartil_sjr":
                pill_cls = _PILL_Q.get(q, "")
                cell = html.Td(html.Span(q, className=pill_cls) if pill_cls else html.Td("—"))
            elif col == "titulo":
                titulo_full = str(val) if pd.notna(val) else "—"
                titulo_short = titulo_full[:60] + ("…" if len(titulo_full) > 60 else "")
                doi = row.get("doi", "")
                if doi and pd.notna(doi) and str(doi).startswith("10."):
                    cell = html.Td(
                        html.A(titulo_short, href=f"https://doi.org/{doi}",
                               target="_blank", title=titulo_full,
                               style={"color": _SECONDARY, "textDecoration": "none"}),
                        title=titulo_full,
                    )
                else:
                    cell = html.Td(titulo_short, title=titulo_full,
                                   style={"fontWeight": "500"})
            elif col == "cited_by_count":
                cell = html.Td(f"{int(val):,}" if pd.notna(val) and val != "" else "—",
                               style={"textAlign": "right"})
            elif col == "anio_publicacion":
                cell = html.Td(str(int(val)) if pd.notna(val) and val != "" else "—",
                               style={"fontWeight": "500", "color": _MUTED})
            else:
                cell = html.Td(str(val)[:50] if pd.notna(val) else "—")
            cells.append(cell)

        style = {"backgroundColor": "#d1fae5"} if is_q1 else {}
        rows.append(html.Tr(cells, style=style))

    return dbc.Card([
        html.Div([
            html.Div([
                html.H5("Publicaciones del Profesor", className="table-toolbar-title"),
                html.P("Ordenado por año desc · Q1 destacado en verde · clic en título para abrir DOI",
                       className="table-toolbar-subtitle"),
            ]),
            html.Span(f"{len(work)} publicaciones", className="table-pill"),
        ], className="table-toolbar"),
        dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, hover=True, striped=False,
            responsive=True, size="sm", className="mb-0 align-middle",
        ),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Tabla: Co-autores frecuentes
# ---------------------------------------------------------------------------

def _card_coautores(df: pd.DataFrame) -> dbc.Card:
    if df is None or df.empty:
        # TODO: query co_autores_frecuentes — requiere join publicacion_autor con afiliaciones externas
        return dbc.Card([
            html.Div([
                html.Div([
                    html.H5("Co-autores Frecuentes", className="table-toolbar-title"),
                    html.P("Colaboradores con mayor número de publicaciones compartidas.",
                           className="table-toolbar-subtitle"),
                ]),
            ], className="table-toolbar"),
            dbc.CardBody(html.Div([
                html.Div("Tabla pendiente de implementación", className="empty-state-title"),
                html.P(
                    "Requiere query de co_autores_frecuentes con afiliaciones. "
                    "Ver: TODO en filter_callbacks._build_profesor_data()",
                    className="empty-state-text",
                ),
            ], className="empty-state")),
        ], className="pretty-card table-card")

    col_map = {
        "coautor":               "Co-autor",
        "afiliacion":            "Afiliación",
        "publicaciones_juntas":  "Pubs. compartidas",
        "citas_conjuntas":       "Citas conjuntas",
    }
    cols_ok = [c for c in col_map if c in df.columns]
    work    = df[cols_ok].head(10).copy()

    header = html.Thead(html.Tr([html.Th(col_map[c]) for c in cols_ok]))
    rows = [
        html.Tr([
            html.Td(str(row.get(c, "—")),
                    style={"textAlign": "right"} if c in ("publicaciones_juntas", "citas_conjuntas") else {})
            for c in cols_ok
        ])
        for _, row in work.iterrows()
    ]

    return dbc.Card([
        html.Div([
            html.H5("Co-autores Frecuentes", className="table-toolbar-title"),
            html.P("Top 10 colaboradores por publicaciones compartidas.", className="table-toolbar-subtitle"),
        ], className="table-toolbar"),
        dbc.Table([header, html.Tbody(rows)],
                  bordered=False, hover=True, size="sm", className="mb-0 align-middle"),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _placeholder_sin_profesor() -> html.Div:
    return html.Div(
        dbc.Card(
            dbc.CardBody(html.Div([
                html.Div("Selecciona un profesor", className="empty-state-title"),
                html.P("Usa el filtro superior para ver el perfil bibliométrico individual.",
                       className="empty-state-text"),
            ], className="empty-state")),
            className="pretty-card",
        ),
        className="page-section",
    )


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
