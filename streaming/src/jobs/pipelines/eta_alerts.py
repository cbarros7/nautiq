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
    # Extraer variables para interpolación
    valencia = next(p for p in config.TARGET_PORTS if p["name"] == "VALENCIA")
    algeciras = next(p for p in config.TARGET_PORTS if p["name"] == "ALGECIRAS")
    bcn = next(p for p in config.TARGET_PORTS if p["name"] == "BARCELONA")
    
    valencia_filter = " OR ".join([f"UPPER(destination) LIKE '%{a}%'" for a in valencia["aliases"]])
    algeciras_filter = " OR ".join([f"UPPER(destination) LIKE '%{a}%'" for a in algeciras["aliases"]])
    bcn_filter = " OR ".join([f"UPPER(destination) LIKE '%{a}%'" for a in bcn["aliases"]])

    resolve_port_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "eta", "resolve_destination_port.sql")).format(
        port_filter=port_filter,
        cargo_min=config.CARGO_SHIP_TYPE_MIN,
        cargo_max=config.CARGO_SHIP_TYPE_MAX,
        valencia_filter=valencia_filter,
        valencia_lat=valencia["lat"],
        valencia_lon=valencia["lon"],
        valencia_radius=valencia["congestion_radius_nm"],
        algeciras_filter=algeciras_filter,
        algeciras_lat=algeciras["lat"],
        algeciras_lon=algeciras["lon"],
        algeciras_radius=algeciras["congestion_radius_nm"],
        bcn_filter=bcn_filter,
        bcn_lat=bcn["lat"],
        bcn_lon=bcn["lon"],
        bcn_radius=bcn["congestion_radius_nm"],
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
    webhook_key = os.getenv("FASTAPI_WEBHOOK_KEY", "")
    if webhook_key:
        webhook_auth_header = f",\n    'gid.connector.http.sink.header.Authorization' = 'Bearer {webhook_key}'"

    sink_sql = schema_utils.read_sql_file(os.path.join(sql_dir, "ddl", "create_eta_alerts_sink.sql")).format(
        webhook_url=config.FASTAPI_WEBHOOK_URL,
        webhook_auth_header=webhook_auth_header
    )
    t_env.execute_sql(sink_sql)

    # --- 3. Añadir INSERT directo al statement set ---
    stmt_set.add_insert_sql(payload_insert_sql)
