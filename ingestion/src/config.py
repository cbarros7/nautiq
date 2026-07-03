"""
Configuración de Ingestion por entorno (Zero Trust: secretos fuera del código).

En producción los secretos vienen de Azure Key Vault / OCI Vault; en local del
`.env`. Este módulo NO conecta a nada: solo expone la configuración.
"""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# Raíz del repo: src -> ingestion -> nautiq
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# --- AISStream ---
AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY")
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# --- Kafka (Aiven, SSL) ---
KAFKA_BROKER_URL = os.getenv("KAFKA_BROKER_URL")
KAFKA_CERTS = {
    "ca": os.getenv("KAFKA_SSL_CA_LOCATION", str(PROJECT_ROOT / ".certs" / "ca.pem")),
    "cert": os.getenv("KAFKA_SSL_CERT_LOCATION", str(PROJECT_ROOT / ".certs" / "service.cert")),
    "key": os.getenv("KAFKA_SSL_KEY_LOCATION", str(PROJECT_ROOT / ".certs" / "service.key")),
}

# Topics: uno por endpoint AIS. OBLIGATORIOS vía entorno (sin valor por defecto).
TOPIC_POSITIONS = os.getenv("KAFKA_TOPIC_POSITIONS")
TOPIC_STATIC = os.getenv("KAFKA_TOPIC_STATIC")
TOPIC_DLQ = os.getenv("KAFKA_TOPIC_DLQ")

# --- Schema Registry: Aiven (Karapace) ---
# URI del servicio Karapace de Aiven (puerto aparte del broker) + auth básica avnadmin.
SCHEMA_REGISTRY_URL = os.getenv("KAFKA_SCHEMA_REGISTRY_URL")
SCHEMA_REGISTRY_AUTH = os.getenv("KAFKA_SCHEMA_REGISTRY_AUTH")  # 'avnadmin:password'

# --- PostgreSQL (Supabase, capa de referencia) — psycopg con variables discretas ---
PG_DSN = {
    "host": os.getenv("PGHOST"),
    "port": os.getenv("PGPORT", "5432"),
    "dbname": os.getenv("PGDATABASE", "postgres"),
    "user": os.getenv("PGUSER"),
    "password": os.getenv("PGPASSWORD"),
    "sslmode": os.getenv("PGSSLMODE", "require"),
}
