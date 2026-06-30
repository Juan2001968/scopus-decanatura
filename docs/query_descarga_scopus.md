# Guía de descarga de datos desde Scopus (2014–2025)

Documento de apoyo para repoblar `data/raw/` con las exportaciones anuales que
consume el pipeline ETL (`src/etl/ingest_publications.py`). Alcance acordado:
**toda la producción de Universidad del Norte por año**; la vinculación a los
profesores de la división la resuelve después `src/etl/link_authors.py`.

---

## 1. Cómo lo usa el proyecto (contexto)

- El ETL **no usa la API** para la descarga masiva: lee CSV anuales desde
  `data/raw/` (`discover_scopus_csvs` → `load_all_publications`).
- Espera un archivo por año, p. ej. `scopus_2014.csv` … `scopus_2025.csv`.
  El año se infiere del nombre del archivo con la regex `(20[01]\d|202[0-5])`,
  así que **el nombre debe contener el año** y no debe empezar por `Prof_`
  (esos se ignoran porque son los CSV de profesores).
- Las columnas del CSV se renombran según `_COLUMN_MAP`. Por eso hay que
  exportar desde Scopus con los campos correctos (ver sección 4).
- El matching Tier-1 (`link_authors.py`) extrae el Scopus Author ID del campo
  **`Author full names`** (formato `Apellido, Nombre (57214321859)`) y filtra por
  afiliación a `Universidad del Norte`. Por eso ese campo y `Affiliations` son
  obligatorios en la exportación.

---

## 2. El query (Scopus Advanced Search)

Entra a <https://www.scopus.com> → **Search → Advanced document search** y corre
**un query por cada año**, cambiando solo el `PUBYEAR`.

### Opción recomendada — por AF-ID (afiliación institucional)

```text
AF-ID(60054319) AND PUBYEAR = 2014
```

> **AF-ID confirmado de Universidad del Norte (Barranquilla, Colombia):
> `60054319`** (~5.897 documentos en total, 2014–2025). NO usar `60052106`,
> que corresponde a otra institución homónima.

`AF-ID` es la forma más limpia y estable de capturar toda la producción de la
institución.

**Cómo obtener el AF-ID exacto** (no es público fuera de Scopus, hazlo una vez):
1. En Scopus, ve a **Search → Affiliations**.
2. Busca `Universidad del Norte` y filtra país `Colombia` (Barranquilla).
3. Abre el perfil institucional; el AF-ID aparece en la URL y en la cabecera
   del perfil (`...affiliationId=XXXXXXXX`).
4. Si Uninorte tiene varios perfiles/variantes, combínalos con `OR`:
   `AF-ID(11111111) OR AF-ID(22222222)`.

### Opción de respaldo — por nombre de afiliación (si no tienes el AF-ID a mano)

```text
( AFFILORG("Universidad del Norte") OR AFFILORG(Uninorte) )
AND AFFILCOUNTRY(Colombia)
AND PUBYEAR = 2014
```

> El AF-ID es preferible: `AFFILORG` por texto puede dejar fuera variantes de
> nombre o colar afiliaciones homónimas. Úsalo solo como respaldo.

### Acotar el período completo en un solo query (opcional)

Si prefieres revisar el total antes de exportar año a año:

```text
AF-ID(<AF_ID_UNINORTE>) AND PUBYEAR > 2013 AND PUBYEAR < 2026
```

Pero **para exportar conviene hacerlo año por año** (ver sección 5: límites).

---

## 3. Lista de queries año a año (2014–2025)

Cambia solo el último número. Doce corridas:

```text
AF-ID(60054319) AND PUBYEAR = 2014
AF-ID(60054319) AND PUBYEAR = 2015
AF-ID(60054319) AND PUBYEAR = 2016
AF-ID(60054319) AND PUBYEAR = 2017
AF-ID(60054319) AND PUBYEAR = 2018
AF-ID(60054319) AND PUBYEAR = 2019
AF-ID(60054319) AND PUBYEAR = 2020
AF-ID(60054319) AND PUBYEAR = 2021
AF-ID(60054319) AND PUBYEAR = 2022
AF-ID(60054319) AND PUBYEAR = 2023
AF-ID(60054319) AND PUBYEAR = 2024
AF-ID(60054319) AND PUBYEAR = 2025
```

---

## 4. Qué campos exportar (para que las columnas coincidan con el ETL)

En cada año: selecciona los resultados → **Export → CSV**. En el panel
"Select what to export", marca **todas las casillas** (Citation information,
Bibliographical information, Abstract & keywords, Funding details, Other
information / References). Es la forma más segura de que no falte ninguna
columna que el ETL mapea.

Como mínimo imprescindible, el ETL (`_COLUMN_MAP`) usa estas columnas de Scopus:

| Campo Scopus (CSV)              | Por qué se necesita                          |
|---------------------------------|----------------------------------------------|
| Authors                         | autores (texto)                              |
| **Author full names**           | **matching Tier-1: contiene el Scopus ID**   |
| **Author(s) ID**                | IDs numéricos de autores                     |
| Document Title                  | título                                       |
| Year                            | año de publicación                           |
| **EID**                         | clave única de la publicación                |
| Source title / Abbreviated…     | fuente / revista                             |
| Volume, Issue, Page start/end, Page count | datos bibliográficos               |
| Cited by                        | conteo de citas                              |
| DOI                             | identificador                                |
| **Affiliations**                | **filtro de afiliación Uninorte (Tier-3)**   |
| Index Keywords                  | palabras clave                               |
| References                      | referencias (análisis de autocitas)          |
| Correspondence Address          | autor de correspondencia                     |
| Publisher, ISSN, PubMed ID      | metadatos de fuente                          |
| Language of Original Document   | idioma                                       |
| Document Type, Publication Stage, Open Access | tipo y estado del documento  |

> Importante: `Author full names` y `Affiliations` son los dos campos críticos
> para que la vinculación profesor–publicación funcione. No los omitas.

---

## 5. Límites de exportación de Scopus (clave para tu caso)

- La **exportación CSV completa** (la que incluye **References**, abstract, etc.)
  está limitada a **2.000 documentos por exportación**.
- La exportación CSV de solo metadatos básicos llega a 20.000, pero **no trae
  References** — y tu ETL sí mapea `References`.

Como Uninorte en los años recientes puede superar 2.000 documentos/año, si un
año excede ese tope tienes dos caminos:

1. **Partir el año** con un filtro adicional y unir los CSV resultantes, p. ej.
   por tipo de documento:
   ```text
   AF-ID(<AF_ID_UNINORTE>) AND PUBYEAR = 2024 AND DOCTYPE(ar)   # artículos
   AF-ID(<AF_ID_UNINORTE>) AND PUBYEAR = 2024 AND NOT DOCTYPE(ar)
   ```
   o usando el selector "documents X to Y" del panel de exportación
   (1–2000, 2001–4000, …). Guarda los trozos y concaténalos en el mismo
   `scopus_2024.csv` (el ETL deduplica por EID más adelante).
2. Para la mayoría de los años antiguos (2014–~2019) probablemente quepas en una
   sola exportación.

---

## 6. Nombrado y ubicación de los archivos

- Guarda cada exportación como `scopus_<AÑO>.csv` (UTF-8) dentro de la carpeta
  `data/raw/` del proyecto. Ejemplos válidos: `scopus_2014.csv`,
  `scopus_2025.csv`.
- No uses el prefijo `Prof_` (reservado para los CSV de profesores, que el ETL
  excluye).
- Si partiste un año en varios trozos, puedes nombrarlos
  `scopus_2024_a.csv`, `scopus_2024_b.csv`: la regex toma el año igual y el ETL
  los concatena y deduplica por EID.

---

## 7. Después de descargar

```bash
# Con los CSV ya en data/raw/
python scripts/run_etl.py
```

El pipeline: ingiere → estandariza columnas → limpia → normaliza → vincula
autores (Tier 1/2/3) → carga. La vinculación a los profesores de la división
ocurre en esa fase, así que descargar toda Uninorte por año es correcto.

> Nota: si también perdiste el roster de profesores (tablas `profesor` /
> `autor_scopus` vivían en PostgreSQL), necesitarás reponer el/los CSV de
> profesores (`Prof_*.csv` con sus Scopus Author IDs / ORCID) para que
> `link_authors.py` tenga contra qué cruzar. Avísame si es el caso y lo vemos.
