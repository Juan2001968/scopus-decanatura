"""
Modelos ORM del sistema bibliométrico.

Define las 8 tablas del esquema ``biblio`` en PostgreSQL:
departamento, profesor, autor_scopus, fuente, fuente_metrica,
publicacion, publicacion_profesor (asociativa) y log_ingesta.

Todos los modelos usan el estilo SQLAlchemy 2.0 (``Mapped`` + ``mapped_column``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.db_config import Base

SCHEMA = "biblio"
"""Nombre del esquema PostgreSQL donde viven todas las tablas."""


# ---------------------------------------------------------------------------
# Tabla asociativa muchos-a-muchos (definida primero para usar como secondary)
# ---------------------------------------------------------------------------

publicacion_profesor_table = Table(
    "publicacion_profesor",
    Base.metadata,
    Column(
        "id_publicacion",
        Integer,
        ForeignKey(f"{SCHEMA}.publicacion.id_publicacion"),
        primary_key=True,
    ),
    Column(
        "id_profesor",
        Integer,
        ForeignKey(f"{SCHEMA}.profesor.id_profesor"),
        primary_key=True,
    ),
    Column("es_autor_correspondencia", Boolean, default=False),
    Column("posicion_autoria", Integer, nullable=True),
    Column("metodo_vinculacion", String(30), nullable=False),
    Column(
        "fecha_vinculacion",
        DateTime,
        server_default=func.now(),
        nullable=False,
    ),
    schema=SCHEMA,
)


# ---------------------------------------------------------------------------
# Tablas de dimensión
# ---------------------------------------------------------------------------


class Departamento(Base):
    """Departamento académico de la División.

    Tabla de dimensión con los 3 departamentos. Cada departamento agrupa
    profesores y permite agregaciones organizacionales.

    Relaciones:
        profesores → lista de :class:`Profesor` del departamento.
    """

    __tablename__ = "departamento"
    __table_args__ = {"schema": SCHEMA}

    id_departamento: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True,
    )
    nombre: Mapped[str] = mapped_column(String(200), unique=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    division: Mapped[str] = mapped_column(String(200))

    profesores: Mapped[list[Profesor]] = relationship(
        back_populates="departamento",
    )

    def __repr__(self) -> str:
        return f"<Departamento(id={self.id_departamento}, codigo='{self.codigo}')>"


class Fuente(Base):
    """Revista, conference proceedings o book series.

    Tabla de dimensión para las fuentes de publicación. Incluye
    metadatos editoriales y se vincula con métricas anuales.

    Relaciones:
        publicaciones → lista de :class:`Publicacion` en esta fuente.
        metricas → lista de :class:`FuenteMetrica` (SJR, CiteScore, etc.).
    """

    __tablename__ = "fuente"
    __table_args__ = (
        UniqueConstraint("source_title", "issn", name="uq_fuente_title_issn"),
        Index("ix_fuente_issn", "issn"),
        {"schema": SCHEMA},
    )

    id_fuente: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True,
    )
    source_title: Mapped[str] = mapped_column(String(500))
    abbreviated_source_title: Mapped[Optional[str]] = mapped_column(String(200))
    issn: Mapped[Optional[str]] = mapped_column(String(9))
    tipo_fuente: Mapped[Optional[str]] = mapped_column(String(100))
    publisher: Mapped[Optional[str]] = mapped_column(String(300))

    publicaciones: Mapped[list[Publicacion]] = relationship(
        back_populates="fuente",
    )
    metricas: Mapped[list[FuenteMetrica]] = relationship(
        back_populates="fuente",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        title = (self.source_title or "")[:50]
        return f"<Fuente(id={self.id_fuente}, titulo='{title}')>"


class FuenteMetrica(Base):
    """Métricas bibliométricas anuales de una fuente.

    Un registro por fuente-año, con indicadores de impacto provenientes
    de Scimago Journal Rank o Scopus Source List.

    Relaciones:
        fuente → :class:`Fuente` a la que pertenecen las métricas.
    """

    __tablename__ = "fuente_metrica"
    __table_args__ = (
        UniqueConstraint("id_fuente", "anio", name="uq_fuente_metrica_anio"),
        {"schema": SCHEMA},
    )

    id_fuente_metrica: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True,
    )
    id_fuente: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.fuente.id_fuente"),
    )
    anio: Mapped[int]
    sjr: Mapped[Optional[float]]
    snip: Mapped[Optional[float]]
    citescore: Mapped[Optional[float]]
    cuartil_sjr: Mapped[Optional[str]] = mapped_column(String(2))
    percentil_sjr: Mapped[Optional[float]]
    cuartil_citescore: Mapped[Optional[str]] = mapped_column(String(2))
    fuente_datos: Mapped[Optional[str]] = mapped_column(String(50))

    fuente: Mapped[Fuente] = relationship(back_populates="metricas")

    def __repr__(self) -> str:
        return f"<FuenteMetrica(fuente={self.id_fuente}, anio={self.anio})>"


# ---------------------------------------------------------------------------
# Tablas de actores
# ---------------------------------------------------------------------------


class Profesor(Base):
    """Profesor de planta de la División, consolidado por ORCID.

    Cada registro representa un profesor único. Un mismo profesor puede
    tener múltiples perfiles en Scopus (ver :class:`AutorScopus`).

    Relaciones:
        departamento → :class:`Departamento` al que pertenece.
        autores_scopus → perfiles Scopus del profesor.
        publicaciones → :class:`Publicacion` vía tabla asociativa (viewonly).
    """

    __tablename__ = "profesor"
    __table_args__ = {"schema": SCHEMA}

    id_profesor: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True,
    )
    nombre_normalizado: Mapped[str] = mapped_column(String(300))
    orcid: Mapped[str] = mapped_column(String(19), unique=True)
    id_departamento: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.departamento.id_departamento"),
    )
    activo: Mapped[bool] = mapped_column(default=True)
    h_index: Mapped[Optional[int]]
    h_index_fecha: Mapped[Optional[datetime]]
    fecha_creacion: Mapped[datetime] = mapped_column(
        server_default=func.now(),
    )
    fecha_actualizacion: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(),
    )

    departamento: Mapped[Departamento] = relationship(
        back_populates="profesores",
    )
    autores_scopus: Mapped[list[AutorScopus]] = relationship(
        back_populates="profesor",
        cascade="all, delete-orphan",
    )
    publicaciones: Mapped[list[Publicacion]] = relationship(
        secondary=publicacion_profesor_table,
        back_populates="profesores",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Profesor(id={self.id_profesor}, orcid='{self.orcid}', "
            f"nombre='{self.nombre_normalizado}')>"
        )


class AutorScopus(Base):
    """Perfil de autor en Scopus asociado a un profesor.

    Resuelve el problema de que un mismo profesor tiene múltiples
    Scopus Author IDs (variantes de nombre, fusiones de perfiles).

    Relaciones:
        profesor → :class:`Profesor` al que pertenece este perfil.
    """

    __tablename__ = "autor_scopus"
    __table_args__ = {"schema": SCHEMA}

    id_autor_scopus: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True,
    )
    scopus_author_id: Mapped[str] = mapped_column(String(20), unique=True)
    nombre_scopus: Mapped[str] = mapped_column(String(300))
    id_profesor: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.profesor.id_profesor"),
    )
    subject_area: Mapped[Optional[str]] = mapped_column(String(200))
    numero_documentos_scopus: Mapped[Optional[int]]

    profesor: Mapped[Profesor] = relationship(
        back_populates="autores_scopus",
    )

    def __repr__(self) -> str:
        return (
            f"<AutorScopus(id={self.id_autor_scopus}, "
            f"scopus_id='{self.scopus_author_id}')>"
        )


# ---------------------------------------------------------------------------
# Tabla de hechos
# ---------------------------------------------------------------------------


class Publicacion(Base):
    """Documento bibliográfico indexado en Scopus.

    Tabla de hechos central del sistema. Un registro por documento único,
    identificado por EID. Almacena metadatos completos de la publicación.

    Relaciones:
        fuente → :class:`Fuente` donde se publicó.
        profesores → lista de :class:`Profesor` vía tabla asociativa (viewonly).
    """

    __tablename__ = "publicacion"
    __table_args__ = (
        Index("ix_publicacion_anio", "anio_publicacion"),
        Index("ix_publicacion_doi", "doi"),
        {"schema": SCHEMA},
    )

    id_publicacion: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True,
    )
    eid: Mapped[str] = mapped_column(String(30), unique=True)
    doi: Mapped[Optional[str]] = mapped_column(String(200))
    titulo: Mapped[str] = mapped_column(Text)
    anio_publicacion: Mapped[int]
    tipo_documental: Mapped[Optional[str]] = mapped_column(String(100))
    idioma: Mapped[Optional[str]] = mapped_column(String(50))
    cited_by_count: Mapped[int] = mapped_column(default=0)
    open_access: Mapped[Optional[str]] = mapped_column(String(50))
    publication_stage: Mapped[Optional[str]] = mapped_column(String(50))
    volumen: Mapped[Optional[str]] = mapped_column(String(50))
    issue: Mapped[Optional[str]] = mapped_column(String(50))
    paginas: Mapped[Optional[str]] = mapped_column(String(100))
    publisher: Mapped[Optional[str]] = mapped_column(String(300))
    correspondence_address: Mapped[Optional[str]] = mapped_column(Text)
    affiliations: Mapped[Optional[str]] = mapped_column(Text)
    indexed_keywords: Mapped[Optional[str]] = mapped_column(Text)
    referencias_raw: Mapped[Optional[str]] = mapped_column(Text)
    pubmed_id: Mapped[Optional[str]] = mapped_column(String(20))
    id_fuente: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{SCHEMA}.fuente.id_fuente"),
    )
    fecha_ingesta: Mapped[datetime] = mapped_column(
        server_default=func.now(),
    )

    fuente: Mapped[Optional[Fuente]] = relationship(
        back_populates="publicaciones",
    )
    profesores: Mapped[list[Profesor]] = relationship(
        secondary=publicacion_profesor_table,
        back_populates="publicaciones",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<Publicacion(id={self.id_publicacion}, eid='{self.eid}')>"


# ---------------------------------------------------------------------------
# Clase ORM sobre la tabla asociativa (acceso a columnas extra)
# ---------------------------------------------------------------------------


class PublicacionProfesor(Base):
    """Vinculación publicación-profesor con metadatos de asociación.

    Mapea la tabla asociativa ``publicacion_profesor`` como clase ORM
    para permitir acceso directo a las columnas adicionales
    (``metodo_vinculacion``, ``posicion_autoria``, etc.).

    Para navegación simple entre publicaciones y profesores, usar las
    relaciones ``Profesor.publicaciones`` y ``Publicacion.profesores``.
    Para crear o consultar los metadatos de vinculación, usar esta clase.
    """

    __table__ = publicacion_profesor_table

    def __repr__(self) -> str:
        return (
            f"<PublicacionProfesor(pub={self.id_publicacion}, "
            f"prof={self.id_profesor}, metodo='{self.metodo_vinculacion}')>"
        )


# ---------------------------------------------------------------------------
# Tabla de auditoría
# ---------------------------------------------------------------------------


class LogIngesta(Base):
    """Registro de auditoría del pipeline ETL.

    Cada ejecución del pipeline (ingesta, vinculación, enriquecimiento)
    crea un registro con conteos y estadísticas para trazabilidad.
    """

    __tablename__ = "log_ingesta"
    __table_args__ = {"schema": SCHEMA}

    id_log: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True,
    )
    fecha_ejecucion: Mapped[datetime] = mapped_column(
        server_default=func.now(),
    )
    fase: Mapped[str] = mapped_column(String(50))
    archivo_origen: Mapped[Optional[str]] = mapped_column(String(300))
    registros_crudos: Mapped[Optional[int]]
    registros_limpios: Mapped[Optional[int]]
    registros_nuevos: Mapped[Optional[int]]
    registros_duplicados: Mapped[Optional[int]]
    registros_error: Mapped[Optional[int]]
    duracion_segundos: Mapped[Optional[float]]
    notas: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<LogIngesta(id={self.id_log}, fase='{self.fase}')>"
