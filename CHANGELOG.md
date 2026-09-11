# Changelog


## [Unreleased]

### Added
- **Configuración de Flink**: Modificación de la configuración para detectar LAG en Kafka y enviar peticiones HTTP a FastAPI (`streaming/Dockerfile`, `streaming/src/jobs/config.py`).
- **Orquestador de Flink**: Desacople del procesamiento creando un orquestador propio para Flink, agregando nuevos pipelines de alertas ETA (`streaming/src/jobs/nautiq_job.py`, `streaming/src/jobs/orchestrator.py`, `streaming/src/jobs/pipelines/eta_alerts.py`).

### Changed
- **SQL por Dominio**: Refactorización profunda y reorganización de todas las queries SQL de Flink, separándolas por dominios lógicos (`ddl/`, `dlq/`, `eta/`, `static/`, `telemetry/`) para mejor mantenibilidad (`streaming/src/jobs/sql/*`).
## [1.0.0] - 2026-08-06

### Added
- **Pipeline Predictivo de ETA**: Algoritmo en Flink para calcular el ETA dinámico en tiempo real usando la Ley Esférica de Cosenos (`eta_alerts.py`, `eta_dynamic.sql`).
- **Inventario Portuario**: Clasificación en tiempo real de buques en estado Atracado, Fondeado y En Camino usando ventanas de tiempo (Tumbling Windows de 30 min).
- **Integración Webhook-Azure**: Nuevo conector `http-sink` en Flink (`create_eta_alerts_sink.sql`) para emitir alertas JSON asíncronas con headers de autorización.
- **Servicio de Alertas FastAPI**: Nueva capa de servicios de dominio (`eta_alert_service.py`) y DTOs basados en Pydantic (`eta_alert_schema.py`) para procesar e inyectar payloads hacia LangGraph.
- **Documentación Arquitectónica (Docstrings)**: Se incorporaron comentarios técnicos estructurados (Propósito, Patrón, Decisiones de Diseño, Datos consumidos) en todos los módulos `.py` de pipelines y servicios.

### Changed
- **Re-arquitectura de Ventanas (Insert-Only)**: Reestructuración de la deduplicación y consolidación de alertas para utilizar ventanas `TUMBLE` con `FIRST_VALUE` y una agregación en 2 fases en el inventario. Esto convierte todo el flujo en **Insert-Only (Append-Only)**, eliminando las operaciones de retracción (`ROW_NUMBER() OVER` continuo) incompatibles con el sink HTTP.
- **Domain-Driven Design (SQL)**: Se reorganizaron los scripts de Flink SQL sueltos en subdirectorios semánticos (`ddl/`, `telemetry/`, `static/`, `eta/`, `dlq/`) para asegurar el escalado.
- **Refactorización de Controladores**: El endpoint POST `/api/v1/alerts/eta` en `webhooks.py` ha sido refactorizado para delegar toda la lógica de negocio a la capa de servicios, habilitando validación estricta y Swagger automático.
- **Rutas Relativas Flink**: Los módulos de Python de Flink (pipelines) ahora acceden a los archivos SQL enlazados por directorio para mayor flexibilidad sin necesidad de recompilar.

### Fixed
- **Validación del Sink HTTP (GetInData)**: Corrección de las opciones DDL en el `http-sink` usando prefijos `gid.connector.http.sink.header.*` para cabeceras de autorización y timeout, y cambio a formato `raw` para evitar doble codificación JSON.
- **Bug de Parser Calcite (Look-ahead)**: Corrección del fallo de sintaxis en `JSON_OBJECT` / `JSON_ARRAYAGG` que chocaba con el keyword `ON` del `INNER JOIN` en queries expandidas.
- **Compatibilidad de Tipos en Flink**: Casteo explícito a `VARCHAR` de la columna `_event_time` (tipo `ROWTIME`) dentro de la función `UNIX_TIMESTAMP` para permitir el cálculo aritmético del inicio de ventana.
- **Trigger de Commit en Data Lake**: Se configuró `'sink.partition-commit.trigger' = 'process-time'` y `'sink.partition-commit.delay' = '0s'` en las tablas Sink Parquet (`create_table_sink.sql`, `schema_utils.py`). Esto elimina el bloqueo donde Flink retenía los archivos Parquet en buffer esperando a que el Watermark sobrepasara el final del día (`partition-time`), forzando la escritura inmediata a Azure ADLS en cada checkpoint.
- **Estabilidad de Memoria (RocksDB)**: Activación del conector off-heap `RocksDB` como State Backend en `config.py` para almacenar de forma eficiente el estado de los joins e inventarios, eliminando fallos por falta de memoria Heap (`OutOfMemoryError: Java heap space`) al re-procesar históricos de Kafka.
- **Crash Blink Planner (Flink)**: Resolución del error de subconsultas correlacionadas al transformar la creación de objetos JSON. Se resolvió pre-agregando la data mediante `port_inventory_summary.sql`.
- **Dependencias**: Se agregó la librería del conector `flink-sql-connector-http` al Dockerfile del clúster de Flink.

