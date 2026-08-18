/* INSERCIÓN: Envía datos estáticos válidos a la capa Bronze. */
INSERT INTO StaticBronze
SELECT 
    mmsi,
    imo,
    name,
    callsign,
    ship_type,
    length_m,
    beam_m,
    draught_m,
    destination,
    eta,
    _ingested_at,
    correlation_id,
    `_kafka_ingestion_time`,
    `_kafka_partition`,
    `_kafka_offset`,
    CAST(LOCALTIMESTAMP AS TIMESTAMP_LTZ(3)) AS `_flink_processing_time`,
    {schema_version} AS `_schema_version`,
    SUBSTRING(_ingested_at, 1, 10) AS `_dt`
FROM StaticKafka
WHERE
    ship_type BETWEEN {cargo_min} AND {cargo_max}
    AND ({port_filter})
