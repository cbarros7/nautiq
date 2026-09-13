/* VISTA TEMPORAL: Agrupa y pre-agrega el inventario en un proceso de 2 fases.
Fase 1: Deduplica posiciones de barcos por ventana (unique_port_vessel_inventory).
Fase 2: Genera los JSON arrays agregados (port_inventory_summary).
Ambas fases usan TUMBLE windows sobre marcas de tiempo de tipo rowtime (TUMBLE_ROWTIME).
Esto asegura que todo el pipeline sea estrictamente INSERT-ONLY (append-only),
permitiendo la escritura directa en el Sink HTTP sin generar retractions ni updates. */

-- Fase 1: Deduplica barcos por ventana
CREATE TEMPORARY VIEW unique_port_vessel_inventory AS
SELECT 
    port_name,
    vessel_status,
    mmsi,
    length_m,
    ship_type,
    TUMBLE_START(`_event_time`, INTERVAL '{dedup_window}' MINUTE) AS window_start,
    TUMBLE_ROWTIME(`_event_time`, INTERVAL '{dedup_window}' MINUTE) AS window_rowtime
FROM port_vessel_inventory
GROUP BY port_name, vessel_status, mmsi, length_m, ship_type, TUMBLE(`_event_time`, INTERVAL '{dedup_window}' MINUTE);

-- Fase 2: Agrupa puertos y serializa a JSON
CREATE TEMPORARY VIEW port_inventory_summary AS
SELECT 
    port_name,
    TUMBLE_START(window_rowtime, INTERVAL '{dedup_window}' MINUTE) AS window_start,
    COUNT(DISTINCT CASE WHEN vessel_status IN ('ATRACADO', 'FONDEADO') THEN mmsi END) AS congested_count,
    JSON_ARRAYAGG(
        CASE WHEN vessel_status = 'ATRACADO' 
             THEN JSON_OBJECT(KEY 'mmsi' VALUE mmsi, KEY 'eslora' VALUE length_m, KEY 'tipo_buque' VALUE ship_type NULL ON NULL) 
        END ABSENT ON NULL
    ) AS atracados_json,
    JSON_ARRAYAGG(
        CASE WHEN vessel_status = 'FONDEADO' 
             THEN JSON_OBJECT(KEY 'mmsi' VALUE mmsi, KEY 'eslora' VALUE length_m, KEY 'tipo_buque' VALUE ship_type NULL ON NULL) 
        END ABSENT ON NULL
    ) AS fondeados_json,
    JSON_ARRAYAGG(
        CASE WHEN vessel_status = 'EN_CAMINO' 
             THEN JSON_OBJECT(KEY 'mmsi' VALUE mmsi, KEY 'eslora' VALUE length_m, KEY 'tipo_buque' VALUE ship_type NULL ON NULL) 
        END ABSENT ON NULL
    ) AS en_camino_json
FROM unique_port_vessel_inventory
GROUP BY port_name, TUMBLE(window_rowtime, INTERVAL '{dedup_window}' MINUTE);
