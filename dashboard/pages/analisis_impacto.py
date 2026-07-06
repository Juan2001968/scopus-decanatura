from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import dcc, html

from dashboard.area_style import abreviar_area, color_area, discrete_map, wrap_area
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

PALETA = [_PRIMARY, _SECONDARY, _WARNING, _SUCCESS, "#7c3aed", _DANGER]

_PILL = {"Q1": "pill-q1", "Q2": "pill-q2", "Q3": "pill-q3", "Q4": "pill-q4"}


def _apply_layout(fig, height: int = 380):
    fig.update_layout(
        template="plotly_white",
        height=height, paper_bgcolor=_PAPER, plot_bgcolor=_PAPER,
        font=dict(family=_FONT, color=_TEXT, size=13),
        margin=dict(t=32, b=28, l=24, r=20),
        colorway=PALETA,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="left", x=0, title=None,
            bgcolor="rgba(0,0,0,0)", font=dict(size=11),
        ),
        hoverlabel=dict(bgcolor=_PRIMARY, font_size=12, font_family=_FONT, font_color="white"),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=_GRID, tickfont=dict(size=11))
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, gridwidth=1, zeroline=False, tickfont=dict(size=11))
    return fig


def layout_impacto(data: dict) -> html.Div:
    logger.info("Renderizando layout_impacto")

    comparativa     = data.get("comparativa_profesores",   pd.DataFrame())
    evolucion       = data.get("evolucion_comparativa",    pd.DataFrame())
    citas_anio      = data.get("citas_por_anio",           pd.DataFrame())
    citas_auto_anio = data.get("citas_autocitas_por_anio", pd.DataFrame())
    top_pubs        = data.get("top_publicaciones",        pd.DataFrame())
    citas_dept      = data.get("citas_por_departamento",   pd.DataFrame())

    return html.Div([
        html.Div([
            html.H4("Análisis de impacto", className="section-header-title"),
            html.P(
                "Patrones de citación, publicaciones influyentes y posicionamiento de profesores.",
                className="section-header-subtitle",
            ),
        ], className="section-header-inline"),

        html.Div([
            # Top artículos citados
            _card_top_citadas(top_pubs),

            # Scatter impacto + citas por departamento
            dbc.Row([
                dbc.Col(_card_scatter_impacto(comparativa), md=7),
                dbc.Col(_card_citas_dept(citas_dept), md=5),
            ], className="g-3 mb-3"),

            # Evolución de citas (ancho completo).
            # Ocultas temporalmente del layout (las funciones se conservan abajo):
            #   - "Citas vs Autocitas"     -> _card_citas_vs_autocitas
            #   - "Citas ajustadas"        -> _card_citas_ajustadas
            #   - "Porcentaje de autocitas"-> _card_autocitas_pct
            dbc.Row([
                dbc.Col(_card_evolucion_citas(evolucion), md=12),
            ], className="g-3 mb-3"),

            # Fila oculta (Citas ajustadas + % autocitas por año):
            # dbc.Row([
            #     dbc.Col(_card_citas_ajustadas(citas_anio), md=6),
            #     dbc.Col(_card_autocitas_pct(citas_auto_anio), md=6),
            # ], className="g-3 mb-3"),

            # Tabla: profesores por citas promedio
            _card_mayor_impacto_cita_promedio(comparativa),

        ], className="page-section section-stack"),
    ])


# ---------------------------------------------------------------------------
# Tabla: Top 25 artículos más citados
# ---------------------------------------------------------------------------

def _card_top_citadas(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Artículos más citados", "Sin publicaciones citadas para mostrar.")

    work = df.copy()
    if "cited_by_count" in work.columns:
        work = work.sort_values("cited_by_count", ascending=False).head(25)

    col_map = {
        "titulo":           "Título",
        "autores_asociados":"Autor(es)",
        "anio_publicacion": "Año",
        "source_title":     "Revista",
        "cited_by_count":   "Citas",
        "cuartil_sjr":      "Cuartil",
    }
    cols_ok = [c for c in col_map if c in work.columns]

    header = html.Thead(html.Tr([
        html.Th("#", style={"width": "40px"}),
        *[html.Th(col_map[c], style={"whiteSpace": "nowrap"}) for c in cols_ok],
    ]))

    rows = []
    for i, (_, row) in enumerate(work.iterrows(), start=1):
        citas = row.get("cited_by_count", 0)
        try:
            citas_int = int(citas) if pd.notna(citas) else 0
        except (ValueError, TypeError):
            citas_int = 0

        row_style = {"backgroundColor": "#fef9e7"} if citas_int > 50 else {}

        cells = [html.Td(str(i), style={"color": _MUTED, "fontWeight": "600"})]
        for col in cols_ok:
            val = row.get(col, "—")
            if col == "titulo":
                t = str(val) if pd.notna(val) else "—"
                doi = row.get("doi", "")
                short = t[:70] + ("…" if len(t) > 70 else "")
                if doi and pd.notna(doi) and str(doi).startswith("10."):
                    cells.append(html.Td(
                        html.A(short, href=f"https://doi.org/{doi}", target="_blank",
                               title=t, style={"color": _SECONDARY, "textDecoration": "none"}),
                        title=t,
                    ))
                else:
                    cells.append(html.Td(short, title=t))
            elif col == "cited_by_count":
                cells.append(html.Td(
                    html.Span(f"{citas_int:,}", style={"fontWeight": "700", "color": _PRIMARY}),
                    style={"textAlign": "right"},
                ))
            elif col == "cuartil_sjr":
                q = str(val) if pd.notna(val) else ""
                cells.append(html.Td(html.Span(q, className=_PILL.get(q, "")) if q else html.Td("—")))
            elif col == "anio_publicacion":
                cells.append(html.Td(str(int(val)) if pd.notna(val) else "—",
                                     style={"textAlign": "right", "color": _MUTED}))
            elif col == "autores_asociados":
                cells.append(html.Td(str(val)[:50] + ("…" if len(str(val)) > 50 else "")
                                     if pd.notna(val) else "—"))
            else:
                cells.append(html.Td(str(val)[:45] if pd.notna(val) else "—"))

        rows.append(html.Tr(cells, style=row_style))

    return dbc.Card([
        html.Div([
            html.Div([
                html.H5("Artículos más citados de la División", className="table-toolbar-title"),
                html.P("Top 25 publicaciones · fondo amarillo = >50 citas",
                       className="table-toolbar-subtitle"),
            ]),
            html.Span(f"{len(df)} artículos totales", className="table-pill"),
        ], className="table-toolbar"),
        dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, hover=True, striped=False,
            responsive=True, size="sm", className="mb-0 align-middle",
        ),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Tabla: Profesores con mayor impacto por cita promedio
# ---------------------------------------------------------------------------

def _card_mayor_impacto_cita_promedio(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Impacto por Cita Promedio", "Sin datos de comparativa de profesores.")

    work = df.copy()
    work["publicaciones_total"] = pd.to_numeric(work.get("publicaciones_total", 0), errors="coerce").fillna(0)
    work["citas_totales"]       = pd.to_numeric(work.get("citas_totales", 0), errors="coerce").fillna(0)
    work["h_index"]             = pd.to_numeric(work.get("h_index", 0), errors="coerce").fillna(0)

    work = work[work["publicaciones_total"] >= 3].copy()
    if work.empty:
        return _card_vacia("Impacto por Cita Promedio", "Sin profesores con ≥3 publicaciones.")

    work["citas_por_pub"] = (work["citas_totales"] / work["publicaciones_total"]).round(2)
    work = work.sort_values("citas_por_pub", ascending=False).head(20).reset_index(drop=True)

    col_map = {
        "nombre_normalizado":  "Profesor",
        "departamento":        "Área de investigación",
        "publicaciones_total": "Publicaciones",
        "citas_totales":       "Citas totales",
        "citas_por_pub":       "Citas / Pub.",
        "h_index":             "H-index",
    }
    cols_ok = [c for c in col_map if c in work.columns]

    header = html.Thead(html.Tr([
        html.Th(col_map[c],
                style={"whiteSpace": "nowrap",
                       "textAlign": "right" if c != "nombre_normalizado" and c != "departamento" else "left"})
        for c in cols_ok
    ]))

    right_cols = {"publicaciones_total", "citas_totales", "citas_por_pub", "h_index"}

    rows = []
    for _, row in work.iterrows():
        cells = []
        for col in cols_ok:
            val = row.get(col, "—")
            style = {"textAlign": "right"} if col in right_cols else {}
            if col == "citas_por_pub":
                cells.append(html.Td(
                    html.Span(f"{val:.2f}", style={"fontWeight": "700", "color": _PRIMARY}),
                    style=style,
                ))
            elif col in ("publicaciones_total", "citas_totales"):
                cells.append(html.Td(f"{int(val):,}" if pd.notna(val) else "—", style=style))
            elif col == "h_index":
                cells.append(html.Td(f"{int(val)}" if pd.notna(val) else "—", style=style))
            elif col == "departamento":
                cells.append(html.Td(abreviar_area(val) if pd.notna(val) else "—",
                                     style={"color": _MUTED}))
            else:
                cells.append(html.Td(str(val)[:35] if pd.notna(val) else "—", style=style))
        rows.append(html.Tr(cells))

    return dbc.Card([
        html.Div([
            html.Div([
                html.H5("Profesores con Mayor Impacto por Cita Promedio", className="table-toolbar-title"),
                html.P("Mínimo 3 publicaciones · ordenado por citas/publicación desc",
                       className="table-toolbar-subtitle"),
            ]),
        ], className="table-toolbar"),
        dbc.Table([header, html.Tbody(rows)],
                  bordered=False, hover=True, size="sm",
                  responsive=True, className="mb-0 align-middle"),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Scatter: Producción vs Impacto
# ---------------------------------------------------------------------------

def _card_scatter_impacto(df: pd.DataFrame) -> dbc.Card:
    if df.empty or "publicaciones_total" not in df.columns:
        return _card_vacia("Posicionamiento de profesores", "Sin datos para el scatter.")

    work = df.copy()
    for col in ("h_index", "citas_totales", "publicaciones_total"):
        work[col] = pd.to_numeric(work.get(col, 0), errors="coerce").fillna(0)

    med_x = work["publicaciones_total"].median()
    med_y = work["citas_totales"].median()

    fig = px.scatter(
        work,
        x="publicaciones_total", y="citas_totales",
        size="h_index", color="departamento",
        color_discrete_map=discrete_map(work["departamento"]),
        text="nombre_normalizado",
        labels={"publicaciones_total": "Publicaciones", "citas_totales": "Citas",
                "departamento": "Área de investigación", "h_index": "h-index"},
        size_max=28,
        custom_data=["nombre_normalizado", "publicaciones_total", "citas_totales", "h_index"],
    )
    fig.update_traces(
        textposition="top center",
        textfont=dict(size=9, color=_TEXT),
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Publicaciones: %{customdata[1]}<br>"
            "Citas: %{customdata[2]}<br>"
            "h-index: %{customdata[3]}<extra></extra>"
        ),
        marker=dict(line=dict(width=1.5, color="white")),
    )
    fig.add_vline(x=med_x, line_dash="dot", line_color="#94a3b8", line_width=1.5,
                  annotation_text=f"Med. pubs: {med_x:.0f}",
                  annotation_font_size=10, annotation_font_color=_MUTED)
    fig.add_hline(y=med_y, line_dash="dot", line_color="#94a3b8", line_width=1.5,
                  annotation_text=f"Med. citas: {med_y:.0f}",
                  annotation_font_size=10, annotation_font_color=_MUTED)
    _apply_layout(fig, height=420)

    return dbc.Card([
        _pretty_header(
            "Producción vs Impacto por profesor",
            "Citas = suma de citas de las publicaciones del profesor en el período filtrado · "
            "tamaño = h-index Scopus (histórico) · líneas punteadas = medianas",
        ),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Barras: citas por departamento
# ---------------------------------------------------------------------------

def _card_citas_dept(df: pd.DataFrame) -> dbc.Card:
    """Citas por área contando cada publicación una sola vez.

    Recibe ``citas_por_departamento`` (publicaciones únicas por área desde la
    capa de datos).  NO debe reconstruirse sumando la comparativa por
    profesor: una publicación con k profesores del área se contaría k veces
    (doble conteo de co-autorías internas, +19–22 % medido).
    """
    if df.empty or "citas_totales" not in df.columns:
        return _card_vacia("Citas por área de investigación", "Sin datos comparativos.")

    plot_df = df.sort_values("citas_totales").copy()
    fig = go.Figure(go.Bar(
        x=plot_df["citas_totales"],
        y=[wrap_area(d) for d in plot_df["departamento"]],
        orientation="h",
        marker_color=[color_area(d) for d in plot_df["departamento"]],
        marker_line_color="white", marker_line_width=1.5,
        customdata=plot_df[["departamento", "publicaciones"]].values,
        hovertemplate=("<b>%{customdata[0]}</b><br>Citas: %{x:,}<br>"
                       "Publicaciones: %{customdata[1]:,}<extra></extra>"),
    ))
    _apply_layout(fig, height=280)
    fig.update_layout(showlegend=False)
    fig.update_yaxes(automargin=True)

    return dbc.Card([
        _pretty_header(
            "Citas acumuladas por área de investigación",
            "Cada publicación cuenta una sola vez por área (co-autorías internas no se duplican)",
        ),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Línea: evolución de citas
# ---------------------------------------------------------------------------

def _card_evolucion_citas(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Evolución de citas", "Sin datos de evolución.")

    fig = px.line(
        df, x="anio", y="citas_totales", color="departamento",
        markers=True, color_discrete_map=discrete_map(df["departamento"]),
        labels={"anio": "Año", "citas_totales": "Citas", "departamento": "Área de investigación"},
    )
    fig.update_traces(line=dict(width=3), marker=dict(size=8))
    _apply_layout(fig, height=340)

    return dbc.Card([
        _pretty_header("Evolución de citas por año", "Comportamiento anual del impacto académico"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Línea: citas ajustadas por antigüedad
# ---------------------------------------------------------------------------

def _card_citas_ajustadas(df: pd.DataFrame) -> dbc.Card:
    if df.empty or "citas_ajustadas_antiguedad" not in df.columns:
        return _card_vacia("Citas ajustadas", "Sin serie ajustada disponible.")

    fig = px.line(
        df, x="anio", y="citas_ajustadas_antiguedad", markers=True,
        labels={"anio": "Año", "citas_ajustadas_antiguedad": "Citas ajustadas"},
        color_discrete_sequence=[_PRIMARY],
    )
    fig.update_traces(line=dict(width=3), marker=dict(size=7))
    _apply_layout(fig, height=340)

    return dbc.Card([
        _pretty_header("Citas ajustadas por antigüedad",
                       "Impacto normalizado según tiempo de exposición"),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Barras apiladas: citas externas vs autocitas intragrupo por año
# ---------------------------------------------------------------------------

def _card_citas_vs_autocitas(df: pd.DataFrame) -> dbc.Card:
    if df.empty or "citas_totales" not in df.columns:
        return _card_vacia("Citas vs Autocitas", "Sin datos disponibles.")

    work = df.copy()
    work["autocitas_intragrupo"] = pd.to_numeric(
        work.get("autocitas_intragrupo", 0), errors="coerce"
    ).fillna(0).astype(int)
    work["citas_externas"] = pd.to_numeric(
        work.get("citas_externas", work["citas_totales"]), errors="coerce"
    ).fillna(0).clip(lower=0).astype(int)

    fig = go.Figure()
    fig.add_bar(
        x=work["anio"], y=work["citas_externas"],
        name="Citas externas",
        marker_color=_PRIMARY,
        hovertemplate="<b>%{x}</b><br>Citas externas: %{y:,}<extra></extra>",
    )
    fig.add_bar(
        x=work["anio"], y=work["autocitas_intragrupo"],
        name="Autocitas intragrupo",
        marker_color=_WARNING,
        hovertemplate="<b>%{x}</b><br>Autocitas: %{y:,}<extra></extra>",
    )
    fig.update_layout(barmode="stack")
    _apply_layout(fig, height=340)

    total_auto  = int(work["autocitas_intragrupo"].sum())
    total_citas = int(work["citas_totales"].sum())
    pct = f"{total_auto / total_citas:.1%}" if total_citas > 0 else "0%"

    return dbc.Card([
        _pretty_header(
            "Citas externas vs Autocitas intragrupo",
            f"Total autocitas: {total_auto:,} ({pct} del total) · 2014–2025",
        ),
        dbc.CardBody(html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False}), className="plot-shell")),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Línea: % de autocitas por año
# ---------------------------------------------------------------------------

def _card_autocitas_pct(df: pd.DataFrame) -> dbc.Card:
    if df.empty or "citas_totales" not in df.columns:
        return _card_vacia("Porcentaje de autocitas", "Sin datos disponibles.")

    work = df.copy()
    work["autocitas_intragrupo"] = pd.to_numeric(
        work.get("autocitas_intragrupo", 0), errors="coerce"
    ).fillna(0)
    work["citas_totales"] = pd.to_numeric(work["citas_totales"], errors="coerce").fillna(0)
    work["pct_autocitas"] = (
        work["autocitas_intragrupo"] / work["citas_totales"].replace(0, float("nan"))
    ).fillna(0).round(4) * 100

    fig = go.Figure(go.Scatter(
        x=work["anio"], y=work["pct_autocitas"],
        mode="lines+markers",
        line=dict(color=_WARNING, width=3),
        marker=dict(size=8, color=_WARNING),
        fill="tozeroy",
        fillcolor="rgba(180, 83, 9, 0.08)",
        hovertemplate="<b>%{x}</b><br>Autocitas: %{y:.1f}%<extra></extra>",
    ))
    fig.update_yaxes(ticksuffix="%", range=[0, None])
    _apply_layout(fig, height=340)
    fig.update_layout(showlegend=False)

    return dbc.Card([
        _pretty_header(
            "% de autocitas intragrupo por año",
            "Fracción del impacto generado por publicaciones del mismo grupo",
        ),
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
