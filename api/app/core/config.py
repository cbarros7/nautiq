"""
Configuración centralizada de la API (Zero Trust: secretos fuera del código).

En producción los secretos vienen de Azure Key Vault (Managed Identity); en local
del `.env`. Este módulo solo expone la configuración, no conecta a nada.
"""

import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# PostgreSQL directo (checkpoints LangGraph, operaciones con DDL) — variables discretas.
PG_DSN = {
    "host": os.getenv("PGHOST"),
    "port": os.getenv("PGPORT", "5432"),
    "dbname": os.getenv("PGDATABASE", "postgres"),
    "user": os.getenv("PGUSER"),
    "password": os.getenv("PGPASSWORD"),
    "sslmode": os.getenv("PGSSLMODE", "require"),
}
