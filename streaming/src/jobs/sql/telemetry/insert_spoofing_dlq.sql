/* INSERCIÓN: Desvía anomalías (Spoofing) a la Dead Letter Queue. */
INSERT INTO SpoofingDLQ
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
    SUBSTRING(p.`timestamp`, 1, 10) AS `_dt`,
    p.prev_lat AS `_prev_lat`,
    p.prev_lon AS `_prev_lon`,
    p.prev_time AS `_prev_time`,
    p.distance_nm AS `_distance_nm`,
    p.delta_hours AS `_delta_hours`,
    (p.distance_nm / NULLIF(p.delta_hours, 0)) AS `_implied_speed_knots`,
    'GPS_SPOOFING_SPEED_EXCEEDED' AS `_anomaly_reason`,
    CAST({spoofing_threshold} AS DOUBLE) AS `_threshold_used`
FROM enriched_positions p
INNER JOIN StaticKafka s ON p.mmsi = s.mmsi
WHERE
    s.ship_type BETWEEN {cargo_min} AND {cargo_max}
    AND ({port_filter})
    AND (p.distance_nm / NULLIF(p.delta_hours, 0)) > {spoofing_threshold}
