"""Estilo y etiquetas compartidos para las áreas de investigación.

Los nombres de departamento viven en la BD (``biblio.departamento.nombre``)
y han cambiado con el tiempo ("Departamento de Química y Biología" →
"Biología y Química", etc.).  Cualquier dict keyed por el nombre literal
se desincroniza en silencio: los colores caen al fallback y las etiquetas
truncadas pierden significado.

Este módulo centraliza la resolución por *contenido* del nombre (substring
insensible a acentos), de modo que los tres colores institucionales y las
abreviaturas sobreviven a renombres menores del catálogo.

Uso típico en las páginas del dashboard::

    from dashboard.area_style import color_area, discrete_map, wrap_area

    px.scatter(..., color="departamento", color_discrete_map=discrete_map(df["departamento"]))
    go.Bar(y=[wrap_area(d) for d in df["departamento"]], marker_color=[color_area(d) for d in ...])
"""

from __future__ import annotations

import unicodedata
from typing import Dict, Iterable, Tuple

# Colores canónicos por área (mismos tonos que usaba COLORES_DEPT).
COLOR_MAT = "#1a3a5c"   # Matemáticas, Estadística y Ciencia de Datos
COLOR_BIO = "#2563a8"   # Biología y Química
COLOR_FIS = "#b45309"   # Física y Geociencias
COLOR_OTRO = "#64748b"  # fallback para nombres no reconocidos


def _sin_acentos(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()


def clave_area(nombre: object) -> str | None:
    """Clave canónica ('MAT' | 'BIO' | 'FIS') o None si no se reconoce."""
    n = _sin_acentos(nombre or "")
    if "matem" in n or "estadist" in n:
        return "MAT"
    if "biolog" in n or "quimic" in n:
        return "BIO"
    if "fisic" in n or "geocien" in n:
        return "FIS"
    return None


_COLORES: Dict[str, str] = {"MAT": COLOR_MAT, "BIO": COLOR_BIO, "FIS": COLOR_FIS}

# Abreviatura media (leyendas, celdas de tabla) y píldora corta (chips).
_ABREV: Dict[str, str] = {
    "MAT": "Mat., Est. y C. Datos",
    "BIO": "Biología y Química",
    "FIS": "Física y Geociencias",
}
_PILL: Dict[str, Tuple[str, str, str]] = {
    "MAT": ("Mat.", COLOR_MAT, "#e8f0fb"),
    "BIO": ("B&Q",  COLOR_BIO, "#dbeafe"),
    "FIS": ("Fís.", COLOR_FIS, "#fef3c7"),
}


def color_area(nombre: object, default: str = COLOR_OTRO) -> str:
    """Color institucional del área, resuelto por contenido del nombre."""
    return _COLORES.get(clave_area(nombre), default)


def discrete_map(nombres: Iterable[object]) -> Dict[str, str]:
    """``color_discrete_map`` para plotly express a partir de los valores reales."""
    return {str(n): color_area(n) for n in dict.fromkeys(str(x) for x in nombres)}


def abreviar_area(nombre: object) -> str:
    """Nombre corto legible para leyendas y celdas ("Mat., Est. y C. Datos")."""
    clave = clave_area(nombre)
    if clave:
        return _ABREV[clave]
    return str(nombre)[:22]


def pill_area(nombre: object) -> Tuple[str, str, str]:
    """(etiqueta, color de texto, color de fondo) para chips compactos."""
    clave = clave_area(nombre)
    if clave:
        return _PILL[clave]
    return (str(nombre)[:4], COLOR_OTRO, "#f1f5f9")


def wrap_area(nombre: object, width: int = 18) -> str:
    """Nombre completo con saltos ``<br>`` para ejes de plotly.

    Envuelve por palabras a un ancho aproximado; nunca corta palabras ni
    pierde texto, a diferencia del viejo ``d.split()[-1][:10]``.
    """
    palabras = str(nombre).split()
    lineas: list[str] = []
    actual = ""
    for p in palabras:
        if actual and len(actual) + 1 + len(p) > width:
            lineas.append(actual)
            actual = p
        else:
            actual = f"{actual} {p}".strip()
    if actual:
        lineas.append(actual)
    return "<br>".join(lineas)
