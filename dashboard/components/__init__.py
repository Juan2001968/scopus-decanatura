"""
Componentes reutilizables del dashboard.

Modulos:

- **navbar**: barra de navegacion superior.
- **filters**: franja de filtros globales.
- **kpi_cards**: tarjetas de indicadores clave.
- **data_table**: tabla interactiva con filtrado y exportacion.
"""

from dashboard.components.navbar import create_navbar
from dashboard.components.filters import create_filters
from dashboard.components.kpi_cards import (
    create_kpi_card,
    create_kpi_row,
    create_kpi_row_custom,
)
from dashboard.components.data_table import create_data_table
