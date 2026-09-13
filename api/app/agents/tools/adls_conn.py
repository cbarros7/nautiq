"""
Escritura de recomendaciones del oráculo a ADLS Gen2 (capa analítica,
consumida por Databricks).

Supabase (db_conn.oracle_recommendations_*) es la FUENTE DE VERDAD: sirve
al frontal y es lo que decide si un evento existe. Esto es la copia
analítica — se escribe DESPUÉS de que Supabase haya confirmado, nunca
antes, y su fallo no invalida la recomendación (ver
math_oracle.publicar_recomendacion).

Autenticación
-------------
SAS token sobre el endpoint blob del storage account. Nótese que el job
de Flink (streaming/src/jobs/config.py) usa account key + URLs
`abfss://` porque va por el conector Hadoop/Java; aquí, desde Python,
se usa el SDK de blob con SAS — apuntan al MISMO storage, sólo cambia
la vía de acceso.

Formato y particionado
----------------------
Un fichero JSON por evento, en `{entorno}/dt=YYYY-MM-DD/{event_id}.json`:

  - JSON (no Parquet) porque el evento ya ES un JSON anidado
    (route_weather, context_vessels...) y es el mismo payload que va al
    `jsonb` de Supabase: Bronze guarda el crudo tal cual llega. Escribir
    Parquet de una fila por evento obligaría a arrastrar pyarrow y a
    aplanar un esquema anidado, con el mismo problema de ficheros
    pequeños. Compactar a Parquet/Delta es trabajo de Silver en
    Databricks, no de la API.
  - `dt=YYYY-MM-DD` sigue la convención de particionado que ya usa el
    sink de Flink (`PARTITIONED BY (dt)` en create_table_sink.sql), así
    que Databricks puede hacer partition pruning igual que con Bronze.
  - El nombre del fichero es el `event_id` (ULID = correlation_id), así
    que reescribir el mismo evento sobrescribe en vez de duplicar:
    idempotente, igual que el `ON CONFLICT (event_id)` de Supabase.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

from app.config import ENV_SLUG, NAUTIQ_ENV

load_dotenv()

# Entorno: NAUTIQ_ENV se lee y valida una sola vez en app/config.py
# (DEV -> "dev", PRO -> "prod"), que es también quien decide la tabla de
# Supabase — así ambos destinos del mismo evento no pueden apuntar a
# entornos distintos por una validación duplicada que divergió.
ADLS_ACCOUNT = os.getenv("ADLS_ACCOUNT_NAME", "stnautiqdatadevswc")
ADLS_CONTAINER = os.getenv("ADLS_RECOMMENDATIONS_CONTAINER", "recommendations")
ADLS_SAS_TOKEN = os.getenv("ADLS_SAS_TOKEN")
# Carpeta raíz dentro del container; deriva del entorno salvo override
# explícito (útil si algún entorno necesita una ruta fuera del patrón).
ADLS_PREFIX = os.getenv("ADLS_RECOMMENDATIONS_PREFIX") or ENV_SLUG


def esta_configurado() -> bool:
    """
    True si hay SAS token configurado. Permite que el oráculo corra en
    local sin credenciales de Azure (se salta la copia analítica y lo
    registra) en vez de fallar.
    """
    return bool(ADLS_SAS_TOKEN)


def _get_container_client():
    if not ADLS_SAS_TOKEN:
        raise RuntimeError(
            "ADLS_SAS_TOKEN no configurado: no se puede escribir en ADLS. "
            "Usar esta_configurado() antes de llamar aquí."
        )
    service = BlobServiceClient(
        account_url=f"https://{ADLS_ACCOUNT}.blob.core.windows.net",
        credential=ADLS_SAS_TOKEN,
    )
    return service.get_container_client(ADLS_CONTAINER)


def construir_ruta(event_id: str, emitted_at: Optional[str] = None) -> str:
    """
    Ruta del blob dentro del container: `{prefijo}/dt=YYYY-MM-DD/{event_id}.json`.

    `emitted_at` (ISO-8601, el del propio evento) determina la partición
    para que el fichero caiga en el día del EVENTO, no en el día en que
    se escribió — si no se pasa, se usa "hoy" en UTC.
    """
    if emitted_at:
        dia = datetime.fromisoformat(emitted_at).astimezone(timezone.utc).date()
    else:
        dia = datetime.now(timezone.utc).date()
    return f"{ADLS_PREFIX}/dt={dia.isoformat()}/{event_id}.json"


def guardar_recomendacion(evento: dict) -> str:
    """
    Escribe el evento (oracle_recommendation_v1) en ADLS y devuelve la
    ruta del blob. Sobrescribe si ya existía ese event_id (idempotente).

    No captura excepciones a propósito: la política de "un fallo de la
    copia analítica no tumba la recomendación" se decide en el llamador
    (math_oracle.publicar_recomendacion), que es quien sabe si Supabase
    —la fuente de verdad— ya confirmó.
    """
    ruta = construir_ruta(evento["event_id"], evento.get("emitted_at"))
    contenido = json.dumps(evento, ensure_ascii=False).encode("utf-8")

    container = _get_container_client()
    container.upload_blob(
        name=ruta,
        data=contenido,
        overwrite=True,
        content_type="application/json",
    )
    return ruta


if __name__ == "__main__":
    print(f"NAUTIQ_ENV={NAUTIQ_ENV} -> prefijo {ADLS_PREFIX!r}")
    print(f"account={ADLS_ACCOUNT} container={ADLS_CONTAINER}")
    print(f"SAS token configurado: {esta_configurado()}")
    print("Ruta de ejemplo:", construir_ruta("01M08APDG115DX8X6KEKVXKHQE", "2026-08-21T09:00:00+00:00"))
