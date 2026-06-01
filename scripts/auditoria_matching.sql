-- ============================================================
-- AUDITORÍA DE MATCHING PUBLICACIÓN-PROFESOR
-- Ejecutar contra la base de datos PostgreSQL (esquema: biblio)
-- ============================================================

-- 1. CONTEO DE PUBLICACIONES POR PROFESOR
--    Ordenado descendente — los valores anormalmente altos son sospechosos.
SELECT
    pr.nombre_normalizado,
    d.codigo  AS departamento,
    COUNT(DISTINCT pp.id_publicacion) AS total_pubs,
    COUNT(DISTINCT CASE WHEN p.anio_publicacion >= EXTRACT(YEAR FROM NOW()) - 2
                        THEN pp.id_publicacion END) AS pubs_ultimos_3_anios
FROM biblio.publicacion_profesor pp
JOIN biblio.profesor           pr ON pp.id_profesor    = pr.id_profesor
JOIN biblio.departamento        d ON pr.id_departamento = d.id_departamento
JOIN biblio.publicacion         p ON pp.id_publicacion  = p.id_publicacion
GROUP BY pr.nombre_normalizado, d.codigo
ORDER BY total_pubs DESC;


-- 2. PUBLICACIONES VINCULADAS A MÚLTIPLES PROFESORES
--    Una publicación real puede tener co-autores en la División.
--    Valores > 3 son sospechosos (más probablemente un false positive).
SELECT
    p.eid,
    p.titulo,
    p.anio_publicacion,
    COUNT(DISTINCT pp.id_profesor) AS n_profesores_vinculados,
    STRING_AGG(pr.nombre_normalizado, ' | ' ORDER BY pr.nombre_normalizado)
        AS profesores
FROM biblio.publicacion         p
JOIN biblio.publicacion_profesor pp ON p.id_publicacion  = pp.id_publicacion
JOIN biblio.profesor            pr ON pp.id_profesor     = pr.id_profesor
GROUP BY p.eid, p.titulo, p.anio_publicacion
HAVING COUNT(DISTINCT pp.id_profesor) > 1
ORDER BY n_profesores_vinculados DESC, p.anio_publicacion DESC;


-- 3. DISTRIBUCIÓN DE MÉTODOS DE VINCULACIÓN
--    Cuántos links se crearon por cada método y cuál es el score promedio.
SELECT
    metodo_vinculacion,
    COUNT(*)                        AS total_links,
    ROUND(AVG(score_similitud)::numeric, 4) AS score_promedio,
    ROUND(MIN(score_similitud)::numeric, 4) AS score_minimo,
    ROUND(MAX(score_similitud)::numeric, 4) AS score_maximo
FROM biblio.publicacion_profesor
GROUP BY metodo_vinculacion
ORDER BY total_links DESC;


-- 4. LINKS POR MÉTODO Y PROFESOR
--    Profesores con muchos links de fuzzy o fuzzy_afiliacion son
--    candidatos prioritarios de revisión manual.
SELECT
    pr.nombre_normalizado,
    d.codigo AS departamento,
    SUM(CASE WHEN pp.metodo_vinculacion = 'exacto'          THEN 1 ELSE 0 END) AS exacto,
    SUM(CASE WHEN pp.metodo_vinculacion = 'fuzzy'           THEN 1 ELSE 0 END) AS fuzzy,
    SUM(CASE WHEN pp.metodo_vinculacion = 'fuzzy_afiliacion' THEN 1 ELSE 0 END) AS fuzzy_afiliacion,
    COUNT(*) AS total
FROM biblio.publicacion_profesor pp
JOIN biblio.profesor           pr ON pp.id_profesor    = pr.id_profesor
JOIN biblio.departamento        d ON pr.id_departamento = d.id_departamento
GROUP BY pr.nombre_normalizado, d.codigo
ORDER BY (fuzzy + fuzzy_afiliacion) DESC, total DESC;


-- 5. PROFESORES CON CONTEO ANORMALMENTE ALTO
--    Umbral orientativo: más del doble del promedio del departamento.
WITH conteos AS (
    SELECT
        pr.id_profesor,
        pr.nombre_normalizado,
        d.codigo AS departamento,
        COUNT(DISTINCT pp.id_publicacion) AS total_pubs
    FROM biblio.publicacion_profesor pp
    JOIN biblio.profesor           pr ON pp.id_profesor    = pr.id_profesor
    JOIN biblio.departamento        d ON pr.id_departamento = d.id_departamento
    GROUP BY pr.id_profesor, pr.nombre_normalizado, d.codigo
),
promedios AS (
    SELECT departamento, AVG(total_pubs) AS promedio_depto
    FROM conteos
    GROUP BY departamento
)
SELECT
    c.nombre_normalizado,
    c.departamento,
    c.total_pubs,
    ROUND(p.promedio_depto::numeric, 1) AS promedio_depto,
    ROUND((c.total_pubs / NULLIF(p.promedio_depto, 0))::numeric, 2) AS ratio_vs_promedio
FROM conteos c
JOIN promedios p ON c.departamento = p.departamento
WHERE c.total_pubs > 2 * p.promedio_depto
ORDER BY ratio_vs_promedio DESC;


-- 6. LINKS FUZZY CON SCORE BAJO (más riesgo de false positive)
--    Estos son los candidatos más peligrosos post-corrección.
SELECT
    pr.nombre_normalizado,
    p.eid,
    p.titulo,
    p.anio_publicacion,
    pp.metodo_vinculacion,
    pp.score_similitud,
    pp.nombre_autor_original
FROM biblio.publicacion_profesor pp
JOIN biblio.profesor pr ON pp.id_profesor   = pr.id_profesor
JOIN biblio.publicacion p  ON p.id_publicacion = pp.id_publicacion
WHERE pp.metodo_vinculacion IN ('fuzzy', 'fuzzy_afiliacion')
  AND pp.score_similitud < 0.95
ORDER BY pp.score_similitud ASC, pr.nombre_normalizado;


-- 7. DUPLICADOS LÓGICOS EN publicacion_profesor
--    La PK (id_publicacion, id_profesor) previene duplicados exactos,
--    pero esta query detecta si hay múltiples filas por (eid, orcid)
--    como síntoma de runs múltiples del ETL.
SELECT
    p.eid,
    pr.orcid,
    COUNT(*) AS n_filas
FROM biblio.publicacion_profesor pp
JOIN biblio.publicacion p  ON p.id_publicacion = pp.id_publicacion
JOIN biblio.profesor   pr ON pr.id_profesor    = pp.id_profesor
GROUP BY p.eid, pr.orcid
HAVING COUNT(*) > 1;
-- Si retorna filas, hay un bug en el upsert (no debería con la PK actual).


-- 8. PROFESORES CON CONTEO ANORMALMENTE BAJO
--    Sospechoso cuando el conteo del sistema es < 50% del promedio del depto
--    O cuando hay 0 publicaciones para un profesor activo.
WITH conteos AS (
    SELECT
        pr.id_profesor,
        pr.nombre_normalizado,
        d.codigo AS departamento,
        COUNT(DISTINCT pp.id_publicacion) AS total_pubs
    FROM biblio.profesor            pr
    LEFT JOIN biblio.publicacion_profesor pp ON pp.id_profesor    = pr.id_profesor
    JOIN  biblio.departamento        d ON pr.id_departamento = d.id_departamento
    GROUP BY pr.id_profesor, pr.nombre_normalizado, d.codigo
),
promedios AS (
    SELECT departamento, AVG(total_pubs) AS promedio_depto
    FROM conteos
    GROUP BY departamento
)
SELECT
    c.nombre_normalizado,
    c.departamento,
    c.total_pubs,
    ROUND(p.promedio_depto::numeric, 1) AS promedio_depto,
    ROUND((c.total_pubs / NULLIF(p.promedio_depto, 0))::numeric, 2) AS ratio_vs_promedio
FROM conteos c
JOIN promedios p ON c.departamento = p.departamento
WHERE c.total_pubs < 0.5 * p.promedio_depto
ORDER BY c.total_pubs ASC, c.departamento;


-- 9. PROFESORES SIN NINGUNA PUBLICACIÓN VINCULADA
--    Si hay profesores con Auth_ID en la tabla autor_scopus pero ninguna pub,
--    sugiere que el matching no reconoce su nombre o ID.
SELECT
    pr.orcid,
    pr.nombre_normalizado,
    d.codigo AS departamento,
    (
        SELECT COUNT(*)
        FROM biblio.autor_scopus au
        WHERE au.id_profesor = pr.id_profesor
    ) AS n_perfiles_scopus
FROM biblio.profesor pr
JOIN biblio.departamento d ON pr.id_departamento = d.id_departamento
WHERE NOT EXISTS (
    SELECT 1
    FROM biblio.publicacion_profesor pp
    WHERE pp.id_profesor = pr.id_profesor
)
ORDER BY d.codigo, pr.nombre_normalizado;


-- 10. DISTRIBUCIÓN DE MÉTODOS INCLUYENDO id_scopus
--     Después de implementar Tier-1 (id_scopus), esta query muestra cuántos
--     links provienen de cada nivel de confianza.
SELECT
    metodo_vinculacion,
    COUNT(*)                        AS total_links,
    ROUND(AVG(score_similitud)::numeric, 4) AS score_promedio
FROM biblio.publicacion_profesor
GROUP BY metodo_vinculacion
ORDER BY
    CASE metodo_vinculacion
        WHEN 'id_scopus' THEN 1
        WHEN 'exacto'    THEN 2
        WHEN 'fuzzy'     THEN 3
        ELSE 4
    END;


-- 11. RESUMEN RÁPIDO PARA DETECTAR REGRESIONES DESPUÉS DEL ETL
--     Ejecutar antes y después de cada re-carga para comparar.
SELECT
    'total_links'         AS metrica, COUNT(*)::text AS valor FROM biblio.publicacion_profesor
UNION ALL
SELECT 'links_id_scopus', COUNT(*)::text FROM biblio.publicacion_profesor WHERE metodo_vinculacion = 'id_scopus'
UNION ALL
SELECT 'links_exacto',    COUNT(*)::text FROM biblio.publicacion_profesor WHERE metodo_vinculacion = 'exacto'
UNION ALL
SELECT 'links_fuzzy',     COUNT(*)::text FROM biblio.publicacion_profesor WHERE metodo_vinculacion = 'fuzzy'
UNION ALL
SELECT 'profesores_con_pubs',        COUNT(DISTINCT id_profesor)::text   FROM biblio.publicacion_profesor
UNION ALL
SELECT 'profesores_sin_pubs', (
    SELECT COUNT(*) FROM biblio.profesor pr
    WHERE NOT EXISTS (SELECT 1 FROM biblio.publicacion_profesor pp WHERE pp.id_profesor = pr.id_profesor)
)::text
UNION ALL
SELECT 'publicaciones_vinculadas',   COUNT(DISTINCT id_publicacion)::text FROM biblio.publicacion_profesor;
