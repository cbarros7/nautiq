INSERT INTO PositionsBronze
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
    SUBSTRING(`timestamp`, 1, 10) AS `dt`
FROM enriched_positions
WHERE 
    (distance_nm / NULLIF(delta_hours, 0)) <= {spoofing_threshold}
    OR prev_lat IS NULL
    OR delta_hours <= 0
