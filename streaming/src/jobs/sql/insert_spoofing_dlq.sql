INSERT INTO SpoofingDLQ
SELECT
    mmsi,
    `timestamp`,
    lat,
    lon,
    speed,
    cog,
    heading,
    nav_status,
    kafka_ingestion_time,
    kafka_partition,
    kafka_offset,
    CAST(LOCALTIMESTAMP AS TIMESTAMP_LTZ(3)) AS `flink_processing_time`,
    {schema_version} AS `schema_version`,
    SUBSTRING(`timestamp`, 1, 10) AS `dt`,
    prev_lat,
    prev_lon,
    prev_time,
    distance_nm,
    delta_hours,
    (distance_nm / NULLIF(delta_hours, 0)) AS implied_speed_knots,
    'GPS_SPOOFING_SPEED_EXCEEDED' AS anomaly_reason,
    CAST({spoofing_threshold} AS DOUBLE) AS threshold_used
FROM enriched_positions
WHERE 
    (distance_nm / NULLIF(delta_hours, 0)) > {spoofing_threshold}
