/* VISTA TEMPORAL: Calcula el ETA Dinámico usando la Ley Esférica de
Cosenos desde posiciones limpiadas. */
CREATE TEMPORARY VIEW eta_dynamic AS
SELECT 
    p.mmsi, 
    p.lat, 
    p.lon, 
    p.speed, 
    p.cog, 
    p.nav_status, 
    p.correlation_id,
    p.`_event_time`,
    rd.name AS vessel_name, 
    rd.imo, 
    rd.ship_type, 
    rd.length_m, 
    rd.beam_m, 
    rd.draught_m, 
    rd.destination, 
    rd.eta AS eta_static_raw,
    rd._resolved_port AS destination_port, 
    rd._port_lat AS port_lat, 
    rd._port_lon AS port_lon,
    -- Ley Esférica de los Cosenos (millas náuticas)
    3440.065 * ACOS(
        CASE 
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) 
                + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) 
                * COS(RADIANS(rd._port_lon - p.lon))) > 1.0 THEN 1.0
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) 
                + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) 
                * COS(RADIANS(rd._port_lon - p.lon))) < -1.0 THEN -1.0
            ELSE (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) 
                + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) 
                * COS(RADIANS(rd._port_lon - p.lon)))
        END
    ) AS _distance_to_port_nm,
    (3440.065 * ACOS(
        CASE 
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) 
                + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) 
                * COS(RADIANS(rd._port_lon - p.lon))) > 1.0 THEN 1.0
            WHEN (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) 
                + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) 
                * COS(RADIANS(rd._port_lon - p.lon))) < -1.0 THEN -1.0
            ELSE (SIN(RADIANS(p.lat)) * SIN(RADIANS(rd._port_lat)) 
                + COS(RADIANS(p.lat)) * COS(RADIANS(rd._port_lat)) 
                * COS(RADIANS(rd._port_lon - p.lon)))
        END
    ) / NULLIF(p.speed, 0)) AS _eta_dynamic_hours
FROM enriched_positions p
INNER JOIN resolved_destination rd ON p.mmsi = rd.mmsi
WHERE p.speed > 0.5
