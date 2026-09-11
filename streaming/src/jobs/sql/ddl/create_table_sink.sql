/* DDL: Crea la tabla de destino (Sink) genérica para Parquet en ADLS. */
CREATE TABLE {table_name} (
{columns_str}
) PARTITIONED BY (`_dt`) WITH (
    'connector' = 'filesystem',
    'path' = '{sink_path}',
    'format' = 'parquet',
    'sink.partition-commit.trigger' = 'process-time',
    'sink.partition-commit.delay' = '0s',
    'sink.partition-commit.policy.kind' = 'success-file',
    'auto-compaction' = 'true',
    'parquet.compression' = 'snappy'
)
