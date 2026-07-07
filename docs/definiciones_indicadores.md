# Definiciones y fórmulas de los indicadores del dashboard

Última actualización: 2026-07-06. Este documento es la referencia normativa
de cómo se calcula cada indicador del Monitor Bibliométrico. Si un gráfico
contradice lo aquí descrito, el gráfico está mal.

## Convenciones generales

- **Fuente de citas**: columna `publicacion.cited_by_count` (conteo de citas
  de Scopus al momento de la última descarga). Los valores nulos se tratan
  como 0. No se recalculan citas "del período": `cited_by_count` es el
  acumulado histórico de cada publicación; el filtro de período selecciona
  *qué publicaciones* entran (por su año de publicación), no qué citas.
- **Filtros**: Área y Profesor se aplican en SQL por IDs
  (`EXISTS`/`JOIN` sobre `publicacion_profesor`); Desde/Hasta filtran
  `anio_publicacion` en SQL; Tipo y Cuartil se aplican como post-filtro en
  pandas (`_apply_tipo_filter`, `_apply_cuartil_filter`).
- **Conteo por área ("whole counting")**: una publicación pertenece a un
  área si al menos un profesor del área está vinculado a ella, y se cuenta
  **una sola vez** dentro del área (el `EXISTS` de `get_publicaciones`
  elimina duplicados por múltiples profesores de la misma área). Una
  publicación con co-autores de dos áreas cuenta una vez en **cada** área;
  por eso la suma de las áreas puede superar el total de la División
  (estándar bibliométrico de conteo completo).
- **Conteo por profesor**: cada publicación del profesor cuenta completa
  para él (sin fraccionar por número de autores). En consecuencia, la suma
  de citas de los profesores de un área **no** es igual a las citas del
  área: las co-autorías internas se contarían k veces. Los agregados por
  área siempre se calculan sobre publicaciones únicas, nunca sumando la
  tabla por profesor.
- **h-index (único método en todo el dashboard)**: se calcula por
  ordenamiento de citas sobre las publicaciones del ámbito (profesor, área,
  División o Universidad) **que pasan los filtros activos**
  (`metrics.calcular_h_index_desde_citas`):

  ```
  1. Tomar cited_by_count de cada publicación del conjunto filtrado
     (nulos = 0) y ordenarlas de mayor a menor: c(1) ≥ c(2) ≥ ... ≥ c(n).
  2. h = max { i : c(i) ≥ i }
     (la posición más alta i cuya publicación tiene al menos i citas;
      equivalente: existen h publicaciones con ≥ h citas cada una).
  ```

  Ejemplo: citas ordenadas [30, 12, 7, 4, 2] → c(1)=30≥1, c(2)=12≥2,
  c(3)=7≥3, c(4)=4≥4, c(5)=2<5 → **h = 4**.

  El h-index del perfil Scopus (`profesor.h_index`) **ya no se muestra** en
  ninguna vista; queda en la BD solo como referencia. Al filtrar por
  período/tipo/cuartil, el h-index mostrado se recalcula sobre ese
  subconjunto (por eso puede ser menor que el del perfil Scopus, que cubre
  toda la carrera del autor).

## Impacto (citas) por profesor — scatter "Producción vs Impacto", ranking y perfil

- `publicaciones_total` = número de publicaciones únicas del profesor que
  pasan los filtros activos (período/tipo/cuartil).
- `citas_totales` = `Σ cited_by_count` de esas mismas publicaciones.
- `citas_por_pub` = `citas_totales / publicaciones_total` (tabla "Impacto
  por Cita Promedio"; requiere ≥ 3 publicaciones).
- `h_index` = h-index **calculado por sort** (ver fórmula en Convenciones)
  sobre esas mismas publicaciones filtradas. El tamaño de burbuja del
  scatter y la columna del ranking usan este valor recalculado; no se usa
  el h-index del perfil Scopus.
- Las tres vistas (scatter de Impacto, ranking de Rankings, KPIs del
  perfil) usan la misma función (`_build_profesor_comparativa` /
  `_fetch_publicaciones`), por lo que son idénticas por construcción.

## Citas acumuladas por área (vista Impacto)

`Σ cited_by_count` de las **publicaciones únicas** del área en el período
filtrado (`_build_citas_por_departamento`). Coincide con el KPI de citas y
con la tabla de Visión General para la misma selección de filtros.

## SJR promedio por área (vista Calidad de Fuente)

Promedio simple de la columna `sjr` sobre las publicaciones únicas del área
que pasan los filtros, ignorando nulos
(`metrics.calcular_metricas_fuente_promedio`). El SJR de cada publicación es
el de su revista **en el año de publicación**
(`fuente_metrica.anio = publicacion.anio_publicacion`). Publicaciones en
revistas sin SJR no aportan al promedio (pero sí al denominador de
cobertura `cobertura_sjr`).

## Red de co-autoría (vista Colaboración)

- Base: las publicaciones que pasan **todos** los filtros activos (área,
  profesor, período, tipo, cuartil) — el mismo `base_df` del resto de la
  vista.
- Aristas: pares de profesores (a, b) con `id_a < id_b` vinculados a una
  misma publicación de la base; peso = número de co-publicaciones
  (`metrics.calcular_coautoria_pares`).
- Con **Área** seleccionada: solo profesores del área (ambos extremos).
- Con **Profesor** seleccionado: red ego (el profesor y sus co-autores de
  la División en las publicaciones filtradas).
- Sin co-publicaciones para la combinación: se muestra un aviso con los
  filtros activos en lugar del grafo.
- Tamaño del nodo = h-index del profesor calculado por sort sobre las
  publicaciones visibles con los filtros activos.

## Radar "Perfil multidimensional por área" (vista Rankings)

Compara **siempre** las tres áreas de la División aplicando los filtros de
período/tipo/cuartil (ignora la selección de Área/Profesor: un radar de una
sola área es degenerado — todo quedaría en 1.0).

Valores crudos por área (sobre publicaciones únicas del área):

| Dimensión | Fórmula | Sensible a filtros |
|---|---|---|
| **Volumen** | nº de publicaciones únicas en el período | período/tipo/cuartil |
| **Impacto** | `Σ cited_by_count / nº publicaciones` (citas por publicación) | período/tipo/cuartil |
| **Calidad** | proporción de publicaciones en revistas Q1 o Q2 (SJR del año de publicación) sobre el total del área, incluyendo "Sin dato" en el denominador | período/tipo/cuartil |
| **h-index** | h-index del área calculado por sort (`h = max{i : c(i) ≥ i}`) sobre las publicaciones únicas del área que pasan los filtros | período/tipo/cuartil |
| **Tendencia** | `pubs [hasta−2, hasta] / max(pubs [hasta−5, hasta−3], 1)` — trienio reciente sobre trienio anterior; 1.0 = estable | período/tipo/cuartil |

Notas de diseño:

- **Impacto usa citas por publicación**, no citas totales: el tamaño del
  área ya lo mide Volumen; usar totales en ambas dimensiones duplicaría el
  peso del tamaño y hacía que el área más grande saturara el radar.
- **Tendencia** necesita al menos 6 años en el rango Desde–Hasta para que
  ambos trienios estén completos; con rangos más cortos la comparación es
  parcial.

### Normalización

Cada dimensión se divide por el **máximo entre las tres áreas**:

```
valor_normalizado(área, dim) = valor_crudo(área, dim) / max(valor_crudo(·, dim))
```

- Rango [0, 1] por eje; **el área líder de cada eje marca exactamente 1.0**.
  Que un área aparezca en 1.0 en varios ejes significa que lidera esas
  dimensiones (p. ej., sin filtros, Física y Geociencias lidera Volumen,
  Impacto, Calidad y h-index), no que haya un error.
- Se descartó la alternativa "las áreas suman 1 por eje" (normalización por
  participación): haría que los valores dependieran del número de áreas,
  comprimiría las diferencias (tres áreas parecidas quedarían todas ≈ 0.33)
  y el radar nunca alcanzaría 1. La normalización por máximo conserva los
  cocientes entre áreas (si A tiene el doble que B, se ve el doble) y tiene
  lectura directa: 1 = mejor área del eje.
- El hover del radar muestra el valor normalizado y el valor real crudo.

## KPIs (tarjetas superiores)

- **Universidad del Norte**: toda la tabla `publicacion` (descarga por
  AF-ID institucional), sin filtros; h-index calculado por sort sobre todas
  esas publicaciones. Constantes por diseño.
- **División / Área / Profesor**: publicaciones únicas del alcance con los
  filtros activos; citas = `Σ cited_by_count`; % Q1+Q2 sobre el total
  (incluye "Sin dato"); h-index = calculado por sort sobre las
  publicaciones del alcance filtrado (misma fórmula en todos los niveles;
  ver Convenciones).
