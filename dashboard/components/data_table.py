from __future__ import annotations

from typing import Optional

from dash import dash_table, html


def create_data_table(
    df,
    table_id: str = "data-table",
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    page_size: int = 15,
    export: bool = False,
):
    """Tabla ejecutiva reutilizable con cabecera oscura."""
    if df is None or df.empty:
        return html.Div(
            [
                html.Div("Sin datos disponibles", className="empty-state-title"),
                html.P(
                    "No hay registros para mostrar en este momento.",
                    className="empty-state-text",
                ),
            ],
            className="empty-state",
        )

    shown_title    = title    or "Detalle de registros"
    shown_subtitle = subtitle or "Explora la información tabular filtrada."

    # Detectar columnas numéricas para alinear a la derecha
    numeric_cols = [
        col for col in df.columns
        if df[col].dtype.kind in ("i", "f", "u")
    ]

    style_cell_conditional = [
        {"if": {"column_id": col}, "textAlign": "right"}
        for col in numeric_cols
    ]

    return html.Div(
        [
            html.Div(
                [
                    html.Div([
                        html.P(shown_title,    className="table-toolbar-title"),
                        html.P(shown_subtitle, className="table-toolbar-subtitle"),
                    ]),
                    html.Span(f"{len(df):,} registros", className="table-pill"),
                ],
                className="table-toolbar",
            ),
            dash_table.DataTable(
                id=table_id,
                columns=[
                    {
                        "name": str(col).replace("_", " ").title(),
                        "id": col,
                        "type": "numeric" if col in numeric_cols else "text",
                    }
                    for col in df.columns
                ],
                data=df.to_dict("records"),
                page_size=page_size,
                sort_action="native",
                filter_action="native",
                page_action="native",
                export_format="csv" if export else "none",
                export_headers="display",
                style_table={
                    "overflowX": "auto",
                    "borderRadius": "0 0 10px 10px",
                    "overflow": "hidden",
                },
                style_header={
                    "backgroundColor": "#1a3a5c",
                    "color": "white",
                    "fontWeight": "600",
                    "fontSize": "11px",
                    "textTransform": "uppercase",
                    "letterSpacing": "0.05em",
                    "padding": "10px 12px",
                    "border": "none",
                    "fontFamily": "'Inter', sans-serif",
                },
                style_cell={
                    "textAlign": "left",
                    "padding": "9px 12px",
                    "fontFamily": "'Inter', sans-serif",
                    "fontSize": "13px",
                    "color": "#1e293b",
                    "borderBottom": "1px solid #e2e8f0",
                    "borderLeft": "none",
                    "borderRight": "none",
                    "whiteSpace": "normal",
                    "height": "auto",
                    "maxWidth": "320px",
                    "overflow": "hidden",
                    "textOverflow": "ellipsis",
                },
                style_data={
                    "backgroundColor": "white",
                },
                style_data_conditional=[
                    {
                        "if": {"row_index": "odd"},
                        "backgroundColor": "#e8f0fb",
                    },
                    *style_cell_conditional,
                ],
                style_filter={
                    "backgroundColor": "#f8fafc",
                    "border": "none",
                    "borderTop": "1px solid #e2e8f0",
                    "padding": "6px 8px",
                },
            ),
        ]
    )
