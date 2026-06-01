# Scopus Decanatura — Sistema de Monitoreo Bibliométrico

Sistema de monitoreo bibliométrico institucional que permite analizar la producción científica de una división académica a partir de datos de Scopus. Incluye un pipeline ETL para la ingesta, limpieza y carga de datos, una base de datos relacional PostgreSQL, y un dashboard interactivo construido con Dash para visualizar indicadores por profesor, departamento y división.

## Stack Tecnológico

- **Lenguaje:** Python 3.10+
- **Dashboard:** Dash + Dash Bootstrap Components + Plotly
- **Base de datos:** PostgreSQL + SQLAlchemy (ORM)
- **ETL:** pandas, pybliometrics, fuzzywuzzy
- **Testing:** pytest

## Estructura del Proyecto

```
scopus_decanatura/
│
├── config/                  # Configuración del sistema y base de datos
├── data/
│   ├── raw/                 # CSV crudos de Scopus y profesores
│   ├── interim/             # Datos intermedios
│   ├── processed/           # Datos finales para carga
│   └── external/            # Datos externos (Scimago, Scopus Source List)
├── notebooks/               # Notebooks de exploración y validación
├── src/
│   ├── etl/                 # Pipeline de ingesta, limpieza, normalización y carga
│   ├── database/            # Conexión, modelos ORM, esquemas
│   ├── api_scopus/          # Cliente para la API de Scopus
│   ├── services/            # Métricas, agregaciones, consultas
│   └── utils/               # Utilidades: normalización, deduplicación, validación
├── dashboard/
│   ├── components/          # Componentes reutilizables del dashboard
│   ├── pages/               # Páginas/tabs del dashboard
│   ├── callbacks/           # Callbacks de Dash
│   └── assets/              # Estilos y recursos estáticos
├── tests/                   # Tests unitarios
├── docs/                    # Documentación del proyecto
├── logs/                    # Archivos de log
├── scripts/                 # Scripts de ejecución
├── .env.example             # Variables de entorno de ejemplo
├── .gitignore
├── requirements.txt
└── pyproject.toml
```

## Instalación

```bash
# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con las credenciales correspondientes
```

## Estado Actual

**Fase: scaffolding** — estructura creada, sin lógica implementada.
