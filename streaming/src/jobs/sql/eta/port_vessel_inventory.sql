/* VISTA TEMPORAL: Clasifica buques (Atracados, Fondeados, En Camino) de forma continua.
NOTA: Esta vista ahora solo realiza la unión de los buques filtrados por su estado sin agrupar.
La agrupación y deduplicación por ventanas se realiza en el paso de resumen para mantener
el pipeline de ejecución de Flink estrictamente como insert-only (append-only). */
CREATE TEMPORARY VIEW port_vessel_inventory AS
-- 1. ATRACADOS
SELECT 
    rd._resolved_port AS port_name, 
    'ATRACADO' AS vessel_status, 
    p.mmsi, 
    rd.length_m, 
    rd.ship_type,
    p.`_event_time`
FROM enriched_positions p 
INNER JOIN resolved_destination rd ON p.mmsi = rd.mmsi
WHERE p.nav_status = 5 
  AND (3440.065 * ACOS(
        CASE 
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon))) > 1.0 THEN 1.0
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon))) < -1.0 THEN -1.0
            ELSE (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon)))
        END
    )) <= rd._port_radius

UNION ALL

-- 2. FONDEADOS
SELECT 
    rd._resolved_port AS port_name, 
    'FONDEADO' AS vessel_status, 
    p.mmsi, 
    rd.length_m, 
    rd.ship_type,
    p.`_event_time`
FROM enriched_positions p 
INNER JOIN resolved_destination rd ON p.mmsi = rd.mmsi
WHERE p.nav_status = 1 
  AND (3440.065 * ACOS(
        CASE 
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon))) > 1.0 THEN 1.0
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon))) < -1.0 THEN -1.0
            ELSE (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon)))
        END
    )) <= rd._port_radius

UNION ALL

-- 3. EN CAMINO (Fuera del radio, velocidad > 0.5 y ETA <= EN_CAMINO_MAX_ETA_HOURS)
SELECT 
    rd._resolved_port AS port_name, 
    'EN_CAMINO' AS vessel_status, 
    p.mmsi, 
    rd.length_m, 
    rd.ship_type,
    p.`_event_time`
FROM enriched_positions p 
INNER JOIN resolved_destination rd ON p.mmsi = rd.mmsi
WHERE (3440.065 * ACOS(
        CASE 
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon))) > 1.0 THEN 1.0
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon))) < -1.0 THEN -1.0
            ELSE (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon)))
        END
    )) > rd._port_radius 
  AND p.speed > 0.5 
  AND ((3440.065 * ACOS(
        CASE 
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon))) > 1.0 THEN 1.0
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon))) < -1.0 THEN -1.0
            ELSE (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) * COS(RADIANS(rd._port_lon - p.lon)))
        END
    )) / NULLIF(p.speed, 0)) <= {en_camino_max_eta}
