import os
from dotenv import load_dotenv, find_dotenv

# Cargar variables de entorno desde el .env más cercano (buscando hacia arriba)
load_dotenv(find_dotenv())

# CONFIGURACIÓN DEL MOTOR DE STREAMING (FLINK)

# Conexión al bus de eventos Kafka
KAFKA_BROKER_URL = os.getenv("KAFKA_BROKER_URL")

# Entorno actual (ej: "local", "dev", "prod")
APP_ENV = os.getenv("APP_ENV", "dev").lower()
# Normalizamos 'local' a 'dev' para la convención de los tópicos
ENV_PREFIX = "dev" if APP_ENV == "local" else APP_ENV

# Tópicos dinámicos según el ambiente
KAFKA_TOPIC_SOURCE = (
    f"{ENV_PREFIX}_bronze.ais.telemetry"  # ej: dev_bronze.ais.telemetry
)
KAFKA_TOPIC_SINK = f"{ENV_PREFIX}_silver.ais.alerts"  # ej: dev_silver.ais.alerts

# TODO (Data Engineer): Si Flink requiere conectarse por SSL a Aiven Kafka,
# deberás configurar aquí las rutas a los certificados (similar a Ingestion)
# o integrarlas directamente en las propiedades del KafkaSource/KafkaSink.
