INSERT INTO ContractsDlqBronze
SELECT 
    raw_payload,
    kafka_ingestion_time,
    SUBSTRING(CAST(kafka_ingestion_time AS STRING), 1, 10) AS `dt`
FROM ContractsDlqKafka
