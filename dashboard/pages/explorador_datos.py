from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html

from dashboard.components.data_table import create_data_table
from src.utils.logger import get_logger

logger = get_logger(__name__)

_COLS_PREFERIDAS = [
    "titulo",
    "authors_raw",
    "anio_publicacion",
    "source_title",
    "tipo_documental",
    "cuartil_sjr",
    "sjr",
    "snip",
    "citescore",
    "cited_by_count",
    "open_access",
    "doi",
    "indexed_keywords",
]

_COL_NAMES = {
    "titulo":            "Título",
    "authors_raw":       "Autores",
    "anio_publicacion":  "Año",
    "source_title":      "Revista",
    "tipo_documental":   "Tipo",
    "cuartil_sjr":       "Cuartil",
    "sjr":               "SJR",
    "snip":              "SNIP",
    "citescore":         "CiteScore",
    "cited_by_count":    "Citas",
    "open_access":       "Open Access",
    "doi":               "DOI",
    "indexed_keywords":  "Keywords",
}


def _debug_etapas_alert(df: pd.DataFrame) -> html.Div | None:
    """Panel de depuración: registros restantes tras cada etapa de filtrado.

    Los conteos vienen en ``df.attrs["etapas"]`` (los adjunta
    ``_fetch_publicaciones``); permiten ver en qué filtro "se caen" los datos.
    """
    etapas = df.attrs.get("etapas") if isinstance(df, pd.DataFrame) else None
    if not etapas:
        return None
    return dbc.Alert(
        [
            html.Strong("Depuración de filtros — registros tras cada etapa: "),
            f"consulta SQL (años + área/profesor): {etapas.get('consulta_sql', '—')} · "
            f"tras tipo documental: {etapas.get('tras_tipo', '—')} · "
            f"tras cuartil SJR: {etapas.get('tras_cuartil', '—')}",
        ],
        color="secondary",
        className="mb-2",
        style={"fontSize": "12px"},
    )


def layout_explorador(df: pd.DataFrame) -> html.Div:
    logger.info("Renderizando layout_explorador (%d filas)", len(df))

    debug_alert = _debug_etapas_alert(df)
    error = df.attrs.get("error") if isinstance(df, pd.DataFrame) else None

    if error:
        return html.Div([
            dbc.Alert(
                [html.Strong("No se pudo consultar la base de datos. "),
                 f"Detalle técnico: {error}"],
                color="danger",
                className="mt-4 mx-3",
            ),
        ])

    if df.empty:
        return html.Div([
            c for c in [
                debug_alert,
                dbc.Alert(
                    "No hay publicaciones para esta combinación de filtros. "
                    "Ajusta o limpia los filtros para ampliar los resultados.",
                    color="info",
                    className="text-center mt-4 mx-3",
                ),
            ] if c is not None
        ])

    # Seleccionar columnas disponibles en orden preferido
    cols_disp  = [c for c in _COLS_PREFERIDAS if c in df.columns]
    cols_extra = [c for c in df.columns if c not in cols_disp]
    cols_final = cols_disp + cols_extra
    df_display = df[cols_final].copy()

    # Renombrar para presentación
    rename_map = {c: _COL_NAMES.get(c, c.replace("_", " ").title()) for c in df_display.columns}
    df_display = df_display.rename(columns=rename_map)

    # Truncar columnas de texto largo
    for orig, nuevo in rename_map.items():
        if orig in ("titulo", "authors_raw", "indexed_keywords"):
            if nuevo in df_display.columns:
                df_display[nuevo] = df_display[nuevo].apply(lambda x: _truncar(x, 80))

    n_total = len(df_display)

    return html.Div([
        # Cabecera de sección
        html.Div([
            html.H4("Explorador de Datos", className="section-header-title"),
            html.P(
                "Tabla maestra exportable · Filtra, ordena y descarga todos los registros.",
                className="section-header-subtitle",
            ),
        ], className="section-header-inline"),

        html.Div([
            *( [debug_alert] if debug_alert is not None else [] ),
            # Nota informativa + instrucciones de exportación
            dbc.Alert(
                [
                    html.I(className="bi bi-info-circle me-2"),
                    html.Strong(f"{n_total:,} registros disponibles. "),
                    "Usa la fila de filtros bajo la cabecera para refinar por columna. ",
                    "Haz clic en ",
                    html.Strong("Export"),
                    " para descargar todos los registros filtrados en CSV.",
                ],
                color="light",
                className="mb-2 border",
                style={"fontSize": "13px"},
            ),

            # Tabla con exportación habilitada
            dbc.Card([
                html.Div([
                    html.Div([
                        html.P("Registros bibliométricos", className="table-toolbar-title"),
                        html.P(
                            "Todos los registros · aplica filtros globales del panel superior",
                            className="table-toolbar-subtitle",
                        ),
                    ]),
                    html.Span(f"{n_total:,} registros", className="table-pill"),
                ], className="table-toolbar"),
                dbc.CardBody(
                    create_data_table(
                        df_display,
                        table_id="table-explorador-datos",
                        title="Registros bibliométricos",
                        subtitle=f"{n_total:,} registros · filtros aplicados",
                        page_size=20,
                        export=True,
                    )
                ),
            ], className="pretty-card table-card"),

        ], className="page-section section-stack"),
    ])


def _truncar(valor: object, max_len: int = 80) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    text = str(valor).strip()
    return text[:max_len] + "…" if len(text) > max_len else text
