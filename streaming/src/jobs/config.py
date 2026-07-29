import os
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.checkpointing_mode import CheckpointingMode
from pyflink.datastream.checkpoint_config import ExternalizedCheckpointCleanup
from pyflink.common import Configuration
from dotenv import load_dotenv, find_dotenv

# Cargar variables de entorno
load_dotenv(find_dotenv())

# Kafka (Aiven) Config
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BROKER_URL")
KAFKA_SECURITY_PROTOCOL = "SSL"
# Rutas locales dentro del contenedor (montado desde ../.certs)
KAFKA_SSL_CA_LOCATION = "/opt/flink/certs/ca.pem"
KAFKA_SSL_CERT_LOCATION = "/opt/flink/certs/service_full.pem"

# Schema Registry Config
KAFKA_SCHEMA_REGISTRY_URL = os.getenv("KAFKA_SCHEMA_REGISTRY_URL")
KAFKA_SCHEMA_REGISTRY_AUTH = os.getenv("KAFKA_SCHEMA_REGISTRY_AUTH")

# Azure ADLS Gen 2 Config
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
AZURE_STORAGE_KEY = os.getenv("AZURE_STORAGE_KEY")
# La URL de Bronze será abfss://bronze@<account>.dfs.core.windows.net/telemetry
ADLS_BRONZE_URL = f"abfss://bronze@{AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net/telemetry"
ADLS_DLQ_SPOOFING_URL = f"abfss://bronze@{AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net/dlq/spoofing"
ADLS_DLQ_CONTRACTS_URL = f"abfss://bronze@{AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net/dlq/contracts"

# FastAPI Webhook
FASTAPI_WEBHOOK_URL = os.getenv("FASTAPI_WEBHOOK_URL")

# Tópicos fuente y DLQ
KAFKA_TOPIC_POSITIONS = os.getenv("KAFKA_TOPIC_POSITIONS", "dev-vessel-positions-raw")
KAFKA_TOPIC_STATIC = os.getenv("KAFKA_TOPIC_STATIC", "dev-vessel-static-raw")
KAFKA_TOPIC_DLQ = os.getenv("KAFKA_TOPIC_DLQ", "dev-vessel-contracts-dlq")

# Lógica de Negocio
SPOOFING_SPEED_THRESHOLD_KNOTS = int(os.getenv("SPOOFING_SPEED_THRESHOLD_KNOTS", "50"))

def setup_environment() -> StreamExecutionEnvironment:
    """Configura el entorno de ejecución de Flink con Checkpoints y State TTL."""
    conf = Configuration()
    # 24 horas de State TTL para evitar fugas de memoria de MMSIs inactivos
    conf.set_string("table.exec.state.ttl", "24 h")
    env = StreamExecutionEnvironment.get_execution_environment(conf)
    
    # Configuración del State Backend (File System) y Checkpointing
    env.enable_checkpointing(300000, CheckpointingMode.EXACTLY_ONCE)
    checkpoint_config = env.get_checkpoint_config()
    checkpoint_config.set_externalized_checkpoint_cleanup(
        ExternalizedCheckpointCleanup.RETAIN_ON_CANCELLATION
    )
    checkpoint_config.set_checkpoint_storage_dir("file:///opt/flink/checkpoints")

    return env

def get_kafka_properties() -> dict:
    """Retorna las propiedades de conexión a Kafka usando SSL."""
    props = {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "group.id": "flink-ais-consumer",
        "security.protocol": KAFKA_SECURITY_PROTOCOL,
        # Configuración de SSL en Flink/Java usando archivos PEM (soportado desde Kafka 3.0+)
        "ssl.truststore.type": "PEM",
        "ssl.truststore.location": KAFKA_SSL_CA_LOCATION,
        "ssl.keystore.type": "PEM",
        "ssl.keystore.location": KAFKA_SSL_CERT_LOCATION,
        # Dependemos de Flink Checkpoints para comitear los offsets
        "enable.auto.commit": "false"
    }
    return props
