"""
Carga final de datos procesados a PostgreSQL.

Persiste los DataFrames producidos por las fases ETL anteriores
(ingesta, limpieza, normalización, enriquecimiento, vinculación)
en las tablas del esquema ``biblio`` usando SQLAlchemy ORM.
Implementa upsert (insertar o actualizar) para permitir recargas
incrementales sin duplicados.

Fase 7 (final) del pipeline ETL.
"""

from __future__ import annotations
from src.services.metrics import calcular_h_index_desde_citas
from datetime import datetime
from typing import Dict, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.db_config import get_session
from src.database.models import (
    AutorScopus,
    Departamento,
    Fuente,
    FuenteMetrica,
    LogIngesta,
    Publicacion,
    Profesor,
    publicacion_profesor_table,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _normalize_source_key(title: object) -> str:
    """Normaliza un source_title para comparación (lowercase, strip)."""
    if pd.isna(title):
        return ""
    return str(title).strip().lower()


def _safe_str(value: object) -> Optional[str]:
    """Convierte valor a string limpio o None si es NaN/vacío."""
    if pd.isna(value):
        return None
    s = str(value).strip()
    return s if s and s not in ("nan", "None") else None


def _safe_str_max(value: object, max_len: int) -> Optional[str]:
    """Convierte a string limpio y trunca al largo máximo."""
    s = _safe_str(value)
    if s is None:
        return None
    return s[:max_len]


def _safe_int(value: object, default: int = 0) -> int:
    """Convierte valor a int, retornando default si es NaN."""
    if pd.isna(value):
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Funciones de carga
# ---------------------------------------------------------------------------


def load_departamentos(session: Session) -> Dict[str, int]:
    """Verifica que los departamentos existen y retorna mapa codigo → id.

    Los departamentos deben haber sido insertados previamente por
    ``seed_departamentos`` en ``init_db.py``.

    Parameters
    ----------
    session:
        Sesión de SQLAlchemy activa.

    Returns
    -------
    dict[str, int]
        Diccionario ``{codigo_departamento: id_departamento}``.

    Raises
    ------
    RuntimeError
        Si la tabla departamento está vacía.

    Example
    -------
    >>> with get_session() as session:
    ...     dept_map = load_departamentos(session)
    ...     dept_map["MAT_EST"]
    1
    """
    deptos = session.query(Departamento).all()
    if not deptos:
        raise RuntimeError(
            "La tabla departamento esta vacia. "
            "Ejecuta scripts/init_database.py primero para sembrar "
            "los departamentos."
        )

    dept_map = {d.codigo: d.id_departamento for d in deptos}
    logger.info(
        "Departamentos cargados: %d (%s)",
        len(dept_map),
        ", ".join(sorted(dept_map.keys())),
    )
    return dept_map


def load_profesores(
    session: Session,
    df_profesores: pd.DataFrame,
    dept_map: Dict[str, int],
) -> Dict[str, int]:
    """Carga profesores en la tabla profesor (upsert por ORCID).

    Para cada fila busca si el ORCID ya existe. Si existe, actualiza
    ``nombre_normalizado`` (si cambió) y ``fecha_actualizacion``.
    Si no existe, inserta un nuevo registro.

    Parameters
    ----------
    session:
        Sesión de SQLAlchemy activa.
    df_profesores:
        DataFrame con columnas ``orcid``, ``nombre_normalizado``,
        ``departamento_codigo``.
    dept_map:
        Diccionario ``{codigo: id_departamento}`` de
        ``load_departamentos``.

    Returns
    -------
    dict[str, int]
        Diccionario ``{orcid: id_profesor}``.

    Example
    -------
    >>> prof_map = load_profesores(session, df_profs, dept_map)
    >>> prof_map["0000-0001-2345-6789"]
    42
    """
    if df_profesores.empty:
        logger.warning("DataFrame de profesores vacio -- nada que cargar")
        return {}

    prof_map: Dict[str, int] = {}
    inserted = 0
    updated = 0
    errors = 0

    # Pre-fetch profesores existentes para evitar N queries
    existing_profs: Dict[str, Profesor] = {
        p.orcid: p for p in session.query(Profesor).all()
    }

    for _, row in df_profesores.iterrows():
        orcid = _safe_str(row.get("orcid"))
        nombre = _safe_str(row.get("nombre_normalizado"))
        dept_code = _safe_str(row.get("departamento_codigo"))

        if not orcid or not nombre:
            errors += 1
            continue

        id_depto = dept_map.get(dept_code)
        if id_depto is None:
            logger.warning(
                "Departamento '%s' no encontrado para profesor ORCID=%s",
                dept_code, orcid,
            )
            errors += 1
            continue

        existing = existing_profs.get(orcid)
        if existing:
            if existing.nombre_normalizado != nombre:
                existing.nombre_normalizado = nombre
            existing.id_departamento = id_depto
            existing.fecha_actualizacion = datetime.now()
            prof_map[orcid] = existing.id_profesor
            updated += 1
        else:
            new_prof = Profesor(
                orcid=orcid,
                nombre_normalizado=nombre,
                id_departamento=id_depto,
                activo=True,
            )
            session.add(new_prof)
            session.flush()
            prof_map[orcid] = new_prof.id_profesor
            existing_profs[orcid] = new_prof
            inserted += 1

    session.flush()

    logger.info(
        "Profesores: %d insertados, %d actualizados, %d errores",
        inserted, updated, errors,
    )
    return prof_map


def load_autores_scopus(
    session: Session,
    df_autores_scopus: pd.DataFrame,
    prof_map: Dict[str, int],
) -> None:
    """Carga perfiles Scopus en la tabla autor_scopus (upsert por scopus_author_id).

    Para cada fila resuelve ``id_profesor`` vía ``prof_map[orcid]``.
    Si el ``scopus_author_id`` ya existe, actualiza; si no, inserta.

    Parameters
    ----------
    session:
        Sesión de SQLAlchemy activa.
    df_autores_scopus:
        DataFrame con columnas ``scopus_author_id``, ``nombre_scopus``,
        ``orcid``, ``subject_area``, ``numero_documentos_scopus``.
    prof_map:
        Diccionario ``{orcid: id_profesor}`` de ``load_profesores``.
    """
    if df_autores_scopus.empty:
        logger.warning("DataFrame de autores Scopus vacio")
        return

    inserted = 0
    updated = 0
    errors = 0

    # Pre-fetch existentes
    existing_autores: Dict[str, AutorScopus] = {
        a.scopus_author_id: a
        for a in session.query(AutorScopus).all()
    }

    for _, row in df_autores_scopus.iterrows():
        scopus_id = _safe_str(row.get("scopus_author_id"))
        orcid = _safe_str(row.get("orcid"))
        nombre = _safe_str(row.get("nombre_scopus"))

        if not scopus_id or not orcid:
            errors += 1
            continue

        id_profesor = prof_map.get(orcid)
        if id_profesor is None:
            logger.warning(
                "ORCID '%s' no encontrado en prof_map para scopus_id=%s",
                orcid, scopus_id,
            )
            errors += 1
            continue

        subject = _safe_str(row.get("subject_area"))
        n_docs = row.get("numero_documentos_scopus")
        n_docs_int = _safe_int(n_docs) if pd.notna(n_docs) else None

        existing = existing_autores.get(scopus_id)
        if existing:
            existing.nombre_scopus = nombre or existing.nombre_scopus
            existing.id_profesor = id_profesor
            existing.subject_area = subject
            existing.numero_documentos_scopus = n_docs_int
            updated += 1
        else:
            new_autor = AutorScopus(
                scopus_author_id=scopus_id,
                nombre_scopus=nombre or "",
                id_profesor=id_profesor,
                subject_area=subject,
                numero_documentos_scopus=n_docs_int,
            )
            session.add(new_autor)
            inserted += 1

    session.flush()

    logger.info(
        "Autores Scopus: %d insertados, %d actualizados, %d errores",
        inserted, updated, errors,
    )


def load_fuentes(
    session: Session,
    df_fuentes: pd.DataFrame,
) -> Dict[str, int]:
    """Carga fuentes en la tabla fuente (upsert por ISSN o source_title).

    Busca primero por ISSN (preferido); si no hay ISSN o no coincide,
    busca por ``source_title`` exacto como fallback.

    Parameters
    ----------
    session:
        Sesión de SQLAlchemy activa.
    df_fuentes:
        DataFrame con columnas ``source_title``,
        ``abbreviated_source_title``, ``issn``, ``tipo_fuente``,
        ``publisher``.

    Returns
    -------
    dict[str, int]
        Diccionario ``{source_title_normalizado: id_fuente}`` para
        vincular publicaciones en fases posteriores.

    Example
    -------
    >>> fuente_map = load_fuentes(session, df_fuentes)
    >>> fuente_map["nature materials"]
    17
    """
    if df_fuentes.empty:
        logger.warning("DataFrame de fuentes vacio")
        return {}

    fuente_map: Dict[str, int] = {}
    inserted = 0
    updated = 0

    # Pre-fetch fuentes existentes
    existing_by_issn: Dict[str, Fuente] = {}
    existing_by_title: Dict[str, Fuente] = {}
    for f in session.query(Fuente).all():
        if f.issn:
            existing_by_issn[f.issn] = f
        key = _normalize_source_key(f.source_title)
        if key:
            existing_by_title[key] = f

    for _, row in df_fuentes.iterrows():
        source_title = _safe_str(row.get("source_title"))
        if not source_title:
            continue

        issn = _safe_str(row.get("issn"))
        abbrev = _safe_str(row.get("abbreviated_source_title"))
        tipo = _safe_str(row.get("tipo_fuente"))
        publisher = _safe_str(row.get("publisher"))
        src_key = _normalize_source_key(source_title)

        # Buscar existente: ISSN primero, luego título
        existing = None
        if issn:
            existing = existing_by_issn.get(issn)
        if existing is None:
            existing = existing_by_title.get(src_key)

        if existing:
            if abbrev:
                existing.abbreviated_source_title = abbrev
            if tipo:
                existing.tipo_fuente = tipo
            if publisher:
                existing.publisher = publisher
            if issn and not existing.issn:
                existing.issn = issn
            fuente_map[src_key] = existing.id_fuente
            updated += 1
        else:
            new_fuente = Fuente(
                source_title=source_title,
                abbreviated_source_title=abbrev,
                issn=issn,
                tipo_fuente=tipo,
                publisher=publisher,
            )
            session.add(new_fuente)
            session.flush()
            fuente_map[src_key] = new_fuente.id_fuente
            if issn:
                existing_by_issn[issn] = new_fuente
            existing_by_title[src_key] = new_fuente
            inserted += 1

    session.flush()

    logger.info(
        "Fuentes: %d insertadas, %d actualizadas",
        inserted, updated,
    )
    return fuente_map


def load_fuente_metricas(
    session: Session,
    df_fuentes_enriched: pd.DataFrame,
    fuente_map: Dict[str, int],
    anio: int,
) -> None:
    """Carga métricas de fuentes en fuente_metrica (upsert por id_fuente + año)."""
    if df_fuentes_enriched.empty:
        logger.warning("DataFrame de fuentes enriquecidas vacio")
        return

    inserted = 0
    updated = 0
    sin_metricas = 0

    existing_metrics: Dict[tuple, FuenteMetrica] = {
        (m.id_fuente, m.anio): m
        for m in session.query(FuenteMetrica).filter_by(anio=anio).all()
    }

    for _, row in df_fuentes_enriched.iterrows():
        source_title = row.get("source_title")
        if pd.isna(source_title):
            continue

        src_key = _normalize_source_key(source_title)
        id_fuente = fuente_map.get(src_key)
        if id_fuente is None:
            continue

        sjr = row.get("sjr")
        citescore = row.get("citescore")
        snip = row.get("snip")
        cuartil = row.get("cuartil_sjr")
        percentil = row.get("percentil_citescore")

        has_any = pd.notna(sjr) or pd.notna(citescore) or pd.notna(snip)
        if not has_any:
            sin_metricas += 1
            continue

        existing = existing_metrics.get((id_fuente, anio))
        if existing:
            if pd.notna(sjr):
                existing.sjr = float(sjr)
            if pd.notna(citescore):
                existing.citescore = float(citescore)
            if pd.notna(snip):
                existing.snip = float(snip)
            if pd.notna(cuartil):
                existing.cuartil_sjr = str(cuartil)
            if pd.notna(percentil):
                existing.percentil_sjr = float(percentil)
            existing.fuente_datos = "scimago_scopus"
            updated += 1
        else:
            new_metric = FuenteMetrica(
                id_fuente=id_fuente,
                anio=anio,
                sjr=float(sjr) if pd.notna(sjr) else None,
                citescore=float(citescore) if pd.notna(citescore) else None,
                snip=float(snip) if pd.notna(snip) else None,
                cuartil_sjr=str(cuartil) if pd.notna(cuartil) else None,
                percentil_sjr=float(percentil) if pd.notna(percentil) else None,
                fuente_datos="scimago_scopus",
            )
            session.add(new_metric)
            # Registrar en el indice en memoria para que filas posteriores
            # con la misma id_fuente (p.ej. fuentes deduplicadas que comparten
            # ISSN) actualicen esta metrica en vez de insertar un duplicado
            # que violaria uq_fuente_metrica_anio.
            existing_metrics[(id_fuente, anio)] = new_metric
            inserted += 1

    session.flush()

    logger.info(
        "Metricas fuentes: %d insertadas, %d actualizadas, %d fuentes sin metricas",
        inserted, updated, sin_metricas,
    )


def load_publicaciones(
    session: Session,
    df_publications: pd.DataFrame,
    fuente_map: Dict[str, int],
    pub_fuente_map: Dict[str, str],
) -> Dict[str, int]:
    """Carga publicaciones en la tabla publicacion (upsert por EID)."""
    if df_publications.empty:
        logger.warning("DataFrame de publicaciones vacio")
        return {}

    pub_map: Dict[str, int] = {}
    inserted = 0
    updated = 0
    errors = 0
    total = len(df_publications)

    existing_eids: Dict[str, int] = dict(
        session.query(Publicacion.eid, Publicacion.id_publicacion).all()
    )

    new_pubs: list = []

    for idx, (_, row) in enumerate(df_publications.iterrows()):
        eid = _safe_str(row.get("eid"))
        if not eid:
            errors += 1
            continue

        source_title = pub_fuente_map.get(eid)
        id_fuente = None
        if source_title:
            src_key = _normalize_source_key(source_title)
            id_fuente = fuente_map.get(src_key)

        if eid in existing_eids:
            update_vals: Dict[str, object] = {}
            cited = row.get("cited_by_count")
            if pd.notna(cited):
                update_vals["cited_by_count"] = _safe_int(cited)
            if id_fuente is not None:
                update_vals["id_fuente"] = id_fuente

            if update_vals:
                session.query(Publicacion).filter_by(eid=eid).update(update_vals)

            pub_map[eid] = existing_eids[eid]
            updated += 1
        else:
            new_pub = Publicacion(
                eid=eid,
                doi=_safe_str(row.get("doi")),
                titulo=_safe_str(row.get("titulo")) or "",
                anio_publicacion=_safe_int(row.get("anio_publicacion")),
                tipo_documental=_safe_str_max(row.get("tipo_documental"), 50),
                idioma=_safe_str_max(row.get("idioma"), 50),
                cited_by_count=_safe_int(row.get("cited_by_count")),
                open_access=_safe_str_max(row.get("open_access"), 50),
                publication_stage=_safe_str_max(row.get("publication_stage"), 50),
                volumen=_safe_str_max(row.get("volumen"), 50),
                issue=_safe_str_max(row.get("issue"), 50),
                paginas=_safe_str_max(row.get("paginas"), 50),
                publisher=_safe_str(row.get("publisher")),
                correspondence_address=_safe_str(row.get("correspondence_address")),
                affiliations=_safe_str(row.get("affiliations")),
                indexed_keywords=_safe_str(row.get("indexed_keywords")),
                referencias_raw=_safe_str(row.get("referencias_raw")),
                pubmed_id=_safe_str_max(row.get("pubmed_id"), 50),
                id_fuente=id_fuente,
            )
            session.add(new_pub)
            new_pubs.append((eid, new_pub))
            inserted += 1

        if (idx + 1) % 500 == 0:
            session.flush()
            for e, p in new_pubs:
                pub_map[e] = p.id_publicacion
            new_pubs.clear()
            logger.info("Progreso publicaciones: %d/%d", idx + 1, total)

    session.flush()
    for e, p in new_pubs:
        pub_map[e] = p.id_publicacion
    new_pubs.clear()

    logger.info(
        "Publicaciones: %d insertadas, %d actualizadas, %d errores",
        inserted, updated, errors,
    )
    return pub_map


def load_publication_professor_links(
    session: Session,
    df_links: pd.DataFrame,
    pub_map: Dict[str, int],
    prof_map: Dict[str, int],
) -> None:
    """Carga vínculos publicación-profesor en publicacion_profesor."""
    if df_links.empty:
        logger.info("Sin vinculos que cargar")
        return

    inserted = 0
    skipped = 0

    existing_links: set = set()
    stmt = select(
        publicacion_profesor_table.c.id_publicacion,
        publicacion_profesor_table.c.id_profesor,
    )
    for r in session.execute(stmt).all():
        existing_links.add((r[0], r[1]))

    for _, row in df_links.iterrows():
        eid = _safe_str(row.get("eid"))
        orcid = _safe_str(row.get("orcid"))
        metodo = _safe_str(row.get("metodo_vinculacion")) or "desconocido"

        if not eid or not orcid:
            skipped += 1
            continue

        id_pub = pub_map.get(eid)
        id_prof = prof_map.get(orcid)

        if id_pub is None:
            logger.warning(
                "EID '%s' no encontrado en pub_map -- vinculo omitido",
                eid,
            )
            skipped += 1
            continue

        if id_prof is None:
            logger.warning(
                "ORCID '%s' no encontrado en prof_map -- vinculo omitido",
                orcid,
            )
            skipped += 1
            continue

        if (id_pub, id_prof) in existing_links:
            skipped += 1
            continue

        session.execute(
            publicacion_profesor_table.insert().values(
                id_publicacion=id_pub,
                id_profesor=id_prof,
                metodo_vinculacion=metodo,
                es_autor_correspondencia=False,
            )
        )
        existing_links.add((id_pub, id_prof))
        inserted += 1

    session.flush()

    logger.info(
        "Vinculos publicacion-profesor: %d insertados, %d omitidos",
        inserted, skipped,
    )


def update_h_index_profesores(session: Session) -> int:
    """Recalcula y actualiza el h-index de todos los profesores con publicaciones vinculadas.

    Usa las tablas:
    - profesor
    - publicacion_profesor
    - publicacion

    Returns
    -------
    int
        Número de profesores actualizados.
    """
    rows = session.execute(
        select(
            Profesor.id_profesor,
            Publicacion.cited_by_count,
        )
        .select_from(Profesor)
        .join(
            publicacion_profesor_table,
            Profesor.id_profesor == publicacion_profesor_table.c.id_profesor,
        )
        .join(
            Publicacion,
            Publicacion.id_publicacion == publicacion_profesor_table.c.id_publicacion,
        )
    ).all()

    if not rows:
        logger.warning("No hay publicaciones vinculadas para calcular h-index")
        return 0

    citas_por_profesor: Dict[int, list] = {}
    for id_profesor, cited_by_count in rows:
        citas_por_profesor.setdefault(id_profesor, []).append(cited_by_count)

    updated = 0
    fecha_actual = datetime.now().date()

    profesores = {
        p.id_profesor: p
        for p in session.query(Profesor).all()
    }

    for id_profesor, citas in citas_por_profesor.items():
        profesor = profesores.get(id_profesor)
        if profesor is None:
            continue

        h_value = calcular_h_index_desde_citas(citas)

        profesor.h_index = h_value
        profesor.h_index_fecha = fecha_actual
        profesor.fecha_actualizacion = datetime.now()
        updated += 1

    session.flush()

    logger.info("h-index actualizado para %d profesores", updated)
    return updated

def log_ingesta(
    session: Session,
    fase: str,
    stats: Dict[str, object],
    archivo_origen: Optional[str] = None,
    notas: Optional[str] = None,
) -> None:
    """Registra un log de ingesta en la tabla log_ingesta."""
    log_entry = LogIngesta(
        fase=fase,
        archivo_origen=archivo_origen,
        registros_crudos=stats.get("registros_crudos"),
        registros_limpios=stats.get("registros_limpios"),
        registros_nuevos=stats.get("registros_nuevos"),
        registros_duplicados=stats.get("registros_duplicados"),
        registros_error=stats.get("registros_error"),
        duracion_segundos=stats.get("duracion_segundos"),
        notas=notas,
    )
    session.add(log_entry)
    session.flush()
    logger.info("Log de ingesta registrado: fase='%s'", fase)


def run_full_load(
    df_profesores: pd.DataFrame,
    df_autores_scopus: pd.DataFrame,
    df_publications: pd.DataFrame,
    df_fuentes: pd.DataFrame,
    df_fuentes_enriched: pd.DataFrame,
    publication_fuente_map: Dict[str, str],
    df_links: pd.DataFrame,
    anio_metricas: Optional[int] = None,
) -> Dict[str, object]:
    """Ejecuta la carga completa a PostgreSQL en una transacción."""
    if anio_metricas is None:
        anio_metricas = datetime.now().year

    start_time = datetime.now()
    logger.info(
        "=== Carga completa a BD iniciada (anio_metricas=%d) ===",
        anio_metricas,
    )

    stats: Dict[str, object] = {}

    try:
        with get_session() as session:
            # 1. Departamentos
            dept_map = load_departamentos(session)
            stats["departamentos"] = len(dept_map)

            # 2. Profesores
            prof_map = load_profesores(session, df_profesores, dept_map)
            stats["profesores"] = len(prof_map)

            # 3. Autores Scopus
            load_autores_scopus(session, df_autores_scopus, prof_map)
            stats["autores_scopus"] = len(df_autores_scopus)

            # 4. Fuentes
            fuente_map = load_fuentes(session, df_fuentes)
            stats["fuentes"] = len(fuente_map)

            # 5. Métricas de fuentes
            load_fuente_metricas(
                session,
                df_fuentes_enriched,
                fuente_map,
                anio_metricas,
            )

            # 6. Publicaciones
            pub_map = load_publicaciones(
                session,
                df_publications,
                fuente_map,
                publication_fuente_map,
            )
            stats["publicaciones"] = len(pub_map)

            # 7. Vínculos publicación-profesor
            load_publication_professor_links(
                session,
                df_links,
                pub_map,
                prof_map,
            )
            stats["links"] = len(df_links)

            # 8. Recalcular h-index de profesores
            stats["h_index_actualizados"] = update_h_index_profesores(session)

            # 9. Duración
            duration = (datetime.now() - start_time).total_seconds()
            stats["duracion_segundos"] = round(duration, 2)

            # 10. Log de ingesta
            log_ingesta(
                session,
                fase="carga_completa",
                stats={
                    "registros_crudos": len(df_publications),
                    "registros_nuevos": stats.get("publicaciones", 0),
                    "duracion_segundos": duration,
                },
                notas=(
                    f"Profesores: {stats.get('profesores', 0)}, "
                    f"Fuentes: {stats.get('fuentes', 0)}, "
                    f"Publicaciones: {stats.get('publicaciones', 0)}, "
                    f"Links: {stats.get('links', 0)}, "
                    f"h-index actualizados: {stats.get('h_index_actualizados', 0)}"
                ),
            )

    except Exception as exc:
        logger.error("Error en carga completa a BD: %s", exc)
        raise

    logger.info(
        "=== Carga completa finalizada en %.1fs: %d profesores, %d fuentes, %d publicaciones, %d links, %d h-index actualizados ===",
        stats.get("duracion_segundos", 0),
        stats.get("profesores", 0),
        stats.get("fuentes", 0),
        stats.get("publicaciones", 0),
        stats.get("links", 0),
        stats.get("h_index_actualizados", 0),
    )
    return stats