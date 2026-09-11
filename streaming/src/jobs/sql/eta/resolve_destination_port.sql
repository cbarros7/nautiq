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
        {resolved_port_cases}
        ELSE {default_port} 
    END AS _resolved_port,
    CASE 
        {port_lat_cases}
    END AS _port_lat,
    CASE 
        {port_lon_cases}
    END AS _port_lon,
    CASE 
        {port_radius_cases}
    END AS _port_radius
FROM StaticKafka
WHERE ship_type BETWEEN {cargo_min} AND {cargo_max}
    AND ({port_filter})
