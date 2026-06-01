"""
Paginas (tabs) del dashboard bibliometrico.

Modulos:

- **resumen_division**: vista general de la Division completa.
- **perfil_profesor**: perfil detallado de un profesor individual.
- **analisis_impacto**: metricas de impacto y citas.
- **calidad_fuente**: cuartiles SJR y metricas de fuente.
- **colaboracion_tematicas**: coautoria, keywords, Open Access, idioma.
- **explorador_datos**: tabla interactiva para explorar registros.
"""

from dashboard.pages.resumen_division import layout_resumen
from dashboard.pages.perfil_profesor import layout_profesor
from dashboard.pages.analisis_impacto import layout_impacto
from dashboard.pages.calidad_fuente import layout_fuentes
from dashboard.pages.colaboracion_tematicas import layout_colaboracion
from dashboard.pages.explorador_datos import layout_explorador
