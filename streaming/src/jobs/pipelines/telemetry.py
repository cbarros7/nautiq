"""
Módulo: telemetry.py
Propósito: Gestiona el pipeline de limpieza y enriquecimiento de posiciones AIS.
Patrón: Stateful Streaming / Filtro de Anomalías (Spoofing).
Decisión de diseño: Se separa el tráfico válido (hacia Bronze) de las anomalías (hacia DLQ) usando
                    la Ley de Cosenos y LAG (estado) para identificar velocidades imposibles. Se encapsula
                    la lógica SQL para mantener Python modular.
Datos consumidos: Lee de 'PositionsKafka', registra vistas intermedias ('enriched_positions'), y escribe a
                  'PositionsBronze' y 'SpoofingDLQ'.
"""
import os
# pyrefly: ignore [missing-import]
import config
import schema_utils
from pyflink.table import StreamTableEnvironment, StatementSet


def build_telemetry_pipeline(t_env: StreamTableEnvironment, stmt_set: StatementSet, config_dict: dict):
    """
    Construye el pipeline de telemetría de posiciones, incluyendo:
    - Ingesta desde Kafka.
    - Detección de Spoofing mediante State Pattern (LAG + trigonometría esférica).
    - Filtrado por tipo de buque (cargo, 70-79) y puerto de destino (target_ships).
    - Enrutamiento hacia Bronze (Válidos) y DLQ (Spoofing).

    PRECONDICIÓN: StaticKafka debe estar registrado en t_env antes de llamar
    a este pipeline (lo registra nautiq_job.py en el paso de shared setup).
    """
    sql_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")
    port_filter = schema_utils.build_port_filter_sql(config.TARGET_PORTS)

    # 1. DDL de Origen (posiciones crudas desde Kafka)
    pos_kafka_ddl, pos_schema_version = schema_utils.generate_ddl_from_registry(
        config.KAFKA_TOPIC_POSITIONS, "PositionsKafka", config_dict, is_sink=False
    )
    t_env.execute_sql(pos_kafka_ddl)

    # 2. DDL de Destino (Bronze Parquet en ADLS)
    adls_pos_path = f"{config.ADLS_BRONZE_URL}/positions"
    pos_adls_ddl, _ = schema_utils.generate_ddl_from_registry(
        config.KAFKA_TOPIC_POSITIONS, "PositionsBronze", config_dict, is_sink=True, sink_path=adls_pos_path
    )
    t_env.execute_sql(pos_adls_ddl)

    # 3. DDL de Spoofing DLQ (Parquet en ADLS)
    spoofing_dlq_ddl, _ = schema_utils.generate_spoofing_dlq_ddl(
        config.KAFKA_TOPIC_POSITIONS, "SpoofingDLQ", config_dict, config.ADLS_DLQ_SPOOFING_URL
    )
    t_env.execute_sql(spoofing_dlq_ddl)

    # 4. Vista enriquecida: State Pattern con LAG + fórmula de Haversine
    enriched_positions_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "telemetry", "enriched_positions.sql"))
    t_env.execute_sql(enriched_positions_sql)

    # 5. INSERT hacia Bronze (posiciones válidas con filtrado de buques objetivo)
    pos_valid_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "telemetry", "insert_positions_valid.sql")).format(
        schema_version=pos_schema_version,
        spoofing_threshold=config.SPOOFING_SPEED_THRESHOLD_KNOTS,
        cargo_min=config.CARGO_SHIP_TYPE_MIN,
        cargo_max=config.CARGO_SHIP_TYPE_MAX,
        port_filter=port_filter
    )

    # 6. INSERT hacia Spoofing DLQ (posiciones anómalas del mismo universo de buques)
    spoofing_dlq_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "telemetry", "insert_spoofing_dlq.sql")).format(
        schema_version=pos_schema_version,
        spoofing_threshold=config.SPOOFING_SPEED_THRESHOLD_KNOTS,
        cargo_min=config.CARGO_SHIP_TYPE_MIN,
        cargo_max=config.CARGO_SHIP_TYPE_MAX,
        port_filter=port_filter
    )

    stmt_set.add_insert_sql(pos_valid_sql)
    stmt_set.add_insert_sql(spoofing_dlq_sql)
