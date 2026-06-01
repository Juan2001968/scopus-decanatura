from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html


def create_navbar() -> dbc.Navbar:
    """Navbar institucional oscura."""
    brand = html.Div(
        [
            html.Div(
                html.I(className="bi bi-bar-chart-line-fill"),
                className="navbar-brand-icon",
            ),
            html.Div(
                [
                    html.P("Monitor Bibliométrico", className="navbar-brand-title"),
                    html.P(
                        "Sistema de Monitoreo Bibliométrico · División de Ciencias Básicas",
                        className="navbar-brand-subtitle",
                    ),
                ],
                className="navbar-brand-text",
            ),
        ],
        className="navbar-brand-block",
    )

    right_side = html.Div(
        [
            html.Span(
                "Scopus · PostgreSQL · Dash",
                className="navbar-status-badge",
            )
        ]
    )

    return dbc.Navbar(
        dbc.Container(
            [
                brand,
                right_side,
            ],
            fluid=True,
            className="d-flex justify-content-between align-items-center",
        ),
        dark=True,
        className="top-navbar",
    )
