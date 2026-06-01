"""
PASO 3: Diagnóstico comparativo de matching para profesores con mayor discrepancia.

Usa pybliometrics (AuthorRetrieval + ScopusSearch) como fuente independiente
para verificar los EIDs que asignó el Paso 2 (v2) a cada profesor.

Flujo
-----
1. Lee calidad_matching_v2.csv y selecciona los TOP_N profesores con mayor
   diferencia (docs_perfil_scopus vs docs_api_total).
2. Para cada uno:
   a. AuthorRetrieval  → document_count oficial del perfil en Scopus.
   b. ScopusSearch(AU-ID()) + filtro año → lista completa de EIDs según Scopus.
   c. Carga los EIDs extraídos en publicaciones_v2.csv para ese profesor.
   d. Calcula:
      - eids_extra    : EIDs en nuestra salida que Scopus NO asigna al prof → sobre-asignación.
      - eids_faltantes: EIDs que Scopus asigna al prof pero que faltan en nuestra salida.
3. Genera data/processed/diagnostico_errores.csv.

Uso
---
    python -m scripts.03_diagnostico_matching
    python -m scripts.03_diagnostico_matching --top 10        # más profesores
    python -m scripts.03_diagnostico_matching --sin-año       # sin filtro de año
"""

from __future__ import annotations

import argparse
import configparser
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    DATA_PROCESSED_DIR,
    LOGS_DIR,
    ROLLING_WINDOW_YEARS,
    SCOPUS_API_KEY,
    SCOPUS_INST_TOKEN,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SLEEP: float = 1.0
_TOP_N_DEFAULT: int = 5

_AÑO_FIN: int = __import__("datetime").datetime.now().year - 1
_AÑO_INICIO: int = _AÑO_FIN - ROLLING_WINDOW_YEARS + 1

_RUTA_CALIDAD = DATA_PROCESSED_DIR / "calidad_matching_v2.csv"
_RUTA_PUBS_V2 = DATA_PROCESSED_DIR / "publicaciones_v2.csv"
_RUTA_SALIDA = DATA_PROCESSED_DIR / "diagnostico_errores.csv"


# ---------------------------------------------------------------------------
# Configuración de pybliometrics
# ---------------------------------------------------------------------------


def _configurar_pybliometrics() -> None:
    """Crea ~/.scopus/config.ini con la clave de la API si no existe."""
    if not SCOPUS_API_KEY:
        raise ValueError(
            "SCOPUS_API_KEY no está definida en .env. "
            "pybliometrics no puede autenticarse sin ella."
        )

    config_dir = Path.home() / ".scopus"
    config_path = config_dir / "config.ini"

    if config_path.exists():
        # Si ya existe pero no tiene nuestra clave, sobreescribir solo la sección
        cfg = configparser.ConfigParser()
        cfg.read(config_path, encoding="utf-8")
        existing_key = cfg.get("Authentication", "APIKey", fallback="")
        if existing_key == SCOPUS_API_KEY:
            logger.info("pybliometrics ya configurado: %s", config_path)
            return
        logger.info("Actualizando pybliometrics config con la clave del .env")
    else:
        config_dir.mkdir(parents=True, exist_ok=True)
        cfg = configparser.ConfigParser()
        logger.info("Creando pybliometrics config: %s", config_path)

    cfg["Authentication"] = {"APIKey": SCOPUS_API_KEY}
    if SCOPUS_INST_TOKEN:
        cfg["Authentication"]["InstToken"] = SCOPUS_INST_TOKEN

    with open(config_path, "w", encoding="utf-8") as f:
        cfg.write(f)

    logger.info("pybliometrics configurado correctamente.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _author_ids_de_fila(fila: pd.Series) -> List[str]:
    """Parsea author_ids separados por ';' en una fila del CSV de calidad."""
    raw = str(fila.get("author_ids", "")).strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(";") if s.strip()]


def _eids_pybliometrics(
    author_ids: List[str],
    año_inicio: Optional[int],
    año_fin: Optional[int],
) -> Tuple[Set[str], int]:
    """Obtiene EIDs y document_count oficial usando pybliometrics.

    Returns
    -------
    tuple[set[str], int]
        (eids_scopus, docs_perfil_oficial)
        docs_perfil_oficial: suma de document_count de todos los Author IDs
        del profesor (incluye duplicados si hay alias; es la suma máxima posible).
    """
    from pybliometrics.scopus import AuthorRetrieval, ScopusSearch  # type: ignore

    eids_todos: Set[str] = set()
    docs_perfil_total: int = 0

    # Construir query con filtro de año opcional
    ids_parte = " OR ".join(f"AU-ID({aid})" for aid in author_ids)
    if len(author_ids) > 1:
        ids_parte = f"({ids_parte})"

    if año_inicio and año_fin:
        query_ss = (
            f"{ids_parte} AND PUBYEAR > {año_inicio - 1} AND PUBYEAR < {año_fin + 1}"
        )
    else:
        query_ss = ids_parte

    # -- ScopusSearch: lista completa de EIDs --
    try:
        time.sleep(_SLEEP)
        ss = ScopusSearch(query_ss, refresh=True, view="STANDARD")
        results = ss.results or []
        for r in results:
            eid = getattr(r, "eid", None) or getattr(r, "identifier", None)
            if eid:
                eids_todos.add(str(eid).strip())
        logger.info("ScopusSearch(%s...): %d EIDs", query_ss[:60], len(eids_todos))
    except Exception as exc:  # noqa: BLE001
        logger.error("ScopusSearch falló para query '%s': %s", query_ss[:60], exc)

    # -- AuthorRetrieval: document_count por cada ID --
    for aid in author_ids:
        try:
            time.sleep(_SLEEP)
            ar = AuthorRetrieval(aid, refresh=True)
            cnt = ar.document_count or 0
            docs_perfil_total += cnt
            logger.info("AuthorRetrieval(%s): document_count=%d", aid, cnt)
        except Exception as exc:  # noqa: BLE001
            logger.error("AuthorRetrieval(%s) falló: %s", aid, exc)

    return eids_todos, docs_perfil_total


# ---------------------------------------------------------------------------
# Diagnóstico por profesor
# ---------------------------------------------------------------------------


def _diagnosticar_profesor(
    nombre: str,
    author_ids: List[str],
    eids_extraidos: Set[str],
    año_inicio: Optional[int],
    año_fin: Optional[int],
) -> dict:
    """Compara EIDs extraídos vs EIDs según pybliometrics para un profesor."""
    logger.info("Diagnosticando: %s | IDs: %s", nombre, ", ".join(author_ids))

    eids_scopus, docs_perfil_oficial = _eids_pybliometrics(
        author_ids, año_inicio, año_fin
    )

    # Publicaciones en nuestra salida que Scopus NO asigna a este profesor
    eids_extra = eids_extraidos - eids_scopus
    # Publicaciones que Scopus asigna pero que faltan en nuestra salida
    eids_faltantes = eids_scopus - eids_extraidos

    return {
        "profesor": nombre,
        "author_ids": ";".join(author_ids),
        "docs_scopus_perfil": docs_perfil_oficial,
        "docs_extraidos": len(eids_extraidos),
        "docs_scopus_query": len(eids_scopus),
        "diferencia": abs(docs_perfil_oficial - len(eids_extraidos)),
        "n_eids_extra": len(eids_extra),
        "n_eids_faltantes": len(eids_faltantes),
        "eids_extra": "|".join(sorted(eids_extra)) if eids_extra else "",
        "eids_faltantes": "|".join(sorted(eids_faltantes)) if eids_faltantes else "",
    }


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------


def _cargar_calidad(ruta: Path) -> pd.DataFrame:
    """Carga calidad_matching_v2.csv y valida columnas requeridas."""
    if not ruta.exists():
        raise FileNotFoundError(
            f"No se encontró {ruta}. "
            "Ejecuta primero: python -m scripts.02_extraer_validar_exportar_v2"
        )
    df = pd.read_csv(ruta, encoding="utf-8-sig", dtype=str).fillna("")
    for col in ("profesor", "author_ids", "diferencia"):
        if col not in df.columns:
            raise ValueError(
                f"Columna '{col}' no encontrada en {ruta.name}. "
                "Verifica que es la salida del Paso 2 v2."
            )
    df["diferencia"] = pd.to_numeric(df["diferencia"], errors="coerce").fillna(0)
    return df


def _cargar_pubs_v2(ruta: Path) -> pd.DataFrame:
    """Carga publicaciones_v2.csv."""
    if not ruta.exists():
        logger.warning(
            "%s no encontrado. Los EIDs extraídos se tratarán como vacíos.", ruta.name
        )
        return pd.DataFrame(columns=["profesor_asignado", "eid"])
    return pd.read_csv(ruta, encoding="utf-8-sig", dtype=str).fillna("")


def _eids_por_profesor(df_pubs: pd.DataFrame) -> Dict[str, Set[str]]:
    """Construye un índice {nombre_profesor -> set(eids)} desde publicaciones_v2."""
    idx: Dict[str, Set[str]] = {}
    if df_pubs.empty or "profesor_asignado" not in df_pubs.columns:
        return idx
    for nombre, grupo in df_pubs.groupby("profesor_asignado"):
        idx[str(nombre)] = set(grupo["eid"].dropna().str.strip())
    return idx


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------


def main(top_n: int = _TOP_N_DEFAULT, filtrar_año: bool = True) -> None:
    """Orquesta el diagnóstico comparativo."""
    logger.info("=== Paso 3: Diagnóstico de matching iniciado ===")

    # Configurar pybliometrics
    try:
        _configurar_pybliometrics()
    except ValueError as exc:
        print(f"\nError de configuración: {exc}", file=sys.stderr)
        sys.exit(1)

    # Cargar datos
    try:
        df_calidad = _cargar_calidad(_RUTA_CALIDAD)
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n{exc}", file=sys.stderr)
        sys.exit(1)

    df_pubs = _cargar_pubs_v2(_RUTA_PUBS_V2)
    eids_idx = _eids_por_profesor(df_pubs)

    # Seleccionar top N por discrepancia
    df_top = (
        df_calidad[df_calidad["author_ids"].str.strip() != ""]
        .sort_values("diferencia", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )

    if df_top.empty:
        print(
            "\nNo hay profesores con author_ids en calidad_matching_v2.csv.",
            file=sys.stderr,
        )
        sys.exit(0)

    año_inicio = _AÑO_INICIO if filtrar_año else None
    año_fin = _AÑO_FIN if filtrar_año else None
    rango_str = f"{año_inicio}–{año_fin}" if filtrar_año else "sin filtro"

    print(f"\nDiagnosticando top {len(df_top)} profesores (diferencia mayor).")
    print(f"Rango de años: {rango_str}")
    print("(Este proceso hace llamadas a la API; puede tardar varios minutos)\n")

    resultados: List[dict] = []
    for i, (_, fila) in enumerate(df_top.iterrows()):
        nombre = str(fila.get("profesor", "")).strip()
        author_ids = _author_ids_de_fila(fila)
        eids_extraidos = eids_idx.get(nombre, set())

        print(f"  ({i + 1}/{len(df_top)}) {nombre} | IDs: {';'.join(author_ids)}")

        resultado = _diagnosticar_profesor(
            nombre=nombre,
            author_ids=author_ids,
            eids_extraidos=eids_extraidos,
            año_inicio=año_inicio,
            año_fin=año_fin,
        )
        resultados.append(resultado)

        print(
            f"         docs_perfil={resultado['docs_scopus_perfil']} | "
            f"docs_extraidos={resultado['docs_extraidos']} | "
            f"eids_extra={resultado['n_eids_extra']} | "
            f"eids_faltantes={resultado['n_eids_faltantes']}"
        )

    # Guardar salida
    df_diag = pd.DataFrame(resultados)
    col_order = [
        "profesor",
        "author_ids",
        "docs_scopus_perfil",
        "docs_extraidos",
        "docs_scopus_query",
        "diferencia",
        "n_eids_extra",
        "n_eids_faltantes",
        "eids_extra",
        "eids_faltantes",
    ]
    df_diag = df_diag[[c for c in col_order if c in df_diag.columns]]
    df_diag = df_diag.sort_values("n_eids_extra", ascending=False).reset_index(drop=True)

    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df_diag.to_csv(_RUTA_SALIDA, index=False, encoding="utf-8-sig")

    print(f"\nGuardado: {_RUTA_SALIDA}  ({len(df_diag)} profesores)")

    # Resumen en consola
    n_con_extra = (df_diag["n_eids_extra"] > 0).sum()
    n_con_faltantes = (df_diag["n_eids_faltantes"] > 0).sum()
    print("\n" + "=" * 65)
    print(f"  RESUMEN DIAGNÓSTICO  (rango: {rango_str})")
    print("=" * 65)
    print(f"  Profesores analizados         : {len(df_diag)}")
    print(f"  Con EIDs extra (sobre-asig.)  : {n_con_extra}")
    print(f"  Con EIDs faltantes (sub-asig.): {n_con_faltantes}")
    if n_con_extra:
        peor = df_diag.iloc[0]
        print(
            f"  Caso crítico (más extra)      : {peor['profesor']} "
            f"({peor['n_eids_extra']} extra)"
        )
    print("=" * 65)
    print(
        "\n  Revisa diagnostico_errores.csv — columna 'eids_extra' lista\n"
        "  los EIDs que se deben eliminar; 'eids_faltantes' los que faltan."
    )

    logger.info("=== Paso 3 finalizado ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Diagnóstico comparativo de matching (Paso 3)."
    )
    parser.add_argument(
        "--top",
        type=int,
        default=_TOP_N_DEFAULT,
        metavar="N",
        help=f"Número de profesores a analizar (default: {_TOP_N_DEFAULT})",
    )
    parser.add_argument(
        "--sin-año",
        action="store_true",
        dest="sin_año",
        help="Omitir el filtro de año (analiza publicaciones históricas completas)",
    )
    args = parser.parse_args()
    main(top_n=args.top, filtrar_año=not args.sin_año)
