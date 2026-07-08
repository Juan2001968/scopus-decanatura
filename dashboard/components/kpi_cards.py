from __future__ import annotations

from typing import Callable, Union

import dash_bootstrap_components as dbc
from dash import html

# Clase CSS de color por semántica → gradiente en ::before (ver styles.css)
_COLOR_CLASS = {
    "primary":   "c-blue",
    "secondary": "c-violet",
    "success":   "c-green",
    "warning":   "c-amber",
    "danger":    "c-rose",
    "info":      "c-indigo",
}


def _format_number(value: Union[int, float, None], decimals: int = 0) -> str:
    if value is None:
        return "—"
    try:
        if decimals > 0:
            return f"{float(value):,.{decimals}f}"
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return "—"


def create_kpi_card(
    title: str,
    value: str,
    subtitle: str = "",
    color: str = "primary",
    icon_class: str = "bi-bar-chart",
) -> dbc.Card:
    color_class = _COLOR_CLASS.get(color, "c-blue")

    return dbc.Card(
        dbc.CardBody(
            html.Div(
                [
                    html.P(title, className="kpi-title"),
                    html.H3(value, className="kpi-value"),
                    html.P(subtitle, className="kpi-subtitle"),
                ],
                className="kpi-inner",
            ),
            className="kpi-card-body",
        ),
        className=f"kpi-card h-100 {color_class}",
    )


# ---------------------------------------------------------------------------
# Tarjetas individuales reutilizables
#
# Cada constructor recibe el dict de KPIs y devuelve una ``dbc.Card`` con el
# mismo estilo visual. Esto permite componer filas con cualquier subconjunto y
# orden de tarjetas mediante ``create_kpi_row_custom``.
# ---------------------------------------------------------------------------


def _card_publicaciones(
    kpis: dict,
    title: str = "Publicaciones Uninorte",
    subtitle: str = "Producción del período",
) -> dbc.Card:
    return create_kpi_card(
        title=title,
        value=_format_number(kpis.get("publicaciones_3_anios")),
        subtitle=subtitle,
        color="primary",
        icon_class="bi-journals",
    )


def _card_citas(
    kpis: dict,
    title: str = "Citas totales",
    subtitle: str = "Impacto acumulado",
) -> dbc.Card:
    citas = kpis.get("citas", {})
    return create_kpi_card(
        title=title,
        value=_format_number(citas.get("total")),
        subtitle=subtitle,
        color="secondary",
        icon_class="bi-chat-quote",
    )


def _card_autocitas(kpis: dict) -> dbc.Card:
    citas_autocitas = kpis.get("autocitas_intragrupo")
    val = _format_number(citas_autocitas) if citas_autocitas is not None else "—"
    sub = "Citas dentro del grupo" if citas_autocitas is not None else "Dato no disponible"
    return create_kpi_card(
        title="Autocitas",
        value=val,
        subtitle=sub,
        color="info",
        icon_class="bi-filter-circle",
    )


def _card_h_index(kpis: dict) -> dbc.Card:
    # h-index calculado por sort de citas de las publicaciones filtradas:
    # h = mayor i tal que la i-ésima publicación más citada tiene >= i citas.
    return create_kpi_card(
        title=kpis.get("h_index_label", "H-index División"),
        value=_format_number(kpis.get("h_index")),
        subtitle="h pubs con ≥ h citas (período)",
        color="success",
        icon_class="bi-trophy",
    )


def _card_pct_q1q2(kpis: dict) -> dbc.Card:
    pct_q1q2 = kpis.get("pct_q1q2")
    val = f"{pct_q1q2:.1%}" if pct_q1q2 is not None else "—"
    sub = "Publicaciones en Q1 o Q2" if pct_q1q2 is not None else "Sin datos de cuartil"
    return create_kpi_card(
        title="% en Q1 o Q2",
        value=val,
        subtitle=sub,
        color="warning",
        icon_class="bi-award",
    )


def _card_profesores(kpis: dict) -> dbc.Card:
    profesores_activos = kpis.get("profesores_activos")
    val = _format_number(profesores_activos) if profesores_activos is not None else "—"
    return create_kpi_card(
        title="Profesores activos",
        value=val,
        subtitle="Con ≥1 publicación",
        color="danger",
        icon_class="bi-people",
    )


# Variantes con subtítulo de ámbito (Universidad vs División), reutilizadas por
# los dos bloques del resumen general.
def _card_publicaciones_uni(kpis: dict) -> dbc.Card:
    return _card_publicaciones(kpis, title="Publicaciones", subtitle="Universidad del Norte")


def _card_citas_uni(kpis: dict) -> dbc.Card:
    return _card_citas(kpis, title="Citas totales", subtitle="Universidad del Norte")


def _card_publicaciones_div(kpis: dict) -> dbc.Card:
    return _card_publicaciones(kpis, title="Publicaciones", subtitle="División de Ciencias Básicas")


def _card_citas_div(kpis: dict) -> dbc.Card:
    return _card_citas(kpis, title="Citas totales", subtitle="División de Ciencias Básicas")


def _card_h_index_uni(kpis: dict) -> dbc.Card:
    # H-index institucional calculado por sort de citas sobre TODAS las
    # publicaciones de Uninorte (tabla ``publicacion`` completa) — misma
    # fórmula que el resto de niveles. El dict proviene de
    # ``_compute_universidad_kpis``; su clave ``h_index`` ya es el valor de la
    # Universidad, distinto del H-index de la División.
    return create_kpi_card(
        title="H-index Universidad",
        value=_format_number(kpis.get("h_index")),
        subtitle="Universidad del Norte",
        color="success",
        icon_class="bi-trophy",
    )


# ---------------------------------------------------------------------------
# Flags de visibilidad de tarjetas
#
# OCULTO temporalmente: con el flag en False la tarjeta NO se renderiza en
# NINGUNA fila de KPIs (área, profesor, División, Universidad, Perfil
# Profesor) y el grid se reajusta solo. Para reactivarla en todas las vistas
# basta poner el flag en True; los constructores (_card_autocitas,
# _card_profesores) y las claves del registro quedan intactos.
#
# Motivo (auditoría 2026-07-06, AUDITORIA.md):
# - Autocitas: se alimenta de autocitas_v1.csv, generado ANTES de la
#   reparación del matching; el valor no es reproducible (hallazgo 3).
# - Profesores activos: cuenta el roster completo del área, no los
#   profesores con >=1 publicación que anuncia el subtítulo (hallazgo 6).
# ---------------------------------------------------------------------------
SHOW_AUTOCITAS = False
SHOW_PROFESORES_ACTIVOS = False


def _hidden_card_keys() -> set[str]:
    """Claves de tarjeta desactivadas por los flags de visibilidad."""
    hidden: set[str] = set()
    if not SHOW_AUTOCITAS:
        hidden.add("autocitas")
    if not SHOW_PROFESORES_ACTIVOS:
        hidden.add("profesores")
    return hidden


# Registro de tarjetas disponibles por clave, para componer filas a la carta.
_CARD_BUILDERS: dict[str, Callable[[dict], dbc.Card]] = {
    # Tarjetas "clásicas" (orden por defecto de create_kpi_row)
    "publicaciones": _card_publicaciones,
    "citas":         _card_citas,
    "autocitas":     _card_autocitas,
    "h_index":       _card_h_index,
    "pct_q1q2":      _card_pct_q1q2,
    "profesores":    _card_profesores,
    # Variantes con ámbito explícito
    "publicaciones_uni": _card_publicaciones_uni,
    "citas_uni":         _card_citas_uni,
    "h_index_uni":       _card_h_index_uni,
    "publicaciones_div": _card_publicaciones_div,
    "citas_div":         _card_citas_div,
}

# Orden por defecto de la fila completa de 6 tarjetas.
_DEFAULT_CARDS = [
    "publicaciones", "citas", "autocitas", "h_index", "pct_q1q2", "profesores",
]


def create_kpi_row_custom(kpis: dict, cards: list[str]) -> dbc.Row:
    """Construye una fila de KPIs con un subconjunto y orden de tarjetas.

    ``cards`` es una lista de claves de :data:`_CARD_BUILDERS`. El ancho de las
    columnas se reparte automáticamente para llenar la fila (12 columnas
    Bootstrap), manteniendo el mismo estilo visual de las tarjetas.
    """
    # OCULTO temporalmente: descartar tarjetas desactivadas por flag
    # (ver SHOW_AUTOCITAS / SHOW_PROFESORES_ACTIVOS arriba).
    cards = [key for key in cards if key not in _hidden_card_keys()]
    n = len(cards) or 1
    # Reparte las 12 columnas; nunca menos de 2 (≥6 tarjetas) ni más de 12.
    xl = min(12, max(2, 12 // n))
    lg = 4 if n > 3 else min(12, max(4, 12 // n))

    cols = []
    for key in cards:
        builder = _CARD_BUILDERS.get(key)
        if builder is None:
            continue
        cols.append(
            dbc.Col(builder(kpis), xl=xl, lg=lg, md=6, sm=6, xs=12)
        )

    return dbc.Row(cols, className="g-3 kpi-wrapper")


def create_kpi_row(kpis: dict) -> dbc.Row:
    """
    KPIs para Decanatura (fila completa de 6 tarjetas):
    1. Publicaciones 2014–2025
    2. Total citas
    3. Citas excluyendo autocitas
    4. H-index del ámbito (calculado por sort de citas del período)
    5. % publicaciones Q1 o Q2
    6. Profesores activos

    Las tarjetas desactivadas por flag (SHOW_AUTOCITAS,
    SHOW_PROFESORES_ACTIVOS) se omiten y el grid se reajusta; delega en
    :func:`create_kpi_row_custom`, que aplica el filtrado.
    """
    return create_kpi_row_custom(kpis, _DEFAULT_CARDS)
