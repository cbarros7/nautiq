/* INSERCIÓN: Filtra y envía posiciones VÁLIDAS a la capa Bronze. */
INSERT INTO PositionsBronze
SELECT
    p.mmsi,
    p.`timestamp`,
    p.lat,
    p.lon,
    p.speed,
    p.cog,
    p.heading,
    p.nav_status,
    p._ingested_at,
    p.correlation_id,
    p.`_kafka_ingestion_time`,
    p.`_kafka_partition`,
    p.`_kafka_offset`,
    CAST(LOCALTIMESTAMP AS TIMESTAMP_LTZ(3)) AS `_flink_processing_time`,
    {schema_version} AS `_schema_version`,
    SUBSTRING(p.`timestamp`, 1, 10) AS `_dt`
FROM enriched_positions p
INNER JOIN StaticKafka s ON p.mmsi = s.mmsi
WHERE
    s.ship_type BETWEEN {cargo_min} AND {cargo_max}
    AND ({port_filter})
    AND (
        (p.distance_nm / NULLIF(p.delta_hours, 0)) <= {spoofing_threshold}
        OR p.prev_lat IS NULL
        OR p.delta_hours <= 0
    )
