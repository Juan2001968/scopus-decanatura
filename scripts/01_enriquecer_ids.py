"""
PASO 1: Enriquecimiento de Author IDs y detección de perfiles fragmentados.

Qué hace este script
--------------------
1. Lee los CSV originales de profesores (sin modificarlos).
2. Para cada profesor, busca o valida su(s) Scopus Author ID(s):
   a) Si ya tiene Auth_ID → lo valida contra la API y detecta alias
      (indicios de perfil fragmentado) revisando name-variant/@auid.
   b) Si no tiene Auth_ID pero sí ORCID → busca en Scopus por ORCID.
   c) Si no tiene ninguno → busca por apellido + nombre + afiliación.
3. Genera dos archivos en data/processed/:
   - candidatos_revision_humana.csv  (todos los casos, especialmente los ambiguos)
   - profesores_validados.csv        (IDs confirmados y pendientes de revisión)
4. DETIENE el proceso y pide revisión humana antes de ejecutar el paso 2.

Instrucciones para el revisor humano
-------------------------------------
- Abre candidatos_revision_humana.csv y revisa las filas con estado
  AMBIGUO_NOMBRE, AMBIGUO_ORCID, CANDIDATO_UNICO_NOMBRE o ALIAS_DETECTADO.
- Para cada profesor en profesores_validados.csv con scopus_ids vacío,
  elige el/los ID(s) correctos consultando candidatos_revision_humana.csv
  y escríbelos en la columna scopus_ids (separados por ; si son varios).
- Marca revisado_humano = True en las filas que hayas corregido.
- Guarda el archivo y ejecuta: python -m scripts.02_extraer_validar_exportar

Salidas
-------
data/processed/candidatos_revision_humana.csv
data/processed/profesores_validados.csv  ← editar antes de paso 2
logs/errores_api.log

Uso
---
    python -m scripts.01_enriquecer_ids
"""

from __future__ import annotations

import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Permitir ejecución directa o como módulo desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA_PROCESSED_DIR, DATA_RAW_DIR, LOGS_DIR
from src.api_scopus.author_retrieval import (
    parse_author_search,
    retrieve_author_by_id,
    retrieve_author_by_orcid,
)
from src.api_scopus.client import ScopusClient
from src.etl.ingest_professors import load_all_professors
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SLEEP_ENTRE_LLAMADAS: float = 0.5
"""Pausa entre llamadas a la API para respetar los rate limits."""

_AFILIACION_BUSQUEDA: str = "Universidad del Norte"
"""Institución que se usa como filtro en la búsqueda por nombre."""

# Estados posibles de cada candidato
_VALIDADO = "ID_VALIDADO"
_INVALIDO = "ID_INVALIDO"
_CAND_ORCID = "CANDIDATO_UNICO_ORCID"
_AMBIGUO_ORCID = "AMBIGUO_ORCID"
_CAND_NOMBRE = "CANDIDATO_UNICO_NOMBRE"
_AMBIGUO_NOMBRE = "AMBIGUO_NOMBRE"
_ALIAS = "ALIAS_DETECTADO"
_SIN_RESULTADO = "SIN_RESULTADO"
_ERROR_API = "ERROR_API"

# ---------------------------------------------------------------------------
# Logger de errores de API
# ---------------------------------------------------------------------------

_api_err_logger = logging.getLogger("errores_api")


def _configurar_log_errores() -> Path:
    """Configura el logger dedicado para errores de API."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ruta = LOGS_DIR / "errores_api.log"
    if not _api_err_logger.handlers:
        handler = logging.FileHandler(ruta, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        _api_err_logger.setLevel(logging.ERROR)
        _api_err_logger.addHandler(handler)
    return ruta


def _log_error_api(contexto: str, autor: str, exc: Exception) -> None:
    """Escribe un error de API en errores_api.log."""
    _api_err_logger.error(
        "contexto=%s | autor=%s | tipo=%s | detalle=%s",
        contexto,
        autor,
        type(exc).__name__,
        str(exc),
    )


# ---------------------------------------------------------------------------
# Funciones de consulta a la API
# ---------------------------------------------------------------------------


def _validar_id_existente(
    auth_id: str,
    nombre_profesor: str,
    client: ScopusClient,
) -> Tuple[str, Optional[dict]]:
    """Valida un Auth_ID existente consultando Author Retrieval.

    Returns
    -------
    tuple[str, dict | None]
        (estado, perfil_parseado) — perfil es None si falla o no existe.
    """
    try:
        time.sleep(_SLEEP_ENTRE_LLAMADAS)
        perfil = retrieve_author_by_id(auth_id, client)
        if perfil:
            return _VALIDADO, perfil
        return _INVALIDO, None
    except (PermissionError, ConnectionError) as exc:
        _log_error_api("validar_id", nombre_profesor, exc)
        return _ERROR_API, None


def _buscar_por_orcid(
    orcid: str,
    nombre_profesor: str,
    client: ScopusClient,
) -> Tuple[str, List[dict]]:
    """Busca Author IDs en Scopus por ORCID.

    Returns
    -------
    tuple[str, list[dict]]
        (estado, lista_de_candidatos).
    """
    try:
        time.sleep(_SLEEP_ENTRE_LLAMADAS)
        resultados = retrieve_author_by_orcid(orcid, client)
        if not resultados:
            return _SIN_RESULTADO, []
        return (_CAND_ORCID if len(resultados) == 1 else _AMBIGUO_ORCID), resultados
    except (PermissionError, ConnectionError) as exc:
        _log_error_api("buscar_orcid", nombre_profesor, exc)
        return _ERROR_API, []


def _buscar_por_nombre(
    apellido: str,
    nombre: str,
    nombre_completo: str,
    client: ScopusClient,
) -> Tuple[str, List[dict]]:
    """Busca Author IDs por apellido + nombre + afiliación.

    Intenta primero apellido+nombre+afiliación; si no hay resultados,
    reintenta solo con apellido+afiliación.

    Returns
    -------
    tuple[str, list[dict]]
        (estado, lista_de_candidatos).
    """
    intentos = [
        (apellido, nombre, _AFILIACION_BUSQUEDA),
        (apellido, "", _AFILIACION_BUSQUEDA),
    ]

    for ap, nom, afil in intentos:
        try:
            time.sleep(_SLEEP_ENTRE_LLAMADAS)
            raw = client.author_search_by_name(ap, nom, afil)
        except (PermissionError, ConnectionError) as exc:
            _log_error_api("buscar_nombre", nombre_completo, exc)
            return _ERROR_API, []

        if raw is None:
            continue

        resultados = parse_author_search(raw)
        if not resultados:
            continue

        estado = _CAND_NOMBRE if len(resultados) == 1 else _AMBIGUO_NOMBRE
        return estado, resultados

    return _SIN_RESULTADO, []


# ---------------------------------------------------------------------------
# Procesamiento principal
# ---------------------------------------------------------------------------


def _construir_fila_candidato(
    nombre_completo: str,
    depto: str,
    orcid: str,
    auth_id_conocido: str,
    candidato: dict,
    metodo: str,
    estado: str,
    es_alias: bool,
    notas: str,
) -> dict:
    """Construye un dict con la estructura de candidatos_revision_humana.csv."""
    return {
        "profesor_nombre": nombre_completo,
        "departamento": depto,
        "orcid_conocido": orcid,
        "auth_id_conocido": auth_id_conocido,
        "candidato_scopus_id": candidato.get("scopus_author_id", ""),
        "candidato_nombre_scopus": candidato.get("nombre", candidato.get("nombre_preferido", "")),
        "candidato_doc_count": candidato.get("document_count", 0),
        "metodo_busqueda": metodo,
        "estado": estado,
        "es_alias": es_alias,
        "notas": notas,
    }


def procesar_profesores(
    df_raw: pd.DataFrame,
    client: ScopusClient,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Procesa todos los profesores y genera los DataFrames de salida.

    Para cada profesor (deduplicado por ORCID o nombre+apellido):
    - Valida el Auth_ID existente y detecta alias.
    - Busca por ORCID si no tiene Auth_ID.
    - Busca por nombre+afiliación si tampoco tiene ORCID o no hubo resultados.

    Parameters
    ----------
    df_raw:
        DataFrame concatenado de los CSV de profesores.
    client:
        Instancia de ScopusClient.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (df_candidatos, df_resumen_profesores)
    """
    filas_candidatos: List[dict] = []
    filas_resumen: List[dict] = []
    vistos: set = set()

    total_filas = len(df_raw)
    for idx, (_, row) in enumerate(df_raw.iterrows()):
        orcid = str(row.get("Orc_ID", "")).strip()
        auth_id = (
            str(row["Auth_ID"]).strip()
            if pd.notna(row.get("Auth_ID")) and str(row.get("Auth_ID", "")).strip()
            else ""
        )
        apellido = str(row.get("AuthorName", "")).strip()
        nombre = str(row.get("AuthorName_1", "")).strip()
        depto = str(row.get("departamento_codigo", "")).strip()
        nombre_completo = f"{apellido}, {nombre}"

        # Deduplicar: un profesor puede aparecer varias veces (una por Auth_ID)
        clave = orcid if orcid else nombre_completo
        if clave in vistos:
            continue
        vistos.add(clave)

        if (idx + 1) % 10 == 0:
            logger.info(
                "Progreso enriquecimiento: %d/%d filas procesadas",
                idx + 1, total_filas,
            )

        ids_confirmados: List[str] = []
        ids_candidatos: List[str] = []
        alias_detectados: List[str] = []
        tiene_fragmentacion = False
        notas_resumen: List[str] = []

        # ----------------------------------------------------------------
        # Caso A: tiene Auth_ID → validar y buscar alias
        # ----------------------------------------------------------------
        if auth_id:
            estado_val, perfil = _validar_id_existente(
                auth_id, nombre_completo, client,
            )

            if estado_val == _VALIDADO and perfil:
                ids_confirmados.append(auth_id)
                doc_count = perfil.get("document_count", 0)

                # Detectar alias (perfiles fragmentados)
                for alias_id in perfil.get("alias_ids", []):
                    alias_detectados.append(alias_id)
                    tiene_fragmentacion = True
                    filas_candidatos.append(
                        _construir_fila_candidato(
                            nombre_completo, depto, orcid, auth_id,
                            {"scopus_author_id": alias_id,
                             "nombre": perfil.get("nombre_preferido", ""),
                             "document_count": 0},
                            "alias_name_variant",
                            _ALIAS,
                            True,
                            f"Alias encontrado en name-variant del ID {auth_id}. "
                            f"Confirmar si corresponde al mismo profesor.",
                        )
                    )

                filas_candidatos.append(
                    _construir_fila_candidato(
                        nombre_completo, depto, orcid, auth_id,
                        {"scopus_author_id": auth_id,
                         "nombre": perfil.get("nombre_preferido", ""),
                         "document_count": doc_count},
                        "validacion_directa",
                        _VALIDADO,
                        False,
                        f"ID validado. Docs en perfil: {doc_count}.",
                    )
                )

            elif estado_val == _INVALIDO:
                notas_resumen.append(f"Auth_ID {auth_id} no encontrado en API (404)")
                filas_candidatos.append(
                    _construir_fila_candidato(
                        nombre_completo, depto, orcid, auth_id,
                        {"scopus_author_id": auth_id, "nombre": "", "document_count": 0},
                        "validacion_directa",
                        _INVALIDO,
                        False,
                        "El ID no existe en Scopus. Verificar y corregir.",
                    )
                )
            else:
                notas_resumen.append(f"Error de API al validar Auth_ID {auth_id}")

        # ----------------------------------------------------------------
        # Caso B: sin Auth_ID, buscar por ORCID
        # ----------------------------------------------------------------
        if not ids_confirmados and orcid:
            estado_orc, resultados = _buscar_por_orcid(orcid, nombre_completo, client)

            for r in resultados:
                sid = r.get("scopus_author_id", "")
                if not sid:
                    continue
                ids_candidatos.append(sid)
                filas_candidatos.append(
                    _construir_fila_candidato(
                        nombre_completo, depto, orcid, auth_id,
                        r, "orcid_search", estado_orc, False,
                        f"Encontrado por ORCID. Total resultados: {len(resultados)}.",
                    )
                )

            if estado_orc == _SIN_RESULTADO:
                notas_resumen.append(f"Sin resultado por ORCID {orcid}")

        # ----------------------------------------------------------------
        # Caso C: sin Auth_ID ni resultados por ORCID → buscar por nombre
        # ----------------------------------------------------------------
        if not ids_confirmados and not ids_candidatos:
            estado_nom, resultados = _buscar_por_nombre(
                apellido, nombre, nombre_completo, client,
            )

            for r in resultados:
                sid = r.get("scopus_author_id", "")
                if not sid:
                    continue
                ids_candidatos.append(sid)
                filas_candidatos.append(
                    _construir_fila_candidato(
                        nombre_completo, depto, orcid, auth_id,
                        r, "nombre_afiliacion", estado_nom, False,
                        f"Encontrado por nombre+afiliación. "
                        f"Total resultados: {len(resultados)}. "
                        f"REQUIERE verificación manual.",
                    )
                )

            if estado_nom == _SIN_RESULTADO:
                notas_resumen.append("Sin resultado por nombre+afiliación")

        # ----------------------------------------------------------------
        # Fila de resumen (profesores_validados.csv)
        # ----------------------------------------------------------------
        todos_posibles = list(set(ids_confirmados + ids_candidatos + alias_detectados))

        if ids_confirmados:
            estado_gral = "FRAGMENTADO" if tiene_fragmentacion else "COMPLETO"
            # Incluir alias en los IDs confirmados para que script 02 los use
            scopus_ids_para_validado = ";".join(
                list(set(ids_confirmados + alias_detectados))
            )
        elif ids_candidatos:
            estado_gral = "REQUIERE_REVISION"
            scopus_ids_para_validado = ""  # el humano debe elegir
        else:
            estado_gral = "SIN_ID"
            scopus_ids_para_validado = ""

        filas_resumen.append({
            "orcid": orcid,
            "nombre": nombre_completo,
            "departamento": depto,
            # Pre-llenado para COMPLETO/FRAGMENTADO; vacío para REQUIERE_REVISION/SIN_ID
            "scopus_ids": scopus_ids_para_validado,
            "revisado_humano": bool(ids_confirmados),
            "estado": estado_gral,
            "tiene_fragmentacion": tiene_fragmentacion,
            "alias_detectados": ";".join(alias_detectados),
            "ids_candidatos_disponibles": ";".join(ids_candidatos),
            "total_ids_posibles": len(todos_posibles),
            "notas": " | ".join(notas_resumen),
            "fecha_procesado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    # -- Construir DataFrames --
    cols_cand = [
        "profesor_nombre", "departamento", "orcid_conocido", "auth_id_conocido",
        "candidato_scopus_id", "candidato_nombre_scopus", "candidato_doc_count",
        "metodo_busqueda", "estado", "es_alias", "notas",
    ]
    df_candidatos = (
        pd.DataFrame(filas_candidatos, columns=cols_cand)
        if filas_candidatos
        else pd.DataFrame(columns=cols_cand)
    )

    cols_res = [
        "orcid", "nombre", "departamento", "scopus_ids", "revisado_humano",
        "estado", "tiene_fragmentacion", "alias_detectados",
        "ids_candidatos_disponibles", "total_ids_posibles", "notas",
        "fecha_procesado",
    ]
    df_resumen = (
        pd.DataFrame(filas_resumen, columns=cols_res)
        if filas_resumen
        else pd.DataFrame(columns=cols_res)
    )

    return df_candidatos, df_resumen


# ---------------------------------------------------------------------------
# Guardado de archivos de salida
# ---------------------------------------------------------------------------


def _guardar_salidas(
    df_candidatos: pd.DataFrame,
    df_resumen: pd.DataFrame,
) -> Tuple[Path, Path]:
    """Guarda los CSVs de salida en data/processed/."""
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    ruta_cand = DATA_PROCESSED_DIR / "candidatos_revision_humana.csv"
    ruta_res = DATA_PROCESSED_DIR / "profesores_validados.csv"

    df_candidatos.to_csv(ruta_cand, index=False, encoding="utf-8-sig")
    df_resumen.to_csv(ruta_res, index=False, encoding="utf-8-sig")

    logger.info("Candidatos guardados en: %s (%d filas)", ruta_cand, len(df_candidatos))
    logger.info("Resumen guardado en: %s (%d filas)", ruta_res, len(df_resumen))

    return ruta_cand, ruta_res


# ---------------------------------------------------------------------------
# Resumen final
# ---------------------------------------------------------------------------


def _imprimir_resumen(df_resumen: pd.DataFrame, df_raw: pd.DataFrame) -> None:
    """Imprime el resumen de resultados en consola."""
    total = len(df_resumen)
    con_id = (df_resumen["estado"] == "COMPLETO").sum()
    fragmentados = (df_resumen["estado"] == "FRAGMENTADO").sum()
    requieren_revision = (df_resumen["estado"] == "REQUIERE_REVISION").sum()
    sin_id = (df_resumen["estado"] == "SIN_ID").sum()

    # Contar cuántos se encontraron automáticamente (antes no tenían Auth_ID)
    profs_sin_auth_original = df_raw[
        df_raw["Auth_ID"].isna() | (df_raw["Auth_ID"].astype(str).str.strip() == "")
    ]["Orc_ID"].nunique()

    encontrados_auto = len(df_resumen[
        (df_resumen["scopus_ids"] != "")
        & (df_resumen["estado"].isin(["COMPLETO", "FRAGMENTADO"]))
    ])

    print("\n" + "=" * 60)
    print("RESUMEN - Paso 1: Enriquecimiento de Author IDs")
    print("=" * 60)
    print(f"  Total profesores únicos procesados : {total}")
    print(f"  Con ID validado (estado COMPLETO)  : {con_id}")
    print(f"  Con perfil fragmentado detectado   : {fragmentados}")
    print(f"  Requieren revisión humana          : {requieren_revision}")
    print(f"  Sin ningún ID encontrado           : {sin_id}")
    print(f"  Profesores sin Auth_ID en CSV orig.: {profs_sin_auth_original}")
    print(f"  Encontrados automáticamente        : {encontrados_auto}")
    print("=" * 60)

    if requieren_revision > 0 or sin_id > 0:
        print("\n⚠️  ACCIÓN REQUERIDA:")
        print("   1. Revisa data/processed/candidatos_revision_humana.csv")
        print("   2. Para cada profesor con scopus_ids vacío en")
        print("      data/processed/profesores_validados.csv,")
        print("      añade el/los ID(s) correctos (separados por ;).")
        print("   3. Marca revisado_humano = True en esas filas.")
        print("   4. Ejecuta: python -m scripts.02_extraer_validar_exportar")
    else:
        print("\n✓ Todos los profesores tienen IDs confirmados.")
        print("  Puedes ejecutar: python -m scripts.02_extraer_validar_exportar")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------


def main() -> None:
    """Orquesta el flujo completo del paso 1."""
    ruta_log = _configurar_log_errores()
    logger.info("=== Paso 1: Enriquecimiento de Author IDs iniciado ===")
    logger.info("Errores de API se guardarán en: %s", ruta_log)

    # -- Inicializar cliente --
    try:
        client = ScopusClient()
    except ValueError as exc:
        print(
            f"\nError: {exc}\n"
            "Configura SCOPUS_API_KEY en el archivo .env antes de ejecutar.",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- Cargar CSV de profesores (sin modificarlos) --
    logger.info("Cargando CSV de profesores desde %s", DATA_RAW_DIR)
    df_raw = load_all_professors(DATA_RAW_DIR)

    if df_raw.empty:
        print("Error: no se encontraron archivos CSV de profesores en data/raw/",
              file=sys.stderr)
        sys.exit(1)

    logger.info("CSV cargados: %d filas totales", len(df_raw))

    # -- Procesar profesores --
    df_candidatos, df_resumen = procesar_profesores(df_raw, client)

    # -- Guardar salidas --
    ruta_cand, ruta_res = _guardar_salidas(df_candidatos, df_resumen)

    # -- Resumen final --
    _imprimir_resumen(df_resumen, df_raw)

    logger.info("=== Paso 1 finalizado ===")
    print(f"\n  Archivos generados:")
    print(f"    {ruta_cand}")
    print(f"    {ruta_res}")
    print(f"    {ruta_log}")


if __name__ == "__main__":
    main()
