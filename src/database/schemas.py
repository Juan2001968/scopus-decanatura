"""
Esquemas Pydantic para validación de datos durante el pipeline ETL.

Validan formato e integridad de los registros antes de la inserción
en la base de datos, proporcionando mensajes de error claros.
"""

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class ProfesorCreate(BaseModel):
    """Datos requeridos para crear un registro de profesor."""

    model_config = ConfigDict(from_attributes=True)

    nombre_normalizado: str
    orcid: str
    id_departamento: int
    activo: bool = True

    @field_validator("orcid")
    @classmethod
    def validate_orcid_format(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", v):
            raise ValueError(
                "ORCID debe tener formato XXXX-XXXX-XXXX-XXXX "
                f"(recibido: '{v}')"
            )
        return v


class AutorScopusCreate(BaseModel):
    """Datos requeridos para crear un perfil de autor Scopus."""

    model_config = ConfigDict(from_attributes=True)

    scopus_author_id: str
    nombre_scopus: str
    id_profesor: int
    subject_area: Optional[str] = None
    numero_documentos_scopus: Optional[int] = None


class PublicacionCreate(BaseModel):
    """Datos requeridos para crear un registro de publicación."""

    model_config = ConfigDict(from_attributes=True)

    eid: str
    doi: Optional[str] = None
    titulo: str
    anio_publicacion: int
    tipo_documental: Optional[str] = None
    idioma: Optional[str] = None
    cited_by_count: int = 0
    open_access: Optional[str] = None
    id_fuente: Optional[int] = None

    @field_validator("eid")
    @classmethod
    def validate_eid_format(cls, v: str) -> str:
        if not v.startswith("2-s2.0-"):
            raise ValueError(
                f"EID debe empezar con '2-s2.0-' (recibido: '{v}')"
            )
        return v

    @field_validator("anio_publicacion")
    @classmethod
    def validate_anio_range(cls, v: int) -> int:
        if not 1900 <= v <= 2030:
            raise ValueError(
                f"Año de publicación debe estar entre 1900 y 2030 "
                f"(recibido: {v})"
            )
        return v


class FuenteCreate(BaseModel):
    """Datos requeridos para crear un registro de fuente."""

    model_config = ConfigDict(from_attributes=True)

    source_title: str
    issn: Optional[str] = None
    tipo_fuente: Optional[str] = None
    publisher: Optional[str] = None


class LogIngestaCreate(BaseModel):
    """Datos requeridos para crear un registro de auditoría ETL."""

    model_config = ConfigDict(from_attributes=True)

    fase: str
    archivo_origen: Optional[str] = None
    registros_crudos: Optional[int] = None
    registros_limpios: Optional[int] = None
    registros_nuevos: Optional[int] = None
    notas: Optional[str] = None
