"""
Módulo: nautiq_job.py
Propósito: Archivo principal (Main) que orquesta el Job Graph completo de Flink.
Patrón: Facade (Fachada) / Orchestrator. 
Decisión de diseño: Se usa para ocultar la complejidad de inicialización de entornos, checkpoints y registro
                    de vistas compartidas, inyectando dependencias hacia pipelines modulares.
Datos consumidos: Lee configuraciones globales, y registra el topic 'StaticKafka' (compartido).
"""
import os
import logging
import subprocess
import tempfile
from pyflink.table import StreamTableEnvironment
import config
import schema_utils
from pipelines.telemetry import build_telemetry_pipeline
from pipelines.static_data import build_static_pipeline
from pipelines.contracts_dlq import build_contracts_dlq_pipeline
from pipelines.eta_alerts import build_eta_alerts_pipeline

logger = logging.getLogger("nautiq.job")

def _write_active_job_id(job_id: str):
    """Persiste el Job ID en ADLS usando comandos nativos de Hadoop para el orquestador."""
    state_file_path = f"{config.ADLS_SAVEPOINTS_URL}/.active_job_id"
    subprocess.run(["hadoop", "fs", "-mkdir", "-p", config.ADLS_SAVEPOINTS_URL], capture_output=True)
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write(job_id)
        tmp_name = f.name
    try:
        subprocess.run(["hadoop", "fs", "-put", "-f", tmp_name, state_file_path], check=True)
        logger.info(f"Job ID persistido en ADLS - path={state_file_path}")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Error al persistir Job ID en ADLS - error={e}")
    finally:
        os.remove(tmp_name)

def main():
    """
    Nautiq JIT Streaming Job (Facade)
    Orquesta los pipelines paralelos de procesamiento continuo utilizando
    el patrón Facade para ocultar la complejidad de Apache Flink.

    Orden de registro (crítico para el plan de ejecución de Flink):
      1. Shared Setup: DDLs fuente compartidos por múltiples pipelines.
      2. Telemetry Pipeline: Posiciones, enriquecimiento, Spoofing DLQ.
      3. Static Pipeline: Datos estáticos del buque.
      4. ETA Alerts Pipeline: Webhooks de alertas de ETA.
    """
    # 1. Setup del Entorno
    env = config.setup_environment()
    t_env = StreamTableEnvironment.create(env)
    stmt_set = t_env.create_statement_set()

    # 2. Configuración Compartida
    config_dict = {
        "KAFKA_BOOTSTRAP_SERVERS": config.KAFKA_BOOTSTRAP_SERVERS,
        "KAFKA_GROUP_ID": config.KAFKA_GROUP_ID,
        "KAFKA_SECURITY_PROTOCOL": config.KAFKA_SECURITY_PROTOCOL,
        "KAFKA_SSL_CA_LOCATION": config.KAFKA_SSL_CA_LOCATION,
        "KAFKA_SSL_CERT_LOCATION": config.KAFKA_SSL_CERT_LOCATION,
        "KAFKA_SCHEMA_REGISTRY_URL": config.KAFKA_SCHEMA_REGISTRY_URL,
        "KAFKA_SCHEMA_REGISTRY_AUTH": config.KAFKA_SCHEMA_REGISTRY_AUTH
    }

    # 3. Shared Setup: StaticKafka se registra UNA SOLA VEZ aquí porque es
    # referenciado por ambos pipelines (telemetry hace JOIN, static escribe desde él).
    static_kafka_ddl, _ = schema_utils.generate_ddl_from_registry(
        config.KAFKA_TOPIC_STATIC, "StaticKafka", config_dict, is_sink=False
    )
    t_env.execute_sql(static_kafka_ddl)

    # 4. Ensamblaje de Pipelines (Modular)
    build_telemetry_pipeline(t_env, stmt_set, config_dict)
    build_static_pipeline(t_env, stmt_set, config_dict)
    build_contracts_dlq_pipeline(t_env, stmt_set, config_dict)
    build_eta_alerts_pipeline(t_env, stmt_set, config_dict)

    logger.info("Enviando grafo de ejecucion al cluster de Flink...")
    table_result = stmt_set.execute()
    job_client = table_result.get_job_client()
    
    if job_client is not None:
        job_id = str(job_client.get_job_id())
        logger.info(f"Job enviado exitosamente al cluster - job_id={job_id}")
        _write_active_job_id(job_id)
        # El script termina aquí. El job queda corriendo de forma asíncrona (Unbounded)
    else:
        logger.error("No se pudo obtener el cliente del Job.")
        raise RuntimeError("Fallo al enviar el Job a Flink")


if __name__ == '__main__':
    main()
