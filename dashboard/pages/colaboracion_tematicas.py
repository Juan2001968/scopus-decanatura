from __future__ import annotations

import math
from typing import Dict, List

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import dcc, html

from dashboard.components.data_table import create_data_table
from src.utils.logger import get_logger

logger = get_logger(__name__)

_PRIMARY   = "#1a3a5c"
_SECONDARY = "#2563a8"
_WARNING   = "#b45309"
_SUCCESS   = "#1a7f5a"
_DANGER    = "#b91c1c"
_FONT      = "'Inter', 'Segoe UI', system-ui, sans-serif"
_TEXT      = "#1e293b"
_MUTED     = "#64748b"
_GRID      = "#e2e8f0"
_PAPER     = "#ffffff"

COLORES_DEPT: Dict[str, str] = {
    "Departamento de Matemáticas y Estadística": _PRIMARY,
    "Departamento de Química y Biología":        _SECONDARY,
    "Departamento de Física y Geociencias":      _WARNING,
}
PALETA_OA = {
    "Gold": "#f59e0b", "Green": "#10b981", "Hybrid": _SECONDARY,
    "Bronze": "#b45309", "Closed": _DANGER,
}


def _apply_layout(fig, height=360):
    fig.update_layout(
        template="plotly_white",
        height=height, paper_bgcolor=_PAPER, plot_bgcolor=_PAPER,
        font=dict(family=_FONT, color=_TEXT, size=13),
        margin=dict(t=32, b=28, l=24, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0, title=None,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        hoverlabel=dict(bgcolor=_PRIMARY, font_size=12, font_family=_FONT, font_color="white"),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=_GRID, tickfont=dict(size=11))
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, gridwidth=1,
                     zeroline=False, tickfont=dict(size=11))
    return fig


def layout_colaboracion(data: dict) -> html.Div:
    logger.info("Renderizando layout_colaboracion")

    colab        = data.get("colaboracion", {})
    hist_autores = data.get("histograma_autores", pd.DataFrame())
    top_kw       = data.get("top_keywords",       pd.DataFrame())
    oa           = data.get("open_access",         pd.DataFrame())
    idiomas      = data.get("idiomas",             pd.DataFrame())
    coautoria    = data.get("coautoria_red",       pd.DataFrame())
    profesores   = data.get("profesores_red",      pd.DataFrame())
    interinst    = data.get("publicaciones_interinstitucionales", pd.DataFrame())

    return html.Div([
        html.Div([
            html.H4("Colaboración y temáticas", className="section-header-title"),
            html.P(
                "Red de co-autoría, patrones de colaboración, keywords y Open Access.",
                className="section-header-subtitle",
            ),
        ], className="section-header-inline"),

        html.Div([
            # Red + stats
            dbc.Row([
                dbc.Col(_card_red_coautoria(coautoria, profesores), md=8),
                dbc.Col(_card_stats_colaboracion(colab), md=4),
            ], className="g-3 mb-3"),

            # Keywords: tabla + barra horizontal
            dbc.Row([
                dbc.Col(_card_top_keywords_bar(top_kw), md=7),
                dbc.Col(_card_top_keywords_tabla(top_kw), md=5),
            ], className="g-3 mb-3"),

            # Colaboración tipo + histograma
            dbc.Row([
                dbc.Col(_card_colab_tipo(hist_autores), md=6),
                dbc.Col(_card_histograma_autores(hist_autores), md=6),
            ], className="g-3 mb-3"),

            # Publicaciones colaborativas interinstitucionales
            _card_publicaciones_interinstitucionales(interinst),

            # Open Access + idiomas
            dbc.Row([
                dbc.Col(_card_open_access(oa), md=8),
                dbc.Col(_card_idiomas(idiomas), md=4),
            ], className="g-3 mb-3"),

        ], className="page-section section-stack"),
    ])


# ---------------------------------------------------------------------------
# Red de co-autoría
# ---------------------------------------------------------------------------

def _circular_layout(nodes: List) -> Dict:
    n = len(nodes)
    if n == 0:
        return {}
    return {
        node: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
        for i, node in enumerate(nodes)
    }


def _card_red_coautoria(coautoria: pd.DataFrame, profesores: pd.DataFrame) -> dbc.Card:
    if coautoria.empty or profesores.empty:
        return _card_vacia("Red de co-autoría",
                           "Sin datos de co-publicaciones entre profesores de la División.")

    node_ids = profesores["id_profesor"].tolist()
    pos = _circular_layout(node_ids)
    prof_map = {row["id_profesor"]: row for _, row in profesores.iterrows()}
    max_h = max(1, profesores["h_index"].fillna(0).max())
    dept_colors = {row["id_profesor"]: COLORES_DEPT.get(row.get("nombre_departamento", ""), _SECONDARY)
                   for _, row in profesores.iterrows()}

    edge_x, edge_y = [], []
    for _, edge in coautoria.iterrows():
        a, b = edge["id_prof_a"], edge["id_prof_b"]
        if a not in pos or b not in pos:
            continue
        x0, y0 = pos[a]
        x1, y1 = pos[b]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1.2, color="#cbd5e1"),
        hoverinfo="none", showlegend=False,
    )

    node_x, node_y, node_sizes, node_colors = [], [], [], []
    node_texts, node_hover = [], []
    for nid in node_ids:
        if nid not in pos:
            continue
        x, y = pos[nid]
        node_x.append(x); node_y.append(y)
        row = prof_map.get(nid, {})
        h = float(row.get("h_index") or 0)
        node_sizes.append(12 + 20 * (h / max_h))
        node_colors.append(dept_colors.get(nid, _SECONDARY))
        name = str(row.get("nombre_normalizado", ""))
        short = name.split(",")[0] if "," in name else name[:15]
        node_texts.append(short)
        node_hover.append(f"<b>{name}</b><br>h-index: {h:.0f}<br>{row.get('nombre_departamento', '')}")

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=node_sizes, color=node_colors, line=dict(width=2, color="white")),
        text=node_texts, textposition="top center",
        textfont=dict(size=8, family=_FONT, color=_TEXT),
        hovertemplate="%{customdata}<extra></extra>",
        customdata=node_hover, showlegend=False,
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        paper_bgcolor=_PAPER, plot_bgcolor=_PAPER, height=440,
        font=dict(family=_FONT, color=_TEXT),
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        hoverlabel=dict(bgcolor=_PRIMARY, font_color="white", font_size=12),
    )

    n_aristas = len(coautoria) if not coautoria.empty else 0
    return dbc.Card([
        _pretty_header("Red de co-autoría entre profesores",
                       f"Tamaño = h-index · {n_aristas} co-publicaciones detectadas"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100 network-card")


# ---------------------------------------------------------------------------
# Mini-stats de colaboración
# ---------------------------------------------------------------------------

def _card_stats_colaboracion(colab: dict) -> dbc.Card:
    items = [
        ("bi-people",         "Promedio autores",  f"{colab.get('promedio_autores', 0):.1f}",   _PRIMARY),
        ("bi-diagram-2",      "Mediana autores",   f"{colab.get('mediana_autores', 0):.0f}",    _SECONDARY),
        ("bi-person-check",   "Un solo autor",     f"{colab.get('proporcion_un_autor', 0):.1%}", _WARNING),
        ("bi-arrow-up-right", "Máx. autores",      f"{colab.get('max_autores', 0):,}",          _SUCCESS),
    ]
    cards = [
        html.Div([
            html.Div([html.I(className=f"bi {icon}", style={"color": color, "fontSize": "1.3rem"})],
                     style={"marginBottom": "8px"}),
            html.P(label, className="mini-kpi-label"),
            html.P(value, className="mini-kpi-value", style={"color": color}),
        ], className="mini-kpi", style={"borderLeft": f"3px solid {color}"})
        for icon, label, value, color in items
    ]

    return dbc.Card([
        _pretty_header("Estadísticas de co-autoría", "Indicadores de colaboración"),
        dbc.CardBody(html.Div(cards, className="mini-kpi-row",
                              style={"flexDirection": "column", "gap": "10px"})),
    ], className="pretty-card h-100")


# ---------------------------------------------------------------------------
# Gráfico: Top 30 Keywords (barras horizontales)
# ---------------------------------------------------------------------------

def _card_top_keywords_bar(df: pd.DataFrame) -> dbc.Card:
    if df.empty or "keyword" not in df.columns:
        return _card_vacia("Top Keywords", "Sin datos de keywords.")

    work = df.head(30).copy()
    freq_col = "frecuencia" if "frecuencia" in work.columns else work.columns[1] if len(work.columns) > 1 else None
    if freq_col is None:
        return _card_vacia("Top Keywords", "Sin columna de frecuencia.")

    work = work.sort_values(freq_col, ascending=True)

    fig = go.Figure(go.Bar(
        x=work[freq_col],
        y=work["keyword"].astype(str).str[:40],
        orientation="h",
        marker_color=_SECONDARY,
        marker_line_color="white", marker_line_width=1.2,
        hovertemplate="<b>%{y}</b>: %{x} apariciones<extra></extra>",
    ))
    _apply_layout(fig, height=500)
    fig.update_xaxes(title_text="Frecuencia")

    return dbc.Card([
        _pretty_header("Top 30 Keywords más frecuentes",
                       "Términos de indización más comunes en el corpus"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Tabla: Top Keywords
# ---------------------------------------------------------------------------

def _card_top_keywords_tabla(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Keywords", "Sin datos de keywords.")

    work = df.head(30).copy()
    if "proporcion" in work.columns:
        work["proporcion"] = work["proporcion"].apply(
            lambda x: f"{x:.1%}" if pd.notna(x) else "—"
        )

    col_map = {"keyword": "Keyword"}
    if "frecuencia" in work.columns:
        col_map["frecuencia"] = "Frecuencia"
    if "proporcion" in work.columns:
        col_map["%"] = "%"

    header = html.Thead(html.Tr([html.Th(v) for v in col_map.values()]))
    rows = []
    for _, row in work.iterrows():
        cells = []
        for col in col_map:
            if col == "%":
                cells.append(html.Td(str(row.get("proporcion", "—")),
                                     style={"textAlign": "right", "color": _MUTED}))
            elif col == "frecuencia":
                val = row.get("frecuencia", "—")
                cells.append(html.Td(f"{int(val):,}" if pd.notna(val) and val != "—" else "—",
                                     style={"textAlign": "right", "fontWeight": "600"}))
            else:
                cells.append(html.Td(str(row.get(col, "—"))))
        rows.append(html.Tr(cells))

    return dbc.Card([
        _pretty_header("Keywords frecuentes",
                       "Top 30 · frecuencia y proporción"),
        dbc.CardBody(
            dbc.Table([header, html.Tbody(rows)],
                      bordered=False, hover=True, size="sm", className="mb-0 align-middle"),
        ),
    ], className="pretty-card table-card h-100")


# ---------------------------------------------------------------------------
# Barras apiladas: tipo de colaboración
# ---------------------------------------------------------------------------

def _card_colab_tipo(df: pd.DataFrame) -> dbc.Card:
    if df.empty or "n_autores" not in df.columns:
        return _card_vacia("Tipo de colaboración", "Sin datos de co-autoría.")

    def _tipo(n):
        if n <= 1:  return "Solo interno"
        if n <= 3:  return "Colaboración pequeña"
        return "Colaboración amplia (4+)"

    colores_tipo = {
        "Solo interno":             _PRIMARY,
        "Colaboración pequeña":     _WARNING,
        "Colaboración amplia (4+)": _SUCCESS,
    }
    work = df.copy()
    work["tipo"] = work["n_autores"].apply(_tipo)
    conteo = work["tipo"].value_counts().reset_index()
    conteo.columns = ["tipo", "count"]

    fig = px.bar(conteo, x="tipo", y="count", color="tipo",
                 color_discrete_map=colores_tipo,
                 labels={"tipo": "Tipo de colaboración", "count": "Publicaciones"})
    fig.update_traces(
        marker_line_color="white", marker_line_width=1.5,
        hovertemplate="<b>%{x}</b>: %{y} publicaciones<extra></extra>",
    )
    _apply_layout(fig, height=300)
    fig.update_layout(showlegend=False)

    return dbc.Card([
        _pretty_header("Tipo de colaboración",
                       "Clasificación por número de autores (proxy de alcance)"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Histograma de co-autores
# ---------------------------------------------------------------------------

def _card_histograma_autores(df: pd.DataFrame) -> dbc.Card:
    if df.empty or "n_autores" not in df.columns:
        return _card_vacia("Distribución de coautores", "Sin datos.")

    fig = px.histogram(
        df, x="n_autores", nbins=25,
        color_discrete_sequence=[_SECONDARY],
        labels={"n_autores": "Número de autores", "count": "Publicaciones"},
    )
    fig.update_traces(
        marker_line_color="white", marker_line_width=1.5, opacity=0.9,
        hovertemplate="<b>%{x} autores</b>: %{y} pubs<extra></extra>",
    )
    _apply_layout(fig, height=300)
    fig.update_layout(bargap=0.1, yaxis_title="Publicaciones")

    return dbc.Card([
        _pretty_header("Distribución de coautores",
                       "Frecuencia por número de autores por publicación"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Tabla: Publicaciones colaborativas interinstitucionales
# ---------------------------------------------------------------------------

def _card_publicaciones_interinstitucionales(df: pd.DataFrame) -> dbc.Card:
    if df is None or df.empty:
        # TODO: query publicaciones_interinstitucionales — artículos con al menos 1 autor externo
        return dbc.Card([
            html.Div([
                html.Div([
                    html.H5("Publicaciones Colaborativas Interinstitucionales", className="table-toolbar-title"),
                    html.P("Artículos con al menos 1 co-autor de institución externa.",
                           className="table-toolbar-subtitle"),
                ]),
            ], className="table-toolbar"),
            dbc.CardBody(html.Div([
                html.Div("Tabla pendiente de implementación", className="empty-state-title"),
                html.P(
                    "Requiere query de publicaciones con autores de afiliación externa. "
                    "Ver: TODO en filter_callbacks._build_colaboracion_data()",
                    className="empty-state-text",
                ),
            ], className="empty-state")),
        ], className="pretty-card table-card")

    col_map = {
        "titulo":                 "Título",
        "anio_publicacion":       "Año",
        "institucion_colaboradora":"Institución colaboradora",
        "pais":                   "País",
        "source_title":           "Revista",
        "cited_by_count":         "Citas",
    }
    cols_ok = [c for c in col_map if c in df.columns]
    header = html.Thead(html.Tr([html.Th(col_map[c]) for c in cols_ok]))
    rows = [
        html.Tr([
            html.Td(str(row.get(c, "—"))[:55] if c == "titulo" else str(row.get(c, "—")),
                    style={"textAlign": "right"} if c == "cited_by_count" else {})
            for c in cols_ok
        ])
        for _, row in df.iterrows()
    ]

    return dbc.Card([
        html.Div([
            html.H5("Publicaciones Colaborativas Interinstitucionales", className="table-toolbar-title"),
            html.P("Solo artículos con ≥1 autor externo a la institución.",
                   className="table-toolbar-subtitle"),
        ], className="table-toolbar"),
        dbc.Table([header, html.Tbody(rows)],
                  bordered=False, hover=True, size="sm",
                  responsive=True, className="mb-0 align-middle"),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Open Access
# ---------------------------------------------------------------------------

def _card_open_access(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Open Access", "Sin datos de Open Access.")

    fig = px.bar(
        df, x="anio", y="count", color="categoria_oa",
        color_discrete_map=PALETA_OA, barmode="stack",
        labels={"anio": "Año", "count": "Publicaciones", "categoria_oa": "Modalidad OA"},
    )
    fig.update_traces(
        marker_line_color="white", marker_line_width=1,
        hovertemplate="<b>%{fullData.name}</b> %{x}: %{y}<extra></extra>",
    )
    _apply_layout(fig, height=300)

    return dbc.Card([
        _pretty_header("Evolución de Open Access por año",
                       "Modalidades de acceso abierto a lo largo del tiempo"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Idiomas
# ---------------------------------------------------------------------------

def _card_idiomas(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Idiomas", "Sin datos de idioma.")

    PALETA = [_PRIMARY, _WARNING, _SECONDARY, _SUCCESS]
    fig = px.pie(df, names="idioma", values="count", hole=0.42,
                 color_discrete_sequence=PALETA)
    fig.update_traces(
        textposition="inside", textinfo="percent+label",
        textfont=dict(size=11, family=_FONT),
        marker=dict(line=dict(color="white", width=2)),
    )
    fig.update_layout(
        paper_bgcolor=_PAPER, height=260,
        font=dict(family=_FONT, color=_TEXT),
        margin=dict(t=16, b=8, l=8, r=8),
        showlegend=False,
        hoverlabel=dict(bgcolor=_PRIMARY, font_color="white"),
    )

    return dbc.Card([
        _pretty_header("Distribución por idioma",
                       "Idiomas de las publicaciones en el período"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
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
