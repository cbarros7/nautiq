"""
Módulo: eta_alerts.py
Propósito: Construye el pipeline predictivo que calcula el ETA dinámico e identifica congestiones en puertos.
Patrón: Event-Driven Serverless / Complex Event Processing (CEP).
Decisión de diseño: Se divide la lógica en múltiples vistas intermedias (inventory, dynamic eta, payload)
                    para eludir las limitaciones del Blink Planner con subconsultas correlacionadas.
                    Emite un HTTP POST asíncrono para despertar a la capa cognitiva (LangGraph).
Datos consumidos: Hace JOIN entre las posiciones limpias ('enriched_positions') y los datos estáticos ('StaticKafka').
                  Escribe a 'EtaAlertsHttpSink'.
"""
import os
# pyrefly: ignore [missing-import]
import config
import schema_utils
from pyflink.table import StreamTableEnvironment, StatementSet

def build_eta_alerts_pipeline(t_env: StreamTableEnvironment, stmt_set: StatementSet, config_dict: dict):
    """
    Construye el pipeline para generar alertas de ETA (Webhook HTTP).
    
    Dependencias:
    - enriched_positions (generada por telemetry.py)
    - StaticKafka (generada en nautiq_job.py)
    """
    sql_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")
    
    # --- 1. Crear Vistas Intermedias ---
    
    # a. resolver puertos de destino (desde StaticKafka)
    port_filter = schema_utils.build_port_filter_sql(config.TARGET_PORTS)
    
    # Construcción dinámica de los bloques CASE para SQL
    resolved_port_cases = ""
    port_lat_cases = ""
    port_lon_cases = ""
    port_radius_cases = ""
    
    for port in config.TARGET_PORTS:
        filter_expr = " OR ".join([f"UPPER(destination) LIKE '%{a}%'" for a in port["aliases"]])
        resolved_port_cases += f"        WHEN {filter_expr} THEN '{port['name']}'\n"
        port_lat_cases += f"        WHEN {filter_expr} THEN {port['lat']}\n"
        port_lon_cases += f"        WHEN {filter_expr} THEN {port['lon']}\n"
        port_radius_cases += f"        WHEN {filter_expr} THEN {port['congestion_radius_nm']}\n"

    resolve_port_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "eta", "resolve_destination_port.sql")).format(
        port_filter=port_filter,
        cargo_min=config.CARGO_SHIP_TYPE_MIN,
        cargo_max=config.CARGO_SHIP_TYPE_MAX,
        resolved_port_cases=resolved_port_cases.rstrip(),
        port_lat_cases=port_lat_cases.rstrip(),
        port_lon_cases=port_lon_cases.rstrip(),
        port_radius_cases=port_radius_cases.rstrip(),
        default_port='UNKNOWN'
    )
    t_env.execute_sql(resolve_port_sql)

    # b. calcular eta_dynamic (hace JOIN con enriched_positions)
    eta_dynamic_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "eta", "eta_dynamic.sql"))
    t_env.execute_sql(eta_dynamic_sql)

    # c. inventario portuario
    inventory_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "eta", "port_vessel_inventory.sql")).format(
        dedup_window=config.ALERT_DEDUP_WINDOW_MINUTES,
        en_camino_max_eta=config.EN_CAMINO_MAX_ETA_HOURS
    )
    t_env.execute_sql(inventory_sql)

    # d. resumen de inventario (pre-agregación JSON de 2 fases)
    # NOTA: port_inventory_summary.sql contiene múltiples sentencias DDL separadas por ';'.
    # Flink t_env.execute_sql sólo admite una sentencia por llamada. Las dividimos y ejecutamos una a una.
    inventory_summary_sql_raw = schema_utils.read_sql_file(os.path.join(sql_dir, "eta", "port_inventory_summary.sql")).format(
        dedup_window=config.ALERT_DEDUP_WINDOW_MINUTES
    )
    for statement in inventory_summary_sql_raw.split(";"):
        stmt = statement.strip()
        if stmt:
            t_env.execute_sql(stmt)

    # e. build alert payload JSON e INSERT directo al sink HTTP
    # NOTA: NO se usa CREATE TEMPORARY VIEW porque el Expander de Flink
    # (SqlCreateViewConverter → Expander.expanded) re-serializa el AST de las vistas
    # dependientes eliminando las cláusulas NULL ON NULL de JSON_OBJECT/JSON_ARRAYAGG.
    # Al re-parsear, el parser confunde el ON del INNER JOIN con la regla de nulos de JSON.
    # Usar INSERT INTO directamente evita este ciclo de serialización/re-parseo.
    payload_insert_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "eta", "build_eta_alert_payload.sql")).format(
        dedup_window=config.ALERT_DEDUP_WINDOW_MINUTES,
        eta_alert_horizon=config.ETA_ALERT_HORIZON_HOURS,
        congestion_threshold=config.CONGESTION_VESSEL_THRESHOLD
    )

    # --- 2. Crear Sink de Salida (HTTP) ---
    
    # Crear Auth Header si hay una key definida
    webhook_auth_header = ""
    webhook_key = config.FASTAPI_WEBHOOK_KEY
    if webhook_key:
        webhook_auth_header = f",\n    'gid.connector.http.sink.header.Authorization' = 'Bearer {webhook_key}'"

    # Opciones de seguridad SSL para HTTP Sink (requerido por flink-http-connector en HTTPS)
    webhook_security_options = ""
    if config.FASTAPI_WEBHOOK_URL and config.FASTAPI_WEBHOOK_URL.lower().startswith("https://"):
        keystore_path = "/etc/ssl/certs/java/cacerts"
        if not os.path.exists(keystore_path):
            keystore_path = "/opt/java/openjdk/lib/security/cacerts"
        webhook_security_options = (
            f",\n    'gid.connector.http.security.keystore.path' = '{keystore_path}',"
            f"\n    'gid.connector.http.security.keystore.password' = 'changeit'"
        )
        cert_prod = "/opt/flink/usrlib/src/azure_function_cert_prod.pem"
        cert_dev = "/opt/flink/usrlib/src/azure_function_cert.pem"
        if os.path.exists(cert_prod):
            webhook_security_options += f",\n    'gid.connector.http.security.cert.server' = '{cert_prod}'"
        elif os.path.exists(cert_dev):
            webhook_security_options += f",\n    'gid.connector.http.security.cert.server' = '{cert_dev}'"

    sink_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "ddl", "create_eta_alerts_sink.sql")).format(
        webhook_url=config.FASTAPI_WEBHOOK_URL,
        webhook_security_options=webhook_security_options,
        webhook_auth_header=webhook_auth_header
    )
    t_env.execute_sql(sink_sql)

    # --- 3. Crear Sink de Salida Local (JSON Debug, sólo en dev) ---
    if config.FLINK_ENV == "dev":
        import logging
        logger = logging.getLogger("nautiq_job")
        logger.info("Inyectando Debug Sinks (JSON local en /tmp) para port_inventory_summary...")
        
        debug_inventory_ddl = """
        CREATE TABLE DebugInventorySummary (
            port_name STRING,
            window_start TIMESTAMP(3),
            congested_count BIGINT,
            atracados_json STRING,
            fondeados_json STRING,
            en_camino_json STRING
        ) WITH (
            'connector' = 'filesystem',
            'path' = 'file:///tmp/debug_output/inventory',
            'format' = 'json'
        )
        """
        t_env.execute_sql(debug_inventory_ddl)
        stmt_set.add_insert_sql("INSERT INTO DebugInventorySummary SELECT * FROM port_inventory_summary")

    # --- 4. Añadir INSERTs directos al statement set ---
    # Añadimos la inserción del payload final al HTTP Sink
    stmt_set.add_insert_sql(payload_insert_sql)
