/* DDL: Crea la tabla Sink para contratos rotos (Bronze DLQ). */
CREATE TABLE {table_name} (
    `raw_payload` STRING,
    `_kafka_ingestion_time` TIMESTAMP_LTZ(3),
    `_dt` STRING
) PARTITIONED BY (`_dt`) WITH (
    'connector' = 'filesystem',
    'path' = '{sink_path}',
    'format' = 'parquet',
    'sink.partition-commit.policy.kind' = 'success-file',
    'auto-compaction' = 'true',
    'parquet.compression' = 'snappy'
)
