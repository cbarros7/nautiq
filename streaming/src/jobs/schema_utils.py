import json
import requests
import base64
import os

def read_sql_file(filepath: str) -> str:
    """Lee el contenido de un archivo SQL."""
    try:
        with open(filepath, 'r') as f:
            return f.read()
    except FileNotFoundError:
        raise RuntimeError(f"Error crítico: No se encontró el archivo SQL en la ruta {filepath}")
    except Exception as e:
        raise RuntimeError(f"Error al leer el archivo SQL {filepath}: {str(e)}")

def avro_type_to_flink_sql_type(avro_type: str | dict | list) -> str:
    """Mapea tipos de datos primitivos de Avro a Flink SQL."""
    if isinstance(avro_type, list):
        # Es un Union (ej: ["null", "double"])
        non_null_types = [t for t in avro_type if t != "null"]
        if not non_null_types:
            return "STRING"
        avro_type = non_null_types[0]
        
    type_mapping = {
        "string": "STRING",
        "int": "INT",
        "long": "BIGINT",
        "float": "FLOAT",
        "double": "DOUBLE",
        "boolean": "BOOLEAN",
        "bytes": "BYTES"
    }
    return type_mapping.get(avro_type, "STRING")

def fetch_schema_from_registry(registry_url: str, auth: str, subject_name: str) -> dict:
    """
    Descarga la última versión del esquema JSON desde Aiven Schema Registry.
    """
    endpoint = f"{registry_url}/subjects/{subject_name}/versions/latest"
    
    # Preparar Basic Auth header manualmente ya que auth viene concatenado user:pass
    auth_bytes = auth.encode('ascii')
    base64_bytes = base64.b64encode(auth_bytes)
    base64_auth = base64_bytes.decode('ascii')
    
    headers = {
        'Authorization': f'Basic {base64_auth}',
        'Accept': 'application/json'
    }
    
    response = requests.get(endpoint, headers=headers)
    if response.status_code != 200:
        raise ConnectionError(f"Failed to fetch schema for {subject_name} from {endpoint}. HTTP {response.status_code}: {response.text}")
        
    # La API de Confluent devuelve un JSON con un campo 'schema' que contiene un string JSON escapado, y un campo 'version'
    registry_response = response.json()
    schema_str = registry_response.get("schema")
    schema_version = registry_response.get("version", 1)
    if not schema_str:
        raise ValueError(f"No schema found in registry response for {subject_name}")
        
    return json.loads(schema_str), schema_version

def get_columns_from_registry(topic_name: str, table_name: str, config_dict: dict, is_sink: bool = False) -> tuple[str, int]:
    """Obtiene las columnas y la versión del esquema desde Aiven Schema Registry para Flink SQL."""
    subject_name = f"{topic_name}-value"
    
    schema, schema_version = fetch_schema_from_registry(
        config_dict["KAFKA_SCHEMA_REGISTRY_URL"],
        config_dict["KAFKA_SCHEMA_REGISTRY_AUTH"],
        subject_name
    )
        
    fields = schema.get("fields", [])
    if not fields:
        raise ValueError(f"No fields defined in remote avro schema for topic {topic_name}")
        
    columns = []
    for field in fields:
        col_name = field["name"]
        col_type = avro_type_to_flink_sql_type(field["type"])
        if col_name == "timestamp":
            col_name = f"`{col_name}`"
        columns.append(f"    {col_name} {col_type}")
        
    if is_sink:
        columns.append("    `kafka_ingestion_time` TIMESTAMP_LTZ(3)")
        columns.append("    `kafka_partition` BIGINT")
        columns.append("    `kafka_offset` BIGINT")
        columns.append("    `flink_processing_time` TIMESTAMP_LTZ(3)")
        columns.append("    `schema_version` BIGINT")
        columns.append("    `dt` STRING")
    else:
        columns.append("    `kafka_ingestion_time` TIMESTAMP_LTZ(3) METADATA FROM 'timestamp'")
        columns.append("    `kafka_partition` BIGINT METADATA FROM 'partition'")
        columns.append("    `kafka_offset` BIGINT METADATA FROM 'offset'")
        
    columns_str = ",\n".join(columns)
    
    # Event-Time y Watermarks para habilitar LAG() en streaming
    if not is_sink and table_name == "PositionsKafka":
        watermark_ddl = ",\n    `event_time` AS TO_TIMESTAMP(REPLACE(SUBSTRING(`timestamp`, 1, 19), 'T', ' ')),\n    WATERMARK FOR `event_time` AS `event_time` - INTERVAL '1' MINUTE"
        columns_str += watermark_ddl
        
    return columns_str, schema_version

def generate_ddl_from_registry(topic_name: str, table_name: str, config_dict: dict, is_sink: bool = False, sink_path: str = None) -> tuple[str, int]:
    """
    Descarga el contrato desde Aiven Schema Registry y genera un CREATE TABLE en sintaxis Flink SQL.
    """
    columns_str, schema_version = get_columns_from_registry(topic_name, table_name, config_dict, is_sink)
    
    sql_dir = os.path.join(os.path.dirname(__file__), "sql")
    if is_sink:
        template = read_sql_file(os.path.join(sql_dir, "create_table_sink.sql"))
        ddl = template.format(
            table_name=table_name,
            columns_str=columns_str,
            sink_path=sink_path
        )
    else:
        template = read_sql_file(os.path.join(sql_dir, "create_table_source.sql"))
        ddl = template.format(
            table_name=table_name,
            columns_str=columns_str,
            topic_name=topic_name,
            kafka_bootstrap_servers=config_dict["KAFKA_BOOTSTRAP_SERVERS"],
            kafka_security_protocol=config_dict["KAFKA_SECURITY_PROTOCOL"],
            kafka_ssl_ca_location=config_dict["KAFKA_SSL_CA_LOCATION"],
            kafka_ssl_cert_location=config_dict["KAFKA_SSL_CERT_LOCATION"],
            kafka_schema_registry_url=config_dict["KAFKA_SCHEMA_REGISTRY_URL"],
            kafka_schema_registry_auth=config_dict["KAFKA_SCHEMA_REGISTRY_AUTH"]
        )
        
    return ddl, schema_version
def generate_spoofing_dlq_ddl(topic_name: str, table_name: str, config_dict: dict, sink_path: str) -> tuple[str, int]:
    """Genera el DDL para el sink SpoofingDLQ descargando las columnas base del registry y añadiendo las de diagnóstico."""
    columns_str, schema_version = get_columns_from_registry(topic_name, table_name, config_dict, is_sink=True)
    
    diagnostic_columns = """
    , `prev_lat` DOUBLE,
    `prev_lon` DOUBLE,
    `prev_time` TIMESTAMP_LTZ(3),
    `distance_nm` DOUBLE,
    `delta_hours` DOUBLE,
    `implied_speed_knots` DOUBLE,
    `anomaly_reason` STRING,
    `threshold_used` DOUBLE"""
    
    columns_str += diagnostic_columns
    
    ddl = f"""
    CREATE TABLE {table_name} (
    {columns_str}
    ) PARTITIONED BY (`dt`) WITH (
        'connector' = 'filesystem',
        'path' = '{sink_path}',
        'format' = 'parquet',
        'sink.partition-commit.policy.kind' = 'success-file',
        'auto-compaction' = 'true',
        'parquet.compression' = 'snappy'
    )
    """
    return ddl, schema_version
def generate_contracts_dlq_ddl(topic_name: str, table_name: str, config_dict: dict, is_sink: bool = False, sink_path: str = None) -> str:
    """
    Genera el DDL para el topic de DLQ de contratos usando 'format'='raw'
    para leer JSONs rotos sin crashear.
    """
    sql_dir = os.path.join(os.path.dirname(__file__), "sql")
    if is_sink:
        template = read_sql_file(os.path.join(sql_dir, "create_contracts_dlq_bronze.sql"))
        return template.format(
            table_name=table_name,
            sink_path=sink_path
        )
    else:
        template = read_sql_file(os.path.join(sql_dir, "create_contracts_dlq_kafka.sql"))
        return template.format(
            table_name=table_name,
            topic_name=topic_name,
            kafka_bootstrap_servers=config_dict["KAFKA_BOOTSTRAP_SERVERS"],
            kafka_security_protocol=config_dict["KAFKA_SECURITY_PROTOCOL"],
            kafka_ssl_ca_location=config_dict["KAFKA_SSL_CA_LOCATION"],
            kafka_ssl_cert_location=config_dict["KAFKA_SSL_CERT_LOCATION"]
        )
