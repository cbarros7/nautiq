CREATE TABLE {table_name} (
{columns_str}
) PARTITIONED BY (`dt`) WITH (
    'connector' = 'filesystem',
    'path' = '{sink_path}',
    'format' = 'parquet',
    'sink.partition-commit.policy.kind' = 'success-file',
    'auto-compaction' = 'true',
    'parquet.compression' = 'snappy'
)
