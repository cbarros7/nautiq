/* VISTA TEMPORAL: Mapea el string libre de destino AIS a un puerto
objetivo conocido y sus coordenadas. */
CREATE TEMPORARY VIEW resolved_destination AS
SELECT 
    mmsi, 
    imo, 
    name, 
    ship_type, 
    length_m, 
    beam_m, 
    draught_m, 
    destination, 
    eta,
    CASE
        WHEN {valencia_filter} THEN 'VALENCIA'
        WHEN {algeciras_filter} THEN 'ALGECIRAS'
        WHEN {bcn_filter} THEN 'BARCELONA'
        ELSE '{default_port}'  
    END AS _resolved_port,
    CASE 
        WHEN {valencia_filter} THEN 39.4457 
        WHEN {algeciras_filter} THEN 36.12972 
        WHEN {bcn_filter} THEN 41.338 
    END AS _port_lat,
    CASE 
        WHEN {valencia_filter} THEN -0.3198 
        WHEN {algeciras_filter} THEN -5.42278 
        WHEN {bcn_filter} THEN 2.1675 
    END AS _port_lon,
    5.0 AS _port_radius
FROM StaticKafka
WHERE ship_type BETWEEN {cargo_min} AND {cargo_max}
    AND ({port_filter})
