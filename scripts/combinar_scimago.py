"""
Combina los CSV anuales descargados de SCImago Journal Rank en el archivo
único que consume el ETL: ``data/raw/scimago_2014_2025.csv``.

Cada CSV de SCImago (descargado con "Download data") viene separado por ';'
y SIN columna de año. Este script:
  1. Descubre los CSV en la carpeta de entrada.
  2. Infiere el año del nombre del archivo (p. ej. "scimagojr 2014.csv" -> 2014).
  3. Añade la columna ``Year``.
  4. Concatena todo y escribe el CSV combinado.

Uso:
    python scripts/combinar_scimago.py
    python scripts/combinar_scimago.py --entrada data/external/scimago_anual
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
_YEAR_RE = re.compile(r"(20[01]\d|202[0-5])")


def _leer_scimago(path: Path) -> pd.DataFrame:
    """Lee un CSV de SCImago probando separador ';' y luego ','."""
    for sep in (";", ","):
        try:
            df = pd.read_csv(path, sep=sep, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(path, sep=sep, encoding="latin-1")
        if len(df.columns) >= 3:
            return df
    raise ValueError(f"No se pudo parsear {path.name} con ';' ni ','.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Combina CSV anuales de SCImago.")
    parser.add_argument(
        "--entrada",
        type=Path,
        default=ROOT / "data" / "external" / "scimago_anual",
        help="Carpeta con los CSV anuales descargados de SCImago.",
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=ROOT / "data" / "raw" / "scimago_2014_2025.csv",
        help="Ruta del CSV combinado de salida.",
    )
    args = parser.parse_args()

    if not args.entrada.exists():
        raise SystemExit(f"No existe la carpeta de entrada: {args.entrada}")

    archivos = sorted(args.entrada.glob("*.csv"))
    if not archivos:
        raise SystemExit(f"No se encontraron CSV en {args.entrada}")

    frames = []
    for f in archivos:
        m = _YEAR_RE.search(f.stem)
        if not m:
            print(f"  ! Omitido (sin año en el nombre): {f.name}")
            continue
        anio = int(m.group(1))
        df = _leer_scimago(f)
        df.columns = df.columns.str.strip()
        df["Year"] = anio
        frames.append(df)
        print(f"  + {f.name}: {len(df):,} filas (Year={anio})")

    if not frames:
        raise SystemExit("Ningún archivo tenía año en el nombre; nada que combinar.")

    combinado = pd.concat(frames, ignore_index=True)

    # Verificar columnas mínimas que espera el ETL
    requeridas = ["Year", "Issn", "SJR", "SJR Best Quartile", "H index"]
    faltan = [c for c in requeridas if c not in combinado.columns]
    if faltan:
        print(f"  ! ADVERTENCIA: faltan columnas esperadas: {faltan}")
        print(f"    Columnas presentes: {list(combinado.columns)}")

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    combinado.to_csv(args.salida, index=False, encoding="utf-8-sig")

    años = sorted(combinado["Year"].unique())
    print(
        f"\nListo: {args.salida}\n"
        f"  {len(combinado):,} filas | años {años[0]}–{años[-1]} "
        f"({len(años)} años)"
    )


if __name__ == "__main__":
    main()
