CREATE TABLE {table_name} (
    `raw_payload` STRING,
    `kafka_ingestion_time` TIMESTAMP_LTZ(3),
    `dt` STRING
) PARTITIONED BY (`dt`) WITH (
    'connector' = 'filesystem',
    'path' = '{sink_path}',
    'format' = 'parquet',
    'sink.partition-commit.policy.kind' = 'success-file',
    'auto-compaction' = 'true',
    'parquet.compression' = 'snappy'
)
