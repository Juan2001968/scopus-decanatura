from __future__ import annotations

import dash
import dash_bootstrap_components as dbc

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
        "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap",
    ],
    suppress_callback_exceptions=True,
    title="Monitor Bibliométrico — División de Ciencias Básicas",
    update_title="Cargando...",
)

server = app.server
