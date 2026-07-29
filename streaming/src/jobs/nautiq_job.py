import os
from pyflink.table import StreamTableEnvironment
import config
from pipelines.telemetry import build_telemetry_pipeline
from pipelines.static_data import build_static_pipeline
from pipelines.contracts_dlq import build_contracts_dlq_pipeline

def main():
    """
    Nautiq JIT Streaming Job (Facade)
    Orquesta los pipelines paralelos de procesamiento continuo utilizando
    el patrón Facade para ocultar la complejidad de Apache Flink.
    """
    # 1. Setup del Entorno
    env = config.setup_environment()
    t_env = StreamTableEnvironment.create(env)
    stmt_set = t_env.create_statement_set()
    
    # 2. Configuración Compartida
    config_dict = {
        "KAFKA_BOOTSTRAP_SERVERS": config.KAFKA_BOOTSTRAP_SERVERS,
        "KAFKA_SECURITY_PROTOCOL": config.KAFKA_SECURITY_PROTOCOL,
        "KAFKA_SSL_CA_LOCATION": config.KAFKA_SSL_CA_LOCATION,
        "KAFKA_SSL_CERT_LOCATION": config.KAFKA_SSL_CERT_LOCATION,
        "KAFKA_SCHEMA_REGISTRY_URL": config.KAFKA_SCHEMA_REGISTRY_URL,
        "KAFKA_SCHEMA_REGISTRY_AUTH": config.KAFKA_SCHEMA_REGISTRY_AUTH
    }

    # 3. Ensamblaje de Pipelines (Modular)
    build_telemetry_pipeline(t_env, stmt_set, config_dict)
    build_static_pipeline(t_env, stmt_set, config_dict)
    # build_contracts_dlq_pipeline(t_env, stmt_set, config_dict)
    
    # 4. Ejecución Asíncrona (DAG execution)
    print("Iniciando Nautiq JIT Streaming Job")
    table_result = stmt_set.execute()
    table_result.wait()

if __name__ == '__main__':
    main()
