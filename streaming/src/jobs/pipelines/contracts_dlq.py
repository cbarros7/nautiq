import os
import config
import schema_utils
from pyflink.table import StreamTableEnvironment, StatementSet

def build_contracts_dlq_pipeline(t_env: StreamTableEnvironment, stmt_set: StatementSet, config_dict: dict):
    """
    Construye el pipeline para el DLQ de contratos rotos (esquemas JSON/Avro inválidos).
    Lee la carga útil raw opaca y la persiste para su posterior análisis.
    """
    if not config.KAFKA_TOPIC_DLQ:
        return
        
    # 1. Registrar DDL de origen (Formato raw)
    contracts_kafka_ddl = schema_utils.generate_contracts_dlq_ddl(
        config.KAFKA_TOPIC_DLQ, "ContractsDlqKafka", config_dict, is_sink=False
    )
    t_env.execute_sql(contracts_kafka_ddl)
    
    # 2. Registrar DDL de destino (Parquet)
    contracts_adls_ddl = schema_utils.generate_contracts_dlq_ddl(
        config.KAFKA_TOPIC_DLQ, "ContractsDlqBronze", config_dict, is_sink=True, sink_path=config.ADLS_DLQ_CONTRACTS_URL
    )
    t_env.execute_sql(contracts_adls_ddl)
    
    # 3. Pipeline hacia Bronze
    sql_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")
    contracts_dlq_insert_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "insert_contracts_dlq.sql"))
    
    stmt_set.add_insert_sql(contracts_dlq_insert_sql)
