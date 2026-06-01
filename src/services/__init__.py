"""
Paquete de servicios: metricas, agregaciones y consultas reutilizables.

Modulos:

- **queries**: capa de acceso a datos (SQL → pd.DataFrame).
- **metrics**: calculo de indicadores bibliometricos (funciones puras).
- **aggregations**: agregaciones de alto nivel por profesor,
  departamento y Division para el dashboard.
"""

from src.services.aggregations import (
    analisis_open_access,
    evolucion_temporal_comparativa,
    perfil_profesor,
    resumen_departamento,
    resumen_division,
    tabla_comparativa_profesores,
    top_publicaciones_citadas,
)
