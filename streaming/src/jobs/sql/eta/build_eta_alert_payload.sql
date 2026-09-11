/* INSERT DIRECTO: Construye el JSON final (Paquete 1 y 2) y lo envía al sink HTTP.
NOTA CRÍTICA: Deduplicamos las alertas por ventana y barco usando una agregación de ventana
TUMBLE con FIRST_VALUE, lo que mantiene todo el pipeline estrictamente INSERT-ONLY (append-only). */
INSERT INTO EtaAlertsHttpSink
SELECT payload_json FROM (
    WITH eta_candidates AS (
        SELECT 
            mmsi,
            TUMBLE_START(`_event_time`, INTERVAL '{dedup_window}' MINUTE) AS window_start,
            FIRST_VALUE(correlation_id) AS correlation_id,
            FIRST_VALUE(imo) AS imo,
            FIRST_VALUE(destination_port) AS destination_port,
            FIRST_VALUE(nav_status) AS nav_status,
            FIRST_VALUE(lon) AS lon,
            FIRST_VALUE(lat) AS lat,
            FIRST_VALUE(cog) AS cog,
            FIRST_VALUE(speed) AS speed,
            FIRST_VALUE(length_m) AS length_m,
            FIRST_VALUE(beam_m) AS beam_m,
            FIRST_VALUE(draught_m) AS draught_m,
            FIRST_VALUE(ship_type) AS ship_type,
            FIRST_VALUE(_eta_dynamic_hours) AS _eta_dynamic_hours,
            FIRST_VALUE(eta_static_raw) AS eta_static_raw
        FROM eta_dynamic
        GROUP BY mmsi, TUMBLE(`_event_time`, INTERVAL '{dedup_window}' MINUTE)
    )
    SELECT 
        JSON_OBJECT(
            KEY 'paquete_1' VALUE JSON_OBJECT(
                KEY 'mmsi' VALUE c.mmsi,
                KEY 'correlation_id' VALUE c.correlation_id,
                KEY 'imo' VALUE c.imo,
                KEY 'puerto' VALUE c.destination_port,
                KEY 'estado' VALUE c.nav_status,
                KEY 'longitud' VALUE c.lon,
                KEY 'latitud' VALUE c.lat,
                KEY 'direccion' VALUE c.cog,
                KEY 'velocidad_buque' VALUE c.speed,
                KEY 'eslora' VALUE c.length_m,
                KEY 'manga' VALUE c.beam_m,
                KEY 'calado_de_diseno' VALUE c.draught_m,
                KEY 'tipo_buque' VALUE c.ship_type,
                KEY 'ETA' VALUE CAST(c._eta_dynamic_hours AS DOUBLE),
                KEY 'ETA_static' VALUE c.eta_static_raw
                NULL ON NULL
            ),
            KEY 'paquete_2' VALUE JSON_OBJECT(
                KEY 'puerto' VALUE c.destination_port,
                KEY 'estados' VALUE JSON_OBJECT(
                    KEY 'num_buques_atracados' VALUE COALESCE(pis.atracados_json, JSON_ARRAY()),
                    KEY 'num_buques_fondeados' VALUE COALESCE(pis.fondeados_json, JSON_ARRAY()),
                    KEY 'num_buques_en_camino' VALUE COALESCE(pis.en_camino_json, JSON_ARRAY())
                    NULL ON NULL
                )
                NULL ON NULL
            )
            NULL ON NULL
        ) AS payload_json
    FROM eta_candidates c
    INNER JOIN port_inventory_summary pis 
        ON c.destination_port = pis.port_name 
        AND c.window_start = pis.window_start
    -- Solo recibiremos l alerta si 
    -- (1) el puerto al que se dirige el buque ya muestra indicios de ocupación Y
    --(2) el buque está a punto de llegar (en menos de X horas). 
    WHERE pis.congested_count >= {congestion_threshold} -- Verifica el estado actual del puerto de destino
      AND c._eta_dynamic_hours <= {eta_alert_horizon} -- Evalúa la urgencia del barco que se está aproximando.
)
