"""
Módulo: static_data.py
Propósito: Construye el pipeline para mover los datos estáticos del buque (dimensiones, destino, etc.) al Data Lake.
Patrón: Data Ingestion / Filtering.
Decisión de diseño: Realiza filtrado temprano en el motor de streaming (por tipo de buque y puertos objetivo)
                    para evitar saturar el Data Lake con buques irrelevantes (ej: veleros, pesqueros).
Datos consumidos: Lee de 'StaticKafka' y escribe en 'StaticBronze'.
"""
import os
import config
import schema_utils
from pyflink.table import StreamTableEnvironment, StatementSet


def build_static_pipeline(t_env: StreamTableEnvironment, stmt_set: StatementSet, config_dict: dict):
    """
    Construye el pipeline para los datos estáticos del buque (dimensiones, destino, etc.).

    Filtra en origen: solo los buques de carga (ship_type 70-79) con destino
    en los puertos objetivo configurados en config.TARGET_PORTS llegan a StaticBronze.

    PRECONDICIÓN: StaticKafka debe estar registrado en t_env antes de llamar
    a este pipeline (lo registra nautiq_job.py en el paso de shared setup).
    """
    sql_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")
    port_filter = schema_utils.build_port_filter_sql(config.TARGET_PORTS)

    # 1. DDL de Destino (Bronze Parquet en ADLS)
    adls_static_path = f"{config.ADLS_BRONZE_URL}/static"
    static_adls_ddl, static_schema_version = schema_utils.generate_ddl_from_registry(
        config.KAFKA_TOPIC_STATIC, "StaticBronze", config_dict, is_sink=True, sink_path=adls_static_path
    )
    t_env.execute_sql(static_adls_ddl)

    # 2. INSERT hacia Bronze (solo buques de carga con destino en puertos objetivo)
    static_insert_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "static", "insert_static.sql")).format(
        schema_version=static_schema_version,
        cargo_min=config.CARGO_SHIP_TYPE_MIN,
        cargo_max=config.CARGO_SHIP_TYPE_MAX,
        port_filter=port_filter
    )

    stmt_set.add_insert_sql(static_insert_sql)
