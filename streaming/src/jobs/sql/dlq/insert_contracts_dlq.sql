/* INSERCIÓN: Redirige mensajes no parseables de Kafka a la DLQ en ADLS. */
INSERT INTO ContractsDlqBronze
SELECT 
    raw_payload,
    _kafka_ingestion_time,
    SUBSTRING(CAST(_kafka_ingestion_time AS STRING), 1, 10) AS `_dt`
FROM ContractsDlqKafka
