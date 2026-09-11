/* DDL: Crea la tabla de origen conectada a Kafka. */
CREATE TABLE {table_name} (
{columns_str}
) WITH (
    'connector' = 'kafka',
    'topic' = '{topic_name}',
    'properties.bootstrap.servers' = '{kafka_bootstrap_servers}',
    'properties.group.id' = '{kafka_group_id}',
    'properties.enable.auto.commit' = 'true',
    'properties.security.protocol' = '{kafka_security_protocol}',
    'properties.ssl.truststore.type' = 'PEM',
    'properties.ssl.truststore.location' = '{kafka_ssl_ca_location}',
    'properties.ssl.keystore.type' = 'PEM',
    'properties.ssl.keystore.location' = '{kafka_ssl_cert_location}',
    'scan.startup.mode' = 'group-offsets',
    'scan.watermark.idle-timeout' = '10000',
    'properties.auto.offset.reset' = 'earliest',
    'format' = 'avro-confluent',
    'avro-confluent.url' = '{kafka_schema_registry_url}',
    'avro-confluent.basic-auth.credentials-source' = 'USER_INFO',
    'avro-confluent.basic-auth.user-info' = '{kafka_schema_registry_auth}'
)
