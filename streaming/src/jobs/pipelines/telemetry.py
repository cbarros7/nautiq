import os
import config
import schema_utils
from pyflink.table import StreamTableEnvironment, StatementSet

def build_telemetry_pipeline(t_env: StreamTableEnvironment, stmt_set: StatementSet, config_dict: dict):
    """
    Construye el pipeline de telemetría de posiciones, incluyendo:
    - Ingesta desde Kafka.
    - Detección de Spoofing mediante State Pattern (LAG).
    - Enrutamiento hacia Bronze (Válidos) y DLQ (Spoofing).
    """
    # 1. Registrar DDL de Origen
    pos_kafka_ddl, pos_schema_version = schema_utils.generate_ddl_from_registry(
        config.KAFKA_TOPIC_POSITIONS, "PositionsKafka", config_dict, is_sink=False
    )
    t_env.execute_sql(pos_kafka_ddl)
    
    # 2. Registrar DDL de destino (Bronze Parquet)
    adls_pos_path = f"{config.ADLS_BRONZE_URL}/positions"
    pos_adls_ddl, _ = schema_utils.generate_ddl_from_registry(
        config.KAFKA_TOPIC_POSITIONS, "PositionsBronze", config_dict, is_sink=True, sink_path=adls_pos_path
    )
    t_env.execute_sql(pos_adls_ddl)
    
    # 3. Registrar DDL de spoofing DLQ
    spoofing_dlq_ddl, _ = schema_utils.generate_spoofing_dlq_ddl(
        config.KAFKA_TOPIC_POSITIONS, "SpoofingDLQ", config_dict, config.ADLS_DLQ_SPOOFING_URL
    )
    t_env.execute_sql(spoofing_dlq_ddl)
    
    # 4. Vista enriquecida (State Pattern con LAG)
    sql_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")
    enriched_positions_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "enriched_positions.sql"))
    t_env.execute_sql(enriched_positions_sql)
    
    # 5. Pipeline hacia Bronze (Ruta válida)
    pos_valid_insert_sql_template = schema_utils.read_sql_file(os.path.join(sql_dir, "insert_positions_valid.sql"))
    pos_valid_insert_sql = pos_valid_insert_sql_template.format(
        schema_version=pos_schema_version,
        spoofing_threshold=config.SPOOFING_SPEED_THRESHOLD_KNOTS
    )
    
    # 6. Pipeline hacia Spoofing DLQ (Ruta anómala)
    spoofing_dlq_insert_sql_template = schema_utils.read_sql_file(os.path.join(sql_dir, "insert_spoofing_dlq.sql"))
    spoofing_dlq_insert_sql = spoofing_dlq_insert_sql_template.format(
        schema_version=pos_schema_version,
        spoofing_threshold=config.SPOOFING_SPEED_THRESHOLD_KNOTS
    )
    
    stmt_set.add_insert_sql(pos_valid_insert_sql)
    stmt_set.add_insert_sql(spoofing_dlq_insert_sql)
