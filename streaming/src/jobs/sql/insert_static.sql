INSERT INTO StaticBronze
SELECT *,
    CAST(LOCALTIMESTAMP AS TIMESTAMP_LTZ(3)) AS `flink_processing_time`,
    {schema_version} AS `schema_version`,
    SUBSTRING(CAST(LOCALTIMESTAMP AS STRING), 1, 10) AS `dt`
FROM StaticKafka
