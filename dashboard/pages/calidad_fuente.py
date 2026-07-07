from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import dcc, html

from dashboard.area_style import color_area, wrap_area
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

_COLORES_CUARTIL = {
    "Q1": _SUCCESS, "Q2": _SECONDARY,
    "Q3": _WARNING, "Q4": _DANGER, "Sin dato": "#94a3b8",
}
_PILL = {"Q1": "pill-q1", "Q2": "pill-q2", "Q3": "pill-q3", "Q4": "pill-q4"}


def _apply_layout(fig, height=380):
    fig.update_layout(
        template="plotly_white",
        height=height, paper_bgcolor=_PAPER, plot_bgcolor=_PAPER,
        font=dict(family=_FONT, color=_TEXT, size=13),
        margin=dict(t=32, b=28, l=24, r=20),
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


def layout_fuentes(data: dict) -> html.Div:
    logger.info("Renderizando layout_fuentes")

    cuartiles_dept = data.get("cuartiles_por_departamento", pd.DataFrame())
    sjr_dept       = data.get("sjr_por_departamento",       pd.DataFrame())
    top_fuentes    = data.get("top_fuentes",                pd.DataFrame())

    return html.Div([
        html.Div([
            html.H4("Calidad de fuente", className="section-header-title"),
            html.P(
                "Análisis de revistas, cuartiles SJR, métricas de calidad y top fuentes.",
                className="section-header-subtitle",
            ),
        ], className="section-header-inline"),

        html.Div([
            # Bubble chart métricas
            _card_bubble_revistas(top_fuentes),

            # Cuartiles + SJR
            dbc.Row([
                dbc.Col(_card_cuartiles_stacked(cuartiles_dept), md=7),
                dbc.Col(_card_sjr_departamento(sjr_dept), md=5),
            ], className="g-3 mb-3"),

            # Top 20 revistas
            _card_tabla_fuentes(top_fuentes),

            # Publicaciones sin clasificar
            _card_sin_clasificar(data.get("publicaciones_sin_clasificar", pd.DataFrame())),

        ], className="page-section section-stack"),
    ])


# ---------------------------------------------------------------------------
# Bubble chart: SJR vs CiteScore
# ---------------------------------------------------------------------------

def _card_bubble_revistas(df: pd.DataFrame) -> dbc.Card:
    if df.empty or ("sjr" not in df.columns and "citescore" not in df.columns):
        return _card_vacia("Bubble chart de revistas",
                           "Sin métricas SJR/CiteScore para construir el gráfico.")

    work = df.copy()
    for col in ("sjr", "citescore"):
        if col not in work.columns:
            work[col] = None
        work[col] = pd.to_numeric(work[col], errors="coerce")

    # Conservar revistas con AL MENOS una métrica.  Antes se exigían SJR y
    # CiteScore a la vez y el gráfico quedaba siempre vacío: la tabla
    # fuente_metrica solo trae SJR (CiteScore no está cargado en la BD).
    work = work.dropna(subset=["sjr", "citescore"], how="all")
    if work.empty:
        return _card_vacia("Bubble chart de revistas",
                           "Ninguna revista del filtro activo tiene métricas SJR ni CiteScore.")

    work["count"] = pd.to_numeric(work.get("count", 1), errors="coerce").fillna(1)

    if "cuartil_sjr" not in work.columns:
        work["cuartil_sjr"] = "Sin dato"
    work["cuartil_sjr"] = work["cuartil_sjr"].fillna("Sin dato")

    if "source_title" in work.columns:
        work["label"] = work["source_title"].str[:45]
    else:
        work["label"] = "Revista"

    # Ejes: SJR vs CiteScore cuando hay suficientes revistas con ambas
    # métricas; si una de las dos falta (el caso real de la BD), degradar a
    # la métrica disponible en X y las citas totales de la revista en Y.
    ambas = work.dropna(subset=["sjr", "citescore"])
    if len(ambas) >= 3:
        plot_df, x_col, y_col = ambas, "sjr", "citescore"
        x_lab, y_lab, y_hover = "SJR", "CiteScore", ":.2f"
        subtitle = "Tamaño = artículos publicados · color = cuartil SJR · líneas = medianas"
    else:
        x_col = ("sjr" if work["sjr"].notna().sum() >= work["citescore"].notna().sum()
                 else "citescore")
        x_lab = "SJR" if x_col == "sjr" else "CiteScore"
        faltante = "CiteScore" if x_col == "sjr" else "SJR"
        y_col = "citas" if "citas" in work.columns else "count"
        y_lab = "Citas totales" if y_col == "citas" else "Artículos"
        y_hover = ":,.0f"
        plot_df = work.dropna(subset=[x_col]).copy()
        plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors="coerce").fillna(0)
        subtitle = (f"Sin datos de {faltante} en la BD — se muestra {x_lab} vs "
                    f"{y_lab.lower()} · tamaño = artículos · color = cuartil SJR")

    med_x = plot_df[x_col].median()
    med_y = plot_df[y_col].median()

    fig = px.scatter(
        plot_df, x=x_col, y=y_col,
        size="count", color="cuartil_sjr",
        color_discrete_map=_COLORES_CUARTIL,
        hover_name="label", size_max=40,
        labels={x_col: x_lab, y_col: y_lab, "count": "Artículos"},
        custom_data=["source_title" if "source_title" in plot_df.columns else "label",
                     "count", x_col, y_col],
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Artículos: %{customdata[1]}<br>"
            f"{x_lab}: %{{customdata[2]:.3f}}<br>"
            f"{y_lab}: %{{customdata[3]{y_hover}}}<extra></extra>"
        ),
        marker=dict(line=dict(width=1.5, color="white"), opacity=0.85),
    )
    fig.add_vline(x=med_x, line_dash="dot", line_color="#94a3b8", line_width=1.5,
                  annotation_text=f"Med. {x_lab}: {med_x:.2f}",
                  annotation_font_size=10, annotation_font_color=_MUTED)
    fig.add_hline(y=med_y, line_dash="dot", line_color="#94a3b8", line_width=1.5,
                  annotation_text=f"Med. {y_lab}: {med_y:,.1f}",
                  annotation_font_size=10, annotation_font_color=_MUTED)
    _apply_layout(fig, height=420)

    return dbc.Card([
        _pretty_header(f"Bubble chart de revistas: {x_lab} vs {y_lab}", subtitle),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card")


# ---------------------------------------------------------------------------
# Barras apiladas 100%: cuartiles por departamento
# ---------------------------------------------------------------------------

def _card_cuartiles_stacked(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Cuartiles por área de investigación", "Sin datos.")

    work = df.copy()
    # Nombre completo del área envuelto en varias líneas (no truncar).
    work["departamento_eje"] = work["departamento"].apply(lambda d: wrap_area(d, width=16))

    fig = px.bar(
        work, x="departamento_eje", y="count", color="cuartil",
        color_discrete_map=_COLORES_CUARTIL, barmode="stack",
        labels={"departamento_eje": "", "count": "Publicaciones", "cuartil": "Cuartil"},
        custom_data=["departamento"],
    )
    fig.update_traces(
        marker_line_color="white", marker_line_width=1.5,
        hovertemplate="<b>%{customdata[0]}</b><br>%{fullData.name}: %{y}<extra></extra>",
    )
    _apply_layout(fig, height=340)
    fig.update_xaxes(tickangle=0, automargin=True)

    return dbc.Card([
        _pretty_header("Cuartiles por área de investigación",
                       "Distribución Q1–Q4 de las publicaciones"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Barras horizontales: SJR promedio por departamento
# ---------------------------------------------------------------------------

def _card_sjr_departamento(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("SJR por área de investigación", "Sin datos de SJR.")

    fig = go.Figure(go.Bar(
        x=df["sjr_promedio"],
        # Nombre completo del área, envuelto con <br> (antes se truncaba a la
        # última palabra: "Datos", "Química", "Geociencia").
        y=[wrap_area(d, width=18) for d in df["departamento"]],
        orientation="h",
        marker_color=[color_area(d) for d in df["departamento"]],
        marker_line_color="white", marker_line_width=1.5,
        customdata=df["departamento"],
        hovertemplate="<b>%{customdata}</b><br>SJR promedio: <b>%{x:.3f}</b><extra></extra>",
    ))
    _apply_layout(fig, height=280)
    fig.update_layout(showlegend=False)
    fig.update_yaxes(automargin=True)

    return dbc.Card([
        _pretty_header("SJR promedio por área de investigación", "Indicador de impacto de las fuentes"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Tabla: Top 20 revistas donde publica la División
# ---------------------------------------------------------------------------

def _card_tabla_fuentes(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Top revistas", "Sin datos de fuentes.")

    col_labels = {
        "source_title": "Revista",
        "count":        "Artículos",
        "sjr":          "SJR",
        "snip":         "SNIP",
        "citescore":    "CiteScore",
        "cuartil_sjr":  "Cuartil",
    }
    cols_ok = [c for c in col_labels if c in df.columns]

    header = html.Thead(html.Tr([
        html.Th(col_labels[c],
                style={"whiteSpace": "nowrap",
                       "textAlign": "right" if c != "source_title" and c != "cuartil_sjr" else "left"})
        for c in cols_ok
    ]))

    rows = []
    for _, row in df.head(20).iterrows():
        cells = []
        for col in cols_ok:
            val = row.get(col, "—")
            if col == "cuartil_sjr":
                q = str(val) if pd.notna(val) else ""
                cells.append(html.Td(html.Span(q, className=_PILL.get(q, "")) if q in _PILL else html.Td("—")))
            elif col in ("sjr", "snip"):
                cells.append(html.Td(f"{float(val):.3f}" if pd.notna(val) and val != "—" else "—",
                                     style={"textAlign": "right"}))
            elif col == "citescore":
                cells.append(html.Td(f"{float(val):.2f}" if pd.notna(val) and val != "—" else "—",
                                     style={"textAlign": "right"}))
            elif col == "count":
                cells.append(html.Td(f"{int(val):,}" if pd.notna(val) and val != "—" else "—",
                                     style={"textAlign": "right", "fontWeight": "600"}))
            elif col == "source_title":
                cells.append(html.Td(str(val)[:55] if pd.notna(val) else "—"))
            else:
                cells.append(html.Td(str(val) if pd.notna(val) else "—"))
        rows.append(html.Tr(cells))

    return dbc.Card([
        html.Div([
            html.Div([
                html.H5("Top 20 Revistas donde publica la División", className="table-toolbar-title"),
                html.P("Ordenado por # artículos · reordenable por SJR, SNIP, CiteScore",
                       className="table-toolbar-subtitle"),
            ]),
            html.Span(f"{len(df)} revistas", className="table-pill"),
        ], className="table-toolbar"),
        dbc.Table([header, html.Tbody(rows)],
                  bordered=False, hover=True, striped=False,
                  responsive=True, size="sm", className="mb-0 align-middle"),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Tabla: Publicaciones sin clasificar o en revistas sin métricas
# ---------------------------------------------------------------------------

def _card_sin_clasificar(df: pd.DataFrame) -> dbc.Card:
    n = 0 if df is None else len(df)
    toolbar = html.Div([
        html.Div([
            html.H5("Publicaciones sin clasificar / Sin métricas", className="table-toolbar-title"),
            html.P("Artículos en revistas sin SJR, sin ISSN o no indexadas en Scimago "
                   "(respeta los filtros activos).",
                   className="table-toolbar-subtitle"),
        ]),
        html.Span(f"{n} publicaciones", className="table-pill"),
    ], className="table-toolbar")

    if df is None or df.empty:
        return dbc.Card([
            toolbar,
            dbc.CardBody(html.Div([
                html.Div("Sin publicaciones pendientes de clasificar",
                         className="empty-state-title"),
                html.P(
                    "Todas las publicaciones de la combinación de filtros actual "
                    "tienen SJR y cuartil asignados.",
                    className="empty-state-text",
                ),
            ], className="empty-state")),
        ], className="pretty-card table-card")

    col_map = {
        "titulo":           "Título",
        "profesor":         "Profesor",
        "source_title":     "Revista",
        "anio_publicacion": "Año",
        "issn":             "ISSN",
        "razon":            "Razón",
    }
    cols_ok = [c for c in col_map if c in df.columns]
    header  = html.Thead(html.Tr([html.Th(col_map[c]) for c in cols_ok]))

    rows = []
    for _, row in df.iterrows():
        cells = []
        for c in cols_ok:
            val = row.get(c)
            if pd.isna(val) or str(val).strip() == "":
                cells.append(html.Td("—"))
            elif c == "anio_publicacion":
                cells.append(html.Td(f"{int(val)}", style={"whiteSpace": "nowrap"}))
            else:
                cells.append(html.Td(str(val)[:70]))
        rows.append(html.Tr(cells))

    return dbc.Card([
        toolbar,
        dbc.Table([header, html.Tbody(rows)],
                  bordered=False, hover=True, size="sm",
                  responsive=True, className="mb-0 align-middle"),
    ], className="pretty-card table-card")


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
