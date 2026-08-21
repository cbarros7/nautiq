import os
import config
import schema_utils
from pyflink.table import StreamTableEnvironment, StatementSet

def build_static_pipeline(t_env: StreamTableEnvironment, stmt_set: StatementSet, config_dict: dict):
    """
    Construye el pipeline para los datos estáticos del buque (dimensiones, etc).
    """
    # 1. Registrar DDL de origen
    static_kafka_ddl, static_schema_version = schema_utils.generate_ddl_from_registry(
        config.KAFKA_TOPIC_STATIC, "StaticKafka", config_dict, is_sink=False
    )
    t_env.execute_sql(static_kafka_ddl)

    # 2. Registrar DDL de destino (Bronze Parquet)
    adls_static_path = f"{config.ADLS_BRONZE_URL}/static"
    static_adls_ddl, _ = schema_utils.generate_ddl_from_registry(
        config.KAFKA_TOPIC_STATIC, "StaticBronze", config_dict, is_sink=True, sink_path=adls_static_path
    )
    t_env.execute_sql(static_adls_ddl)
    
    # 3. Pipeline hacia Bronze
    sql_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")
    static_insert_sql_template = schema_utils.read_sql_file(os.path.join(sql_dir, "insert_static.sql"))
    static_insert_sql = static_insert_sql_template.format(schema_version=static_schema_version)
    
    stmt_set.add_insert_sql(static_insert_sql)
