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

# --- Entorno (DEV / PRE / PRO) ---
# Determina el prefijo de los topics de Kafka cuando no se fija uno explícito con
# KAFKA_TOPIC_* (ver más abajo). Los topics reales en Aiven siguen el patrón
# "<prefijo>-vessel-*-raw" (p.ej. "dev-vessel-positions-raw"); cambiar NAUTIQ_ENV
# cambia a qué entorno apunta el servicio sin tocar ninguna otra variable.
# PRO es la única excepción al patrón NAUTIQ_ENV.lower(): los topics ya existentes en
# Aiven usan "prod-", no "pro-" (verificado contra el cluster, no es un typo).
NAUTIQ_ENV = os.getenv("NAUTIQ_ENV", "DEV").upper()
if NAUTIQ_ENV not in ("DEV", "PRE", "PRO"):
    raise ValueError(f"NAUTIQ_ENV={NAUTIQ_ENV!r} inválido; debe ser DEV, PRE o PRO.")
_TOPIC_ENV_PREFIX = {"DEV": "dev", "PRE": "pre", "PRO": "prod"}

# --- AISStream ---
# AISStream admite UNA conexión por key. La principal sirve `ShipStaticData`
# (descubrimiento continuo); la auxiliar, opcional, dedica una conexión propia al
# firehose de `PositionReport`. Sin la auxiliar ambos tipos comparten conexión.
AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY")
AISSTREAM_AUX_API_KEY = os.getenv("AISSTREAM_AUX_API_KEY")
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# --- Kafka (Aiven, SSL) ---
KAFKA_BROKER_URL = os.getenv("KAFKA_BROKER_URL")
KAFKA_CERTS = {
    "ca": os.getenv("KAFKA_SSL_CA_LOCATION", str(PROJECT_ROOT / ".certs" / "ca.pem")),
    "cert": os.getenv("KAFKA_SSL_CERT_LOCATION", str(PROJECT_ROOT / ".certs" / "service.cert")),
    "key": os.getenv("KAFKA_SSL_KEY_LOCATION", str(PROJECT_ROOT / ".certs" / "service.key")),
}

# Topics: uno por endpoint AIS. Por defecto se derivan de NAUTIQ_ENV; KAFKA_TOPIC_*
# los sobreescribe si algún entorno necesita un nombre que no siga el patrón.
# La DLQ NO deriva por defecto: es intencionalmente opcional (sin ella, el servicio
# corre sin DLQ en vez de fallar) — derivar un nombre siempre convertiría ese "sin
# configurar" en "apunta a un topic que quizá no existe todavía en ese entorno".
_env_prefix = _TOPIC_ENV_PREFIX[NAUTIQ_ENV]
TOPIC_POSITIONS = os.getenv("KAFKA_TOPIC_POSITIONS") or f"{_env_prefix}-vessel-positions-raw"
TOPIC_STATIC = os.getenv("KAFKA_TOPIC_STATIC") or f"{_env_prefix}-vessel-static-raw"
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
