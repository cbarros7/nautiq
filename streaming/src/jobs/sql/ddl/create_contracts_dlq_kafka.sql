/* DDL: Crea la tabla origen para contratos rotos (Kafka DLQ). */
CREATE TABLE {table_name} (
    `raw_payload` STRING,
    `_kafka_ingestion_time` TIMESTAMP_LTZ(3) METADATA FROM 'timestamp'
) WITH (
    'connector' = 'kafka',
    'topic' = '{topic_name}',
    'properties.bootstrap.servers' = '{kafka_bootstrap_servers}',
    'properties.group.id' = '{kafka_group_id}',
    'properties.security.protocol' = '{kafka_security_protocol}',
    'properties.ssl.truststore.type' = 'PEM',
    'properties.ssl.truststore.location' = '{kafka_ssl_ca_location}',
    'properties.ssl.keystore.type' = 'PEM',
    'properties.ssl.keystore.location' = '{kafka_ssl_cert_location}',
    'scan.startup.mode' = 'group-offsets',
    'properties.auto.offset.reset' = 'earliest',
    'format' = 'raw'
)
