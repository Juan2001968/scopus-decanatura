from __future__ import annotations

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import dcc, html

from dashboard.area_style import abreviar_area, color_area, pill_area
from src.utils.logger import get_logger

logger = get_logger(__name__)

_PRIMARY   = "#1a3a5c"
_SECONDARY = "#2563a8"
_ACCENT    = "#e8f0fb"
_SUCCESS   = "#1a7f5a"
_WARNING   = "#b45309"
_DANGER    = "#b91c1c"
_FONT      = "'Inter', 'Segoe UI', system-ui, sans-serif"
_TEXT      = "#1e293b"
_MUTED     = "#64748b"
_GRID      = "#e2e8f0"
_PAPER     = "#ffffff"

PALETA = [_PRIMARY, _SECONDARY, _WARNING, _SUCCESS, "#7c3aed", _DANGER]


def _short_dept(name: str) -> str:
    return abreviar_area(name)


def _apply_layout(fig, height: int = 380):
    fig.update_layout(
        template="plotly_white",
        height=height,
        paper_bgcolor=_PAPER,
        plot_bgcolor=_PAPER,
        font=dict(family=_FONT, color=_TEXT, size=13),
        margin=dict(t=36, b=28, l=24, r=20),
        colorway=PALETA,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="left", x=0, title=None,
            bgcolor="rgba(0,0,0,0)", font=dict(size=11),
        ),
        hoverlabel=dict(
            bgcolor=_PRIMARY, font_size=12,
            font_family=_FONT, font_color="white",
            bordercolor=_PRIMARY,
        ),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=_GRID, tickfont=dict(size=11))
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, gridwidth=1, zeroline=False, tickfont=dict(size=11))
    return fig


def layout_resumen(data: dict) -> html.Div:
    logger.info("Renderizando layout_resumen")

    evolucion    = data.get("evolucion_por_departamento", pd.DataFrame())
    dist_tipos   = data.get("distribucion_tipos", pd.DataFrame())
    dist_cuart   = data.get("distribucion_cuartiles", pd.DataFrame())
    tabla_deptos = data.get("tabla_departamentos", pd.DataFrame())
    comparativa  = data.get("comparativa_profesores", pd.DataFrame())

    return html.Div([
        html.Div([
            _card_ranking_profesores(comparativa),
            _card_evolucion_toggle(evolucion),
            dbc.Row([
                dbc.Col(_card_top10_profesores(comparativa), md=7),
                dbc.Col(_card_cuartiles(dist_cuart), md=5),
            ], className="g-3 mb-3"),
            dbc.Row([
                dbc.Col(_card_tipos(dist_tipos), md=5),
                dbc.Col(_card_tabla_departamentos(tabla_deptos, data.get("totales_division")), md=7),
            ], className="g-3 mb-3"),
        ], className="page-section section-stack"),
    ])


# ---------------------------------------------------------------------------
# Tabla: Ranking de profesores por producción
# ---------------------------------------------------------------------------

def _card_ranking_profesores(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Ranking de Profesores", "Sin datos de comparativa de profesores.")

    work = df.copy()
    work["publicaciones_total"] = pd.to_numeric(work.get("publicaciones_total", 0), errors="coerce").fillna(0)
    work["citas_totales"]       = pd.to_numeric(work.get("citas_totales", 0), errors="coerce").fillna(0)
    work["h_index"]             = pd.to_numeric(work.get("h_index", 0), errors="coerce").fillna(0)
    work["pct_q1q2"]            = pd.to_numeric(work.get("pct_q1q2", 0), errors="coerce").fillna(0)
    work = work.sort_values("publicaciones_total", ascending=False).reset_index(drop=True)
    work["pos"] = range(1, len(work) + 1)

    _MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

    header = html.Thead(html.Tr([
        html.Th("#"),
        html.Th("Profesor"),
        html.Th("Área de investigación"),
        html.Th("Publicaciones", style={"textAlign": "right"}),
        html.Th("Citas", style={"textAlign": "right"}),
        html.Th("H-index", style={"textAlign": "right"}),
        html.Th("% Q1+Q2", style={"textAlign": "right"}),
    ]))

    rows = []
    for _, row in work.head(20).iterrows():
        pos   = int(row["pos"])
        medal = _MEDALS.get(pos, "")
        dept  = str(row.get("departamento", ""))
        pill_label, pill_color, pill_bg = pill_area(dept)

        h_val   = row.get("h_index")
        q_val   = row.get("pct_q1q2")
        prof_id = int(row.get("id_profesor", 0))

        cells = [
            html.Td(
                html.Span(
                    f"{medal} {pos}" if medal else str(pos),
                    style={"fontWeight": "600", "fontSize": "13px"},
                )
            ),
            html.Td(
                html.Span(
                    str(row.get("nombre_normalizado", ""))[:35],
                    id={"type": "prof-ranking-link", "index": prof_id},
                    n_clicks=0,
                    className="prof-ranking-link",
                ) if prof_id else str(row.get("nombre_normalizado", ""))[:35]
            ),
            html.Td(
                html.Span(
                    pill_label,
                    style={
                        "background": pill_bg, "color": pill_color,
                        "borderRadius": "999px", "padding": "2px 8px",
                        "fontSize": "11px", "fontWeight": "600",
                    },
                )
            ),
            html.Td(f"{int(row['publicaciones_total']):,}", style={"textAlign": "right", "fontWeight": "600"}),
            html.Td(f"{int(row['citas_totales']):,}", style={"textAlign": "right"}),
            html.Td(f"{int(h_val)}" if pd.notna(h_val) else "—", style={"textAlign": "right"}),
            html.Td(f"{q_val:.0%}" if pd.notna(q_val) else "—", style={"textAlign": "right"}),
        ]
        rows.append(html.Tr(cells))

    return dbc.Card([
        html.Div([
            html.Div([
                html.H5("Ranking de Profesores por Producción", className="table-toolbar-title"),
                html.P(
                    f"Top {min(20, len(work))} profesores · ordenado por publicaciones · reordenable por columna",
                    className="table-toolbar-subtitle",
                ),
            ]),
            html.Span(f"{len(work)} profesores", className="table-pill"),
        ], className="table-toolbar"),
        dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, hover=True, striped=False,
            responsive=True, size="sm", className="mb-0 align-middle",
        ),
    ], className="pretty-card table-card")


# ---------------------------------------------------------------------------
# Gráfico: Top 10 profesores por publicaciones (barras horizontales)
# ---------------------------------------------------------------------------

def _card_top10_profesores(df: pd.DataFrame) -> dbc.Card:
    if df.empty or "publicaciones_total" not in df.columns:
        return _card_vacia("Top 10 Profesores", "Sin datos de comparativa de profesores.")

    work = df.copy()
    work["publicaciones_total"] = pd.to_numeric(work["publicaciones_total"], errors="coerce").fillna(0)
    work = work.nlargest(10, "publicaciones_total").sort_values("publicaciones_total")

    nombre_col = "nombre_normalizado" if "nombre_normalizado" in work.columns else work.columns[0]
    dept_col   = "departamento"       if "departamento"       in work.columns else None

    fig = go.Figure()
    deptos_presentes = (
        [d for d in work[dept_col].dropna().unique()] if dept_col else []
    )
    for dept in deptos_presentes:
        sub = work[work[dept_col] == dept]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["publicaciones_total"],
            y=sub[nombre_col].str[:28],
            orientation="h",
            name=_short_dept(dept),
            marker_color=color_area(dept),
            marker_line_color="white", marker_line_width=1.5,
            hovertemplate="<b>%{y}</b><br>Publicaciones: %{x}<extra></extra>",
        ))

    _apply_layout(fig, height=360)
    fig.update_layout(barmode="stack", showlegend=True)
    fig.update_xaxes(title_text="Publicaciones totales")

    return dbc.Card([
        _pretty_header(
            "Top 10 Profesores por Publicaciones",
            "Colores por área de investigación · período filtrado",
        ),
        dbc.CardBody(html.Div(
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            className="plot-shell",
        )),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Gráfico 1: Evolución con toggle anual/acumulado + trendline
# ---------------------------------------------------------------------------

def _card_evolucion_toggle(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Evolución temporal", "Sin datos de evolución anual.")

    deptos = sorted(df["nombre_departamento"].unique())
    fig = go.Figure()

    for i, depto in enumerate(deptos):
        sub = df[df["nombre_departamento"] == depto].sort_values("anio")
        color = color_area(depto, PALETA[i % len(PALETA)])
        fig.add_trace(go.Bar(
            x=sub["anio"], y=sub["publicaciones"],
            name=_short_dept(depto),
            marker_color=color,
            marker_line_color="white", marker_line_width=1.5,
            visible=True,
        ))

    for i, depto in enumerate(deptos):
        sub = df[df["nombre_departamento"] == depto].sort_values("anio")
        color = color_area(depto, PALETA[i % len(PALETA)])
        fig.add_trace(go.Scatter(
            x=sub["anio"], y=sub["publicaciones"].cumsum(),
            name=_short_dept(depto),
            line=dict(color=color, width=3),
            mode="lines+markers", marker=dict(size=7),
            visible=False,
        ))

    total_anio = df.groupby("anio")["publicaciones"].sum().reset_index()
    if len(total_anio) >= 2:
        z = np.polyfit(total_anio["anio"], total_anio["publicaciones"], 1)
        p = np.poly1d(z)
        fig.add_trace(go.Scatter(
            x=total_anio["anio"], y=p(total_anio["anio"]),
            name="Tendencia",
            line=dict(color=_DANGER, width=2, dash="dot"),
            mode="lines", visible=True,
            showlegend=True,
        ))

    n = len(deptos)
    anual_vis = [True] * n + [False] * n + [True]
    acum_vis  = [False] * n + [True] * n + [False]

    fig.update_layout(
        barmode="stack",
        updatemenus=[dict(
            type="buttons", direction="right",
            x=0.0, y=1.18, xanchor="left", yanchor="top",
            bgcolor="white", bordercolor=_GRID,
            font=dict(size=12, family=_FONT, color=_PRIMARY),
            buttons=[
                dict(label="Por año",   method="update",
                     args=[{"visible": anual_vis}, {"barmode": "stack"}]),
                dict(label="Acumulado", method="update",
                     args=[{"visible": acum_vis}, {}]),
            ],
            active=0,
        )],
    )
    _apply_layout(fig, height=420)

    return dbc.Card([
        _pretty_header(
            "Evolución de publicaciones por área de investigación",
            "Barras anuales apiladas · botón para ver acumulado",
        ),
        dbc.CardBody(html.Div(
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            className="plot-shell",
        )),
    ], className="pretty-card plot-card")


# ---------------------------------------------------------------------------
# Gráfico 2: Donut cuartiles
# ---------------------------------------------------------------------------

def _card_cuartiles(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Cuartiles SJR", "Sin datos de cuartiles.")

    colores = {
        "Q1": _SUCCESS, "Q2": _SECONDARY,
        "Q3": _WARNING, "Q4": _DANGER, "Sin dato": "#94a3b8",
    }

    fig = px.pie(df, names="cuartil", values="count", hole=0.58,
                 color="cuartil", color_discrete_map=colores)
    fig.update_traces(
        textposition="inside", textinfo="percent",
        insidetextfont=dict(size=11, family=_FONT),
        marker=dict(line=dict(color="white", width=2)),
        hovertemplate="<b>%{label}</b>: %{value} pubs (%{percent})<extra></extra>",
    )
    fig.update_layout(
        paper_bgcolor=_PAPER, height=290,
        font=dict(family=_FONT, color=_TEXT, size=12),
        margin=dict(t=16, b=8, l=8, r=8),
        legend=dict(orientation="v", x=1.02, xanchor="left", y=0.5,
                    yanchor="middle", font=dict(size=11)),
        hoverlabel=dict(bgcolor=_PRIMARY, font_color="white", font_size=12),
    )

    return dbc.Card([
        _pretty_header("Distribución por cuartil SJR",
                       "Calidad relativa de las fuentes de publicación"),
        dbc.CardBody(html.Div(
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            className="plot-shell",
        )),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Gráfico 3: Donut tipos documentales
# ---------------------------------------------------------------------------

def _card_tipos(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        return _card_vacia("Tipos documentales", "Sin datos de tipo documental.")

    fig = px.pie(df, names="tipo_documental", values="count",
                 hole=0.55, color_discrete_sequence=PALETA)
    fig.update_traces(
        textposition="inside", textinfo="percent",
        insidetextfont=dict(size=11, family=_FONT),
        marker=dict(line=dict(color="white", width=2)),
        hovertemplate="<b>%{label}</b>: %{value} (%{percent})<extra></extra>",
    )
    fig.update_layout(
        paper_bgcolor=_PAPER, height=290,
        font=dict(family=_FONT, color=_TEXT, size=12),
        margin=dict(t=16, b=8, l=8, r=8),
        legend=dict(orientation="v", x=1.02, xanchor="left", y=0.5,
                    yanchor="middle", font=dict(size=11)),
        hoverlabel=dict(bgcolor=_PRIMARY, font_color="white", font_size=12),
    )

    return dbc.Card([
        _pretty_header("Distribución por tipo documental",
                       "Composición del output científico por tipología"),
        dbc.CardBody(html.Div(
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            className="plot-shell",
        )),
    ], className="pretty-card plot-card h-100")


# ---------------------------------------------------------------------------
# Tabla comparativa de departamentos
# ---------------------------------------------------------------------------

def _card_tabla_departamentos(
    df: pd.DataFrame,
    totales_division: dict | None = None,
) -> dbc.Card:
    if df.empty:
        return _card_vacia("Comparativa áreas de investigación", "Sin información comparativa.")

    col_map = {
        "nombre_departamento":   "Área de investigación",
        "profesores":            "Profesores activos",
        "publicaciones_total":   "Publicaciones",
        "publicaciones_3_anios": "2014–2025",
        "citas_totales":         "Citas",
        "h_index_area":          "H-index",
        "sjr_promedio":          "SJR prom.",
    }

    header = html.Thead(html.Tr([
        html.Th(v, style={"whiteSpace": "nowrap"}) for v in col_map.values()
    ]))

    rows = []
    # Sin fila de total para h-index y SJR: no son aditivos entre áreas.
    totals = {c: 0 for c in col_map
              if c not in ("nombre_departamento", "h_index_area", "sjr_promedio")}
    for _, row in df.iterrows():
        cells = []
        for col in col_map:
            val = row.get(col, "—")
            if isinstance(val, float):
                fmt = (f"{val:.2f}" if col == "sjr_promedio" else f"{val:,.0f}")
                cells.append(html.Td(fmt, style={"textAlign": "right"} if col != "nombre_departamento" else {}))
                if col in totals:
                    totals[col] += val
            elif isinstance(val, int):
                cells.append(html.Td(f"{val:,}", style={"textAlign": "right"}))
                if col in totals:
                    totals[col] += val
            else:
                cells.append(html.Td(val))
        rows.append(html.Tr(cells))

    # La suma de las filas por área cuenta DOS veces las publicaciones con
    # coautores de áreas distintas (11 pubs / 88 citas con los datos de
    # 2026-07): el TOTAL de publicaciones y citas se toma del conjunto ÚNICO
    # de la División (``totales_division``, calculado sobre el mismo base_df
    # filtrado en _build_resumen_data). "profesores" sí es aditivo: cada
    # profesor pertenece a UNA sola área (columna profesor.id_departamento).
    if totales_division:
        for key in ("publicaciones_total", "publicaciones_3_anios", "citas_totales"):
            if key in totals and totales_division.get(key) is not None:
                totals[key] = totales_division[key]

    # Fila de totales
    total_cells = [html.Td("TOTAL", style={"fontWeight": "700"})]
    for col in list(col_map.keys())[1:]:
        v = totals.get(col, "")
        if isinstance(v, float) and v > 0:
            total_cells.append(html.Td(f"{v:,.0f}", style={"fontWeight": "700", "textAlign": "right"}))
        elif isinstance(v, int) and v > 0:
            total_cells.append(html.Td(f"{v:,}", style={"fontWeight": "700", "textAlign": "right"}))
        else:
            total_cells.append(html.Td("—", style={"fontWeight": "700", "textAlign": "right"}))
    rows.append(html.Tr(total_cells, style={"backgroundColor": "#e8f0fb"}))

    return dbc.Card([
        html.Div([
            html.Div([
                html.H5("Producción por Área de investigación", className="table-toolbar-title"),
                html.P("Indicadores consolidados por unidad académica con totales · "
                       "H-index del área calculado del período (mayor h con h publicaciones de ≥ h citas)",
                       className="table-toolbar-subtitle"),
            ]),
        ], className="table-toolbar"),
        dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, hover=True, striped=False,
            responsive=True, size="sm", className="mb-0 align-middle",
        ),
    ], className="pretty-card table-card h-100")


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
