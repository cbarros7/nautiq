# Nautiq streaming engine — Apache Flink y complex event processing (CEP)

Módulo central de procesamiento en tiempo real y flujo continuo (*stream processing*) de la plataforma **Nautiq**. Este componente ingesta, valida, enriquece y analiza telemetría marítima global en streaming (estándar AIS - *Automatic Identification System*) mediante **Apache Flink 1.19** sobre Python (**PyFlink**) y la API declarativa de **Flink SQL**.

---

## Tabla de contenidos
1. [Visión general y objetivos](#visión-general-y-objetivos)
2. [Arquitectura del sistema](#arquitectura-del-sistema)
3. [Topología de pipelines (job graph)](#topología-de-pipelines-job-graph)
   - [3.1. Telemetry pipeline (posiciones y anti-spoofing)](#31-telemetry-pipeline-posiciones-y-anti-spoofing)
   - [3.2. Static data pipeline (dimensión buques)](#32-static-data-pipeline-dimensión-buques)
   - [3.3. Contracts DLQ pipeline (dead letter queue)](#33-contracts-dlq-pipeline-dead-letter-queue)
   - [3.4. ETA alerts pipeline (CEP y pre-agregación portuaria)](#34-eta-alerts-pipeline-cep-y-pre-agregación-portuaria)
4. [Decisiones de diseño y arquitectura (ADRs)](#decisiones-de-diseño-y-arquitectura-adrs)
   - [ADR-01: Garantía append-only (insert-only) en HTTP sink](#adr-01-garantía-append-only-insert-only-en-http-sink)
   - [ADR-02: Bypass de bugs en el SQL view expander de Flink](#adr-02-bypass-de-bugs-en-el-sql-view-expander-de-flink)
   - [ADR-03: Inyección de credenciales ADLS Gen2 vía Hadoop core-site](#adr-03-inyección-de-credenciales-adls-gen2-vía-hadoop-core-site)
   - [ADR-04: Gestión de estado fuera de heap con RocksDB y TTL](#adr-04-gestión-de-estado-fuera-de-heap-con-rocksdb-y-ttl)
   - [ADR-05: Patrón external orchestrator para simulación bounded](#adr-05-patrón-external-orchestrator-para-simulación-bounded)
5. [Estructura del directorio](#estructura-del-directorio)
6. [Configuración y variables de entorno](#configuración-y-variables-de-entorno)
7. [Guía operativa y despliegue](#guía-operativa-y-despliegue)
   - [Despliegue local (DEV)](#despliegue-local-dev)
   - [Despliegue en Azure VM (PROD)](#despliegue-en-azure-vm-prod)
   - [Operaciones y monitoreo](#operaciones-y-monitoreo)

---

## Visión general y objetivos

El motor de streaming de Nautiq tiene tres misiones operativas críticas:

1. **Ingesta y limpieza de telemetría masiva:** Filtrar millones de señales AIS de buques en el Mediterráneo y estrecho de Gibraltar, eliminando tráfico irrelevante (recreativo, pesca) y aislando anomalías cinemáticas (*spoofing* o saltos de señal imposibles).
2. **Persistencia en data lakehouse (capa bronze):** Escribir datos particionados por fecha (`_dt=YYYY-MM-DD`) en formato **Parquet** dentro de **Azure Data Lake Storage Gen2 (ADLS)** con semántica *Exactly-Once*.
3. **Detección predictiva de congestión y alertas (CEP):** Calcular en tiempo real el tiempo estimado de llegada dinámico (**ETA dinámico**) de buques mercantes hacia los principales puertos objetivo (Valencia, Algeciras, Barcelona, Bilbao, etc.) y despertar de forma asíncrona a la capa cognitiva (agentes IA en Azure Functions / LangGraph) cuando se detecte saturación portuaria inminente.

---

## Arquitectura del sistema

```
                         ┌──────────────────────────────────────────────┐
                         │              Aiven Apache Kafka              │
                         └──────┬────────────────────┬──────────────────┘
                                │                    │
                        positions.v1 (Avro)    static.v1 (Avro)
                                │                    │
                                ▼                    ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │                          Apache Flink 1.19 (PyFlink Engine)                      │
 │                                                                                  │
 │  ┌───────────────────────────┐         ┌──────────────────────────────────────┐  │
 │  │    Telemetry Pipeline     │         │        Static Data Pipeline          │  │
 │  │  - LAG() Window           │         │  - Ship Type Filter (70-79 Cargo)    │  │
 │  │  - Spherical Law Cosines  │         │  - Target Port Filter                │  │
 │  │  - Spoofing Filter        │         └──────────────────┬───────────────────┘  │
 │  └─────────────┬─────────────┘                            │                      │
 │                │ enriched_positions                       │                      │
 │                └───────────────────────┐   ┌──────────────┘                      │
 │                                        ▼   ▼                                     │
 │                               ┌────────────────────────────────┐                 │
 │                               │      ETA Alerts Pipeline       │                 │
 │                               │  - Temporal Join               │                 │
 │                               │  - Geofencing & Inventory      │                 │
 │                               │  - 2-Phase Tumbling Windows    │                 │
 │                               │  - JSON Payload Assembly       │                 │
 │                               └────────────────┬───────────────┘                 │
 └───────────────────────┬────────────────────────┼────────────────────────┬────────┘
                         │                        │                        │
                         ▼                        ▼                        ▼
        ┌────────────────────────────────┐        │        ┌────────────────────────────────┐
        │       PositionsBronze          │        │        │          StaticBronze          │
        │      (ADLS Gen2 Parquet)       │        │        │      (ADLS Gen2 Parquet)       │
        └────────────────────────────────┘        │        └────────────────────────────────┘
                                                  ▼
                                ┌───────────────────────────────────┐
                                │     EtaAlertsHttpSink (HTTP)      │
                                │   --> Azure Function Webhook      │
                                └───────────────────────────────────┘
```

---

## Topología de pipelines (job graph)

El punto de entrada unificado es `streaming/src/jobs/nautiq_job.py`, el cual utiliza el patrón de diseño **Facade** para registrar las fuentes compartidas y compilar los cuatro sub-pipelines en un único `StatementSet` atómico:

### 3.1. Telemetry pipeline (posiciones y anti-spoofing)
* **Fuente:** Topic Kafka `positions.v1` (`PositionsKafka`) deserializado dinámicamente mediante el esquema Avro registrado en Confluent Schema Registry.
* **Algoritmo anti-spoofing:**
  A través de la vista temporal `enriched_positions.sql`, se aplica una función analítica de ventana (`LAG`) sobre `mmsi` ordenada por `_event_time`:
  $$\text{distancia\_nm} = 3440.065 \times \arccos\left(\sin(\text{lat}_1)\sin(\text{lat}_2) + \cos(\text{lat}_1)\cos(\text{lat}_2)\cos(\text{lon}_2 - \text{lon}_1)\right)$$
  *Se aplica un clamping estricto $[-1.0, 1.0]$ al argumento de $\arccos$ para evitar errores de dominio y `NaN` en Flink por imprecisiones de punto flotante IEEE 754.*
* **Bifurcación:**
  * **Válidos ($\text{velocidad} \le 50 \text{ nudos}$):** Se insertan en `PositionsBronze` (`abfss://bronze@.../telemetry/positions/_dt=...`).
  * **Anomalías ($\text{velocidad} > 50 \text{ nudos}$):** Se desvían a `SpoofingDLQ` (`abfss://bronze@.../telemetry/spoofing_dlq/`) para auditoría forense.

### 3.2. Static data pipeline (dimensión buques)
* **Fuente:** Topic Kafka `static.v1` (`StaticKafka`), registrado una única vez a nivel de cluster.
* **Filtrado temprano en origen:** Solo permite el paso de buques de carga (`ship_type` entre 70 y 79) cuyo destino declarado (`destination`) coincida con los alias de los puertos configurados en `TARGET_PORTS`.
* **Destino:** `StaticBronze` (`abfss://bronze@.../telemetry/static/_dt=...`).

### 3.3. Contracts DLQ pipeline (dead letter queue)
* **Fuente:** Topic Kafka `dead-letter-queue.contracts` (`ContractsDlqKafka`).
* **Lectura en crudo:** Utiliza el conector con formato `'format' = 'raw'` para leer los bytes sin intentar parsear esquemas. Si un mensaje entrante en la capa de ingesta posee un JSON malformado o un schema Avro no compatible, se aísla de inmediato sin tirar abajo los workers de Flink.
* **Destino:** `ContractsDlqBronze`.

### 3.4. ETA alerts pipeline (CEP y pre-agregación portuaria)
Implementa la lógica central de **Complex Event Processing (CEP)** y cálculo predictivo:
1. **Resolución de puertos (`resolve_destination_port.sql`):** Mapea cadenas de texto libre de destino (ej. `"VALENCIA PORT"`, `"ES VLC"`) a coordenadas lat/lon oficiales y radios de congestión en millas náuticas (`congestion_radius_nm`).
2. **Cálculo de ETA dinámico (`eta_dynamic.sql`):** Cruza las posiciones enriquecidas con los datos estáticos del buque mediante un temporal join y calcula el tiempo restante en horas:
   $$\text{ETA\_Dynamic} = \frac{\text{Distancia Ortodrómica}(\text{Buque}, \text{Puerto})}{\text{Velocidad (nudos)}}$$
3. **Clasificación de inventario portuario (`port_vessel_inventory.sql`):**
   - `ATRACADO`: Estado de navegación 5 (`Moored`) dentro del radio de congestión.
   - `FONDEADO`: Estado de navegación 1 (`At anchor`) dentro del radio de congestión.
   - `EN_CAMINO`: Fuera del radio de congestión, navegando hacia el puerto con ETA dinámico menor al horizonte de alerta (`EN_CAMINO_MAX_ETA_HOURS`).
4. **Pre-agregación en 2 fases con ventanas tumbling (`port_inventory_summary.sql`):**
   - **Fase 1 (`unique_port_vessel_inventory`):** Agrupación por ventana temporal de tumbling (`TUMBLE_START` y `TUMBLE_ROWTIME`) para deduplicar posiciones de un mismo barco.
   - **Fase 2 (`port_inventory_summary`):** Agrupa a nivel de puerto y genera arrays JSON estructurados (`JSON_ARRAYAGG` con `JSON_OBJECT`) con los barcos presentes.
5. **Ensamblaje del payload y webhook (`build_eta_alert_payload.sql`):**
   - Cruza el buque candidato con el inventario del puerto destino en la misma ventana temporal.
   - Dispara la alerta si el puerto destino tiene congestión ($\ge \text{CONGESTION\_VESSEL\_THRESHOLD}$) y el barco está próximo ($\le \text{ETA\_ALERT\_HORIZON\_HOURS}$).
   - Emite el paquete a través del sink HTTP (`EtaAlertsHttpSink`) directamente a la Azure Function.

---

## Decisiones de diseño y arquitectura (ADRs)

### ADR-01: Garantía append-only (insert-only) en HTTP sink
* **Problema:** Los conectores HTTP de Flink (`flink-http-connector`) implementan la interfaz `AppendStreamTableSink`. Si la consulta SQL contiene agregaciones convencionales con `GROUP BY`, Flink infiere un changelog con mensajes de actualización/borrado (`UPDATE_BEFORE`, `UPDATE_AFTER`), provocando una excepción de compilación: `Table sink doesn't support consuming update and delete changes`.
* **Solución:** Todo el pipeline de inventario y alertas se estructuró mediante ventanas de tiempo de tumbling alineadas sobre marcas de agua de eventos (`TUMBLE_ROWTIME`). Al cerrarse cada ventana, Flink garantiza que el resultado es inmutable y emite eventos estrictamente `INSERT-ONLY`.

### ADR-02: Bypass de bugs en el SQL view expander de Flink
* **Problema:** En Flink 1.19, el convertidor de vistas del planificador Calcite (`SqlCreateViewConverter` / `Expander.expanded`) re-serializa el AST de vistas intermedias que usan funciones JSON complejas (`JSON_OBJECT`, `JSON_ARRAYAGG`). En este proceso de re-serialización, elimina las cláusulas `ABSENT ON NULL` y confunde la palabra clave `ON` del `JOIN` con la regla de nulos de JSON, arrojando errores sintácticos irrecuperables al compilar.
* **Solución:** En lugar de crear una vista temporal anidada para el payload final, el archivo `build_eta_alert_payload.sql` ejecuta un `INSERT INTO EtaAlertsHttpSink SELECT ...` directo, eludiendo la serialización del expander de vistas.

### ADR-03: Inyección de credenciales ADLS Gen2 vía Hadoop core-site
* **Problema:** Flink 1.19 migró a un analizador YAML estricto (`config.yaml`). Al intentar inyectar SAS tokens o Storage Keys mediante variables `FLINK_PROPERTIES`, los scripts de arranque (`config-parser-utils.sh` y `docker-entrypoint.sh`) cortaban los valores al encontrar caracteres especiales (`:`, `&`, `=`), destruyendo las claves.
* **Solución:**
  1. Se utiliza la **Storage Account Key** en lugar de SAS tokens temporales.
  2. Un script de pre-arranque (`entrypoint.sh`) inyecta dinámicamente las credenciales en un `/opt/hadoop/etc/hadoop/core-site.xml` nativo antes de iniciar la JVM.
  3. Se configuran `HADOOP_CONF_DIR` y `HADOOP_CLASSPATH` en el contenedor para que el plugin `azure-fs-hadoop` resuelva la autenticación directamente a nivel del filesystem de Hadoop.

### ADR-04: Gestión de estado fuera de heap con RocksDB y TTL
* **Problema:** El streaming AIS ingesta millones de eventos. Mantener las tablas dimensionales (`StaticKafka`) y los estados de los cruces temporales en la memoria Heap de Java provocaría paradas prolongadas de Garbage Collection (GC) o errores de `OutOfMemoryError`.
* **Solución:**
  - Se configuró **EmbeddedRocksDBStateBackend**, almacenando el estado en disco local/SSD fuera del Heap de Java.
  - Se definió un State Time-To-Live (`table.exec.state.ttl`) de **30 días**, permitiendo recordar barcos que no emiten datos estáticos con frecuencia, pero purgando automáticamente buques desguazados o inactivos.
  - Checkpoints incrementales cada 5 minutos en ADLS Gen2 con retención tras cancelación (`ExternalizedCheckpointCleanup.RETAIN_ON_CANCELLATION`).

### ADR-05: Patrón external orchestrator para simulación bounded
* **Problema:** En entornos de presupuesto limitado (cloud educativo / Azure for Students), mantener instancias computacionales 24/7 resulta inviable. Se requería poder correr el pipeline en ventanas controladas o bajo demanda, pero garantizando cero pérdida de datos entre encendidos y apagados.
* **Solución:** Se implementó `orchestrator.py`:
  - Utiliza un archivo de lock distribuido en ADLS (`.orchestrator.lock`) para evitar colisiones.
  - Monitorea el **Kafka Consumer Group Lag**. Cuando el backlog de mensajes pendientes se drena por completo (`lag = 0`), ejecuta un `flink stop --savepointPath ...` ordenado.
  - Al reiniciar, localiza el último Savepoint en ADLS y reanuda el job exactamente donde se quedó.
  - Banderas de control de emergencia:
    - `FLINK_FORCE_UNLOCK="true"`: Elimina locks huérfanos tras caídas abruptas de la VM.
    - `FLINK_FORCE_COLD_START="true"`: Fuerza arranque en frío descartando savepoints si cambian los esquemas de forma incompatible.
    - `FLINK_IGNORE_UNCLAIMED_STATE="true"` (`-n`): Tolera cambios en operadores SQL al restaurar estado.

---

## Estructura del directorio

```
streaming/
├── Dockerfile               # Imagen Docker de Flink 1.19 + Python 3.10 + Hadoop + Conectores
├── docker-compose.yml       # Definición de servicios JobManager y TaskManager
├── entrypoint.sh            # Script wrapper que inyecta credenciales en core-site.xml y cacerts
├── core-site.xml            # Plantilla de configuración XML de Hadoop para Azure Blob FS
├── pyproject.toml / uv.lock # Dependencias de Python gestionadas con uv
├── scripts/
│   └── monitor_alerts.sh    # Script CLI para inspeccionar métricas y alertas generadas
└── src/
    ├── azure_function_cert.pem      # Certificado intermedio para HTTPS hacia Azure Function
    ├── azure_function_cert_prod.pem # Certificado de producción
    └── jobs/
        ├── config.py         # Configuración centralizada de puertos, tópicos, URLs y estado
        ├── schema_utils.py   # Helper para consultar Confluent Schema Registry y generar DDLs
        ├── nautiq_job.py     # Main Job Graph (Facade) que ensambla y somete el StatementSet
        ├── orchestrator.py   # Orquestador del ciclo de vida del job (Savepoints & Idleness)
        ├── pipelines/        # Módulos Python con la lógica de cada flujo
        │   ├── telemetry.py
        │   ├── static_data.py
        │   ├── contracts_dlq.py
        │   └── eta_alerts.py
        └── sql/              # Catálogo de consultas y DDLs en Flink SQL
            ├── ddl/          # Tablas fuentes (Kafka), destinos (Bronze ADLS) y HTTP Sinks
            ├── dlq/          # Consultas para persistencia en Dead Letter Queue
            ├── eta/          # Vistas temporales de inventario, geocodificación y alertas
            ├── static/       # Consultas de filtrado de datos estáticos
            └── telemetry/    # Enriquecimiento cinemático y detección de spoofing
```

---

## Configuración y variables de entorno

Las variables de entorno se definen en el archivo `.env` (o `.env.prod` / `.env.dev` en la raíz del proyecto):

| Variable | Descripción | Valor por defecto / Ejemplo |
| :--- | :--- | :--- |
| `AZURE_STORAGE_ACCOUNT` | Nombre de la cuenta de Azure Storage (ADLS Gen2) | `stnautiqdatadevswc` |
| `AZURE_STORAGE_KEY` | Clave de acceso primaria para ADLS Gen2 | *[Secret]* |
| `KAFKA_BOOTSTRAP_SERVERS` | Endpoint del cluster de Apache Kafka (Aiven) | `kafka-nautiq.aivencloud.com:12345` |
| `KAFKA_SECURITY_PROTOCOL` | Protocolo de seguridad de Kafka | `SSL` |
| `KAFKA_GROUP_ID` | Identificador del Consumer Group de Flink | `flink-ais-consumer-prod-v1` |
| `KAFKA_TOPIC_POSITIONS` | Tópico de telemetría dinámica | `positions.v1` |
| `KAFKA_TOPIC_STATIC` | Tópico de datos estáticos de buques | `static.v1` |
| `KAFKA_TOPIC_DLQ` | Tópico de errores de contratos | `dead-letter-queue.contracts` |
| `FASTAPI_WEBHOOK_URL` | Endpoint HTTP de la Azure Function para alertas | `https://func-nautiq.azurewebsites.net/api/alerts` |
| `FASTAPI_WEBHOOK_KEY` | Clave de autenticación / Bearer token del webhook | *[Secret]* |
| `FLINK_PARALLELISM` | Número de slots paralelos de ejecución | `2` |
| `FLINK_UI_PORT` | Puerto expuesto para el Web Dashboard | `8081` (DEV) / `8082` (PROD) |
| `FLINK_FORCE_COLD_START` | Si es `true`, ignora Savepoints y arranca limpio | `false` |
| `FLINK_FORCE_UNLOCK` | Si es `true`, remueve locks colgados en ADLS | `true` |
| `CONGESTION_VESSEL_THRESHOLD` | Mínimo de barcos fondeados/atracados para alertar | `1` |
| `ETA_ALERT_HORIZON_HOURS` | Horizonte máximo de ETA dinámico para alertar | `48` |

---

## Guía operativa y despliegue

La raíz del repositorio contiene el script de automatización `run_flink.sh`, que encapsula la construcción de imágenes, configuración de puertos y ejecución.

### Despliegue local (DEV)
```bash
# Construir contenedores y ejecutar orquestador en modo interactivo
./run_flink.sh --env dev

# O en segundo plano (detached)
./run_flink.sh --env dev --detach
```
* **Web UI (local):** [http://localhost:8081](http://localhost:8081)
* **Métricas Prometheus:** [http://localhost:9251/metrics](http://localhost:9251/metrics)

---

### Despliegue en Azure VM (PROD)
En producción, el clúster se despliega sobre una VM Ubuntu On-Demand (`Standard_D2s_v3`, 2 vCPUs, 8 GB RAM):
```bash
# Conectar a la VM de Azure
ssh azureuser@<IP_PUBLICA_VM>

# Navegar a la carpeta del proyecto y ejecutar
cd /home/azureuser/nautiq
./run_flink.sh --env prod --detach
```
* **Web UI (producción):** `http://<IP_PUBLICA_VM>:8082`
* **Métricas Prometheus:** `http://<IP_PUBLICA_VM>:9249/metrics`

---

### Operaciones y monitoreo

#### 1. Comprobar estado de los jobs vía REST API
```bash
curl -s http://localhost:8082/jobs/overview | jq .
```

#### 2. Inspeccionar logs de procesamiento en tiempo real
```bash
# Logs del JobManager / Orquestador
docker logs -f nautiq-prod-jobmanager-1

# Logs del TaskManager (envío de alertas HTTP y escrituras ADLS)
docker logs -f nautiq-prod-taskmanager-1
```

#### 3. Cancelar un job de forma manual
```bash
curl -X PATCH http://localhost:8082/jobs/<JOB_ID>?mode=cancel
```

#### 4. Guardar un savepoint manual en ADLS
```bash
docker exec nautiq-prod-jobmanager-1 flink stop <JOB_ID> \
  --savepointPath abfss://checkpoints@<STORAGE_ACCOUNT>.dfs.core.windows.net/flink_savepoints
```
