# Streaming (Flink) — toda la lógica de negocio

> **Estado: documental.** No se implementa Flink en esta fase. Este README describe
> la arquitectura objetivo y la futura implementación. Ingestion ya publica los
> eventos validados en Kafka; Flink los consume y concentra **toda** la lógica de
> negocio (enriquecimiento, validación semántica, persistencia, alertas).

## Posición en la arquitectura

```
AISStream ─▶ Ingestion (valida contrato + Avro) ─▶ Kafka ─┐
                                                          ▼
                                              ┌──────────────────────┐
   PostgreSQL (ports, thetis_mrv)  ◀── join ──│   Flink (PyFlink)     │
                                              │  lógica de negocio    │
                                              └──────────────────────┘
                                                 │        │        │
                              Delta Lake (maestro)│        │        │ webhook
                              DLQ (Kafka)  ◀──────┘        │        ▼
                                          searoute/meteo ◀─┘    API / Web App
```

Corre en la VM ARM Ampere A1 de OCI (ADR 001), imágenes Docker AArch64.

## Topics de entrada

| Topic | Esquema (`contracts/`) | Origen |
|-------|------------------------|--------|
| `vessel.positions.raw` | `ais_position_v1.avsc` | AIS PositionReport |
| `vessel.static.raw`    | `ais_static_v1.avsc`   | AIS ShipStaticData |

Consumo con `keyBy(mmsi)` (la key de partición ya es el MMSI -> orden causal por buque).

## Responsabilidades de Flink

### 1. Consumo desde Kafka
Source Avro (Schema Registry) sobre los dos topics. Deserializa contra los esquemas
de `contracts/`. Extrae el `correlation_id` (ULID) de los headers para linaje.

### 2. Validación de eventos
Validación **semántica** (la sintáctica/contrato ya la hizo Ingestion):
centinelas AIS (`91`/`181`), null island, rango, **on-land** (`global-land-mask`,
O(1) en memoria) y **salto imposible** (`ValueState` con la última posición por
MMSI, warm-up tras reinicio, umbral >50 kn anti-spoofing).

### 3. DLQ
Los eventos inválidos -> **side output** -> topic `vessel.positions.dlq`,
conservando el ULID. Nunca se descartan en silencio. (Ingestion ya NO gestiona DLQ.)

### 4. Maestro de buques (enriquecimiento)
- Construye/actualiza el maestro desde `vessel.static.raw` (UPSERT por MMSI,
  filtro carga 70-79).
- Enriquece DWT/GT/EEXI con **LEFT JOIN por IMO** contra la tabla de referencia
  `thetis_mrv` (PostgreSQL, poblada por `ingestion/reference/thetis.py`).
- Persiste el maestro en **Delta Lake** (capa de almacenamiento del proyecto).

### 5. Cálculo simple de ATA / disparador JIT
Geometría barata en memoria: ETA crudo = distancia / SOG hacia el puerto destino
(Valencia/Algeciras/Barcelona) + monitor de congestión. Si proyecta llegada
prematura a puerto congestionado, **dispara un webhook** a la API. Flink NO calcula
combustible ni LLM.

### 6. Rutas (SeaRoute)
Distancia/ruta navegable con `searoute` entre la última posición AIS y el puerto
destino (resuelto vía tabla `ports`). Coordenadas siempre `[lon, lat]`.

### 7. Meteo (Open-Meteo, pull)
Consulta **pull** a Open-Meteo con las coordenadas de la ruta para adjuntar el
contexto meteorológico al evento/alerta. (NO se hace en Ingestion.)

### 8. Alertas a la Web App
Webhook a la API (FastAPI) con el payload enriquecido (ETA, ruta, meteo, ULID).
La API ejecuta la capa cognitiva (oráculo matemático + LLM) y emite la recomendación.

## Persistencia

| Destino | Contenido |
|---------|-----------|
| Delta Lake | Maestro de buques enriquecido; telemetría histórica (medallón Bronze/Silver/Gold). |
| Kafka `*.dlq` | Eventos inválidos con ULID para auditoría. |
| PostgreSQL | **Solo lectura** desde Flink: `ports`, `thetis_mrv` (referencia). |

## Implementación futura (pendiente)

- Job PyFlink: sources Avro, `KeyedProcessFunction` con `ValueState`, side outputs.
- Empaquetado ARM64 de `global-land-mask`, `numpy`, `searoute` para los TaskManagers.
- Sink Delta Lake + File Sink (rotación 128 MB / 15 min).
- Cliente Open-Meteo y webhook HTTP a la API.
- Generación de POJOs desde los `.avsc` de `contracts/`.
