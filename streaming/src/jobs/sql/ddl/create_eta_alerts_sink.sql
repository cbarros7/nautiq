/* DDL: Crea la tabla Sink HTTP (Webhook) para enviar alertas de ETA. */
CREATE TABLE EtaAlertsHttpSink (
    `payload_json` STRING
) WITH (
    'connector' = 'http-sink',
    'url' = '{webhook_url}',
    'format' = 'raw',
    'insert-method' = 'POST',
    'gid.connector.http.sink.request.timeout' = '10',
    'gid.connector.http.sink.header.Content-Type' = 'application/json',
    'gid.connector.http.sink.header.X-Nautiq-Source' = 'Flink-ETA-Engine'{webhook_auth_header}
)
