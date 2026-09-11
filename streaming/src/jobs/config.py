"""
Módulo: config.py
Propósito: Centraliza toda la configuración del entorno, variables de entorno, y umbrales de negocio (constantes).
Patrón: Configuration Registry / Singleton (implícito por el módulo).
Decisión de diseño: Se evita hardcodear valores en el código para permitir que DevOps/FinOps inyecten variables según el entorno (dev/prod).
Datos consumidos: Lee el archivo .env o variables del sistema (OS ENV).
"""
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

# FastAPI / Azure Function Webhook
FASTAPI_WEBHOOK_URL = os.getenv("ETA_ALERTS_WEBHOOK_URL") or os.getenv("FASTAPI_WEBHOOK_URL")
FASTAPI_WEBHOOK_KEY = os.getenv("ETA_ALERTS_WEBHOOK_KEY") or os.getenv("FASTAPI_WEBHOOK_KEY", "")

# Tópicos fuente y DLQ
_nautiq_env = os.getenv("NAUTIQ_ENV", "dev").lower()
_topic_prefix = "prod" if _nautiq_env in ("pro", "prod") else "dev"

KAFKA_TOPIC_POSITIONS = os.getenv("KAFKA_TOPIC_POSITIONS") or f"{_topic_prefix}-vessel-positions-raw"
KAFKA_TOPIC_STATIC = os.getenv("KAFKA_TOPIC_STATIC") or f"{_topic_prefix}-vessel-static-raw"
KAFKA_TOPIC_DLQ = os.getenv("KAFKA_TOPIC_DLQ")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", f"flink-ais-consumer-{_topic_prefix}")

# --------------------------------------------------------------------------
# Lógica de Negocio: Detección de Spoofing
# --------------------------------------------------------------------------
SPOOFING_SPEED_THRESHOLD_KNOTS = int(os.getenv("SPOOFING_SPEED_THRESHOLD_KNOTS", "50"))

# --------------------------------------------------------------------------
# Lógica de Negocio: Filtrado de Buques y Puertos Objetivo
# --------------------------------------------------------------------------
# Tipos de buque AIS que nos interesan (IMO categoría Cargo Vessels).
CARGO_SHIP_TYPE_MIN = 70
CARGO_SHIP_TYPE_MAX = 79

# Registro de puertos objetivo. El campo AIS `destination` es texto libre
# escrito por el capitán, por lo que puede venir en múltiples formatos.
# Para añadir un nuevo puerto, añade un dict a esta lista con el nombre
# canónico y todos los alias que quieras detectar (siempre en MAYÚSCULAS).
# La función `schema_utils.build_port_filter_sql()` transforma este
# registro en un predicado SQL WHERE dinámicamente.
TARGET_PORTS = [
    {
        "name": "VALENCIA",
        "aliases": ["VALENCIA", "VLC", "VLNCIA", "ES VAL", "VALE"],
        "lat": 39.4457,
        "lon": -0.3198,
        "congestion_radius_nm": 5.0
    },
    {
        "name": "ALGECIRAS",
        "aliases": ["ALGECIRAS", "ALGEC", "ALG", "ES ALG", "ALGE"],
        "lat": 36.12972,
        "lon": -5.42278,
        "congestion_radius_nm": 5.0
    },
    {
        "name": "BARCELONA",
        "aliases": ["BARCELONA", "BCN", "BARNA", "ES BCN", "BARCEL", "BARCN"],
        "lat": 41.338,
        "lon": 2.1675,
        "congestion_radius_nm": 5.0
    },
]

# ---- Reglas de Negocio ETA & Alertas ----
ETA_ALERT_HORIZON_HOURS = int(os.getenv("ETA_ALERT_HORIZON_HOURS", "48"))        # Disparar alerta si ETA dinámico < N horas (Dev: 48 a 72 horas). (Prod: 12 a 24 horas)
CONGESTION_VESSEL_THRESHOLD = int(os.getenv("CONGESTION_VESSEL_THRESHOLD", "1")) # Mínimo de buques en puerto para considerar "congestión" (Dev: 1 para pruebas). (Prod: 3 a 5 pruebas)
ALERT_DEDUP_WINDOW_MINUTES = int(os.getenv("ALERT_DEDUP_WINDOW_MINUTES", "1"))     # Ventana de deduplicación por buque (Dev: 1 a 5 para pruebas). (Prod: 30 a 60 minutos)
EN_CAMINO_MAX_ETA_HOURS = int(os.getenv("EN_CAMINO_MAX_ETA_HOURS", "72"))        # Filtro de distancia temporal para buques "en camino" (Dev: 48 a 72 horas). (Prod: 48 a 72 horas)

# ---- Configuración de Flink ----
FLINK_PARALLELISM = int(os.getenv("FLINK_PARALLELISM", "2"))               # Número de hilos paralelos (Task Slots)

# ---- Configuración del Orquestador (External Orchestrator Pattern) ----
# ADLS_SAVEPOINTS_URL: Ruta centralizada para almacenar los Savepoints en Azure ADLS.
ADLS_SAVEPOINTS_URL = f"abfss://checkpoints@{AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net/flink_savepoints"
# FLINK_ENV: Entorno de despliegue (dev/prod).
FLINK_ENV = os.getenv("FLINK_ENV") or os.getenv("NAUTIQ_ENV") or "dev"
# FLINK_FORCE_COLD_START: Bandera de emergencia para ignorar Savepoints y reconstruir la memoria desde cero.
FLINK_FORCE_COLD_START = os.getenv("FLINK_FORCE_COLD_START", "false").lower() == "true"
# FLINK_IGNORE_UNCLAIMED_STATE: Bandera para permitir cambios menores (como quitar un JOIN) sin corromper el arranque.
FLINK_IGNORE_UNCLAIMED_STATE = os.getenv("FLINK_IGNORE_UNCLAIMED_STATE", "true").lower() == "true"
# FLINK_FORCE_UNLOCK: Bandera de emergencia para forzar la eliminación de locks obsoletos en ADLS.
FLINK_FORCE_UNLOCK = os.getenv("FLINK_FORCE_UNLOCK", "false").lower() == "true"

def setup_environment() -> StreamExecutionEnvironment:
    """Configura el entorno de ejecución de Flink con Checkpoints y State RocksDB."""
    conf = Configuration()
    # Establecemos State TTL de 30 días para equilibrar retención a largo plazo de la dimensión
    # de buques (Static) y evitar el problema de reciclaje de MMSIs de buques desguazados.
    conf.set_string("table.exec.state.ttl", "30 d")
    # Ignorar subtasks ociosas en el cálculo de Watermarks (esencial si Paralelismo > Particiones de Kafka)
    conf.set_string("table.exec.source.idle-timeout", "5 s")
    # Usar RocksDB como State Backend para almacenar el estado del JOIN fuera del JVM Heap
    conf.set_string("state.backend", "rocksdb")
    env = StreamExecutionEnvironment.get_execution_environment(conf)
    env.set_parallelism(FLINK_PARALLELISM)
    
    # Configuración del Checkpointing
    env.enable_checkpointing(300000, CheckpointingMode.EXACTLY_ONCE)
    checkpoint_config = env.get_checkpoint_config()
    
    # Evitar acumulación y timeouts en disco/red
    checkpoint_config.set_max_concurrent_checkpoints(1)
    checkpoint_config.set_min_pause_between_checkpoints(30000)
    checkpoint_config.set_checkpoint_timeout(120000)
    
    checkpoint_config.set_externalized_checkpoint_cleanup(
        ExternalizedCheckpointCleanup.RETAIN_ON_CANCELLATION
    )
    # Checkpoints seguros en ADLS para sobrevivir a pérdida de la VM
    checkpoint_config.set_checkpoint_storage_dir(
        f"abfss://checkpoints@{AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net/flink_checkpoints"
    )

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
