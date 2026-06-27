# Ingestion — adquisición de datos y publicación en Kafka

Tras el refactor, Ingestion tiene **una responsabilidad única**: adquirir datos de
fuentes externas, validarlos con Pydantic contra los contratos de `contracts/`,
serializarlos con **Avro (Schema Registry)** y publicarlos en Kafka. **Sin lógica de
negocio**: nada de plausibilidad, DLQ, enriquecimiento ni maestro de buques — todo
eso vive en Flink (ver `streaming/README.md`).

## Estructura

```
ingestion/src/
  ais/                  # Servicio AIS -> Kafka (production-ready)
    client.py           #   WebSocket AISStream con reconexión + backoff
    models.py           #   Contratos Pydantic (AISPosition, AISStatic) -> dict Avro
    publisher.py        #   Productor SSL + Avro/Schema Registry (MMSI key, ULID header)
    scraper.py          #   Descubre la flota -> Valencia/Algeciras/Barcelona
    tracker.py          #   Consume 2 endpoints -> 2 topics; paralelismo/rate-limit/retry
  reference/            # Cargas puntuales de referencia -> PostgreSQL (Supabase)
    db.py               #   Conexión psycopg + DDL (ports, thetis_mrv) + UPSERTs
    locode.py           #   UN/LOCODE -> tabla ports
    thetis.py           #   THETIS-MRV -> tabla thetis_mrv
  producer.py           # Facade del servicio AIS (scraper + tracker)
  config.py, constants.py
```

## Dos responsabilidades, dos ejecuciones

### 1. Servicio AIS (streaming -> Kafka)
```bash
uv run python main.py
```
- `scraper` descubre la flota de carga con destino a los tres puertos.
- `tracker` consume `PositionReport` + `ShipStaticData`, valida el contrato y publica:

| Endpoint AIS | Topic Kafka | Contrato |
|--------------|-------------|----------|
| PositionReport | `vessel.positions.raw` | `contracts/ais_position_v1.avsc` |
| ShipStaticData | `vessel.static.raw` | `contracts/ais_static_v1.avsc` |

MMSI como **partition key**; ULID de linaje en **headers**. Mensajes que no cumplen
el contrato **no se publican** (no hay DLQ en Ingestion).

### 2. Carga de referencia (point-in-time -> PostgreSQL)
```bash
uv run python -m ingestion.src.reference.locode   # UN/LOCODE -> ports
uv run python -m ingestion.src.reference.thetis   # THETIS-MRV -> thetis_mrv
```
Flink consume estas tablas (LEFT JOIN por IMO / resolución de destino).

## Fuentes de datos (reales)

| Fuente | Procedencia |
|--------|-------------|
| AISStream | WebSocket en vivo (requiere `AISSTREAM_API_KEY` con cuota). |
| UN/LOCODE | `improved-un-locodes` (UNECE + coords OSM/Wikidata); auto-descarga a `data/reference/`. |
| THETIS-MRV | Fichero anual público de EMSA (**descarga manual**, reCAPTCHA) en `data/reference/thetis_mrv.xlsx`. El fichero NO trae DWT/GT directos: el DWT se **deriva** del trabajo de transporte (solo buques que reportan en base dwt). |

### UN/LOCODE: librería vs persistencia (decisión §1)
Se evaluó la librería `locode` de Python: solo da códigos/ciudades, **sin
coordenadas**, por lo que no sirve para enrutar. **Decisión: persistir** el dataset
(con coords) en PostgreSQL — más simple y mantenible, y consultable por Flink/API.

## Configuración (entorno)

`AISSTREAM_API_KEY`, `KAFKA_BROKER_URL` + certs SSL, `KAFKA_SCHEMA_REGISTRY_URL`
(+ `KAFKA_SCHEMA_REGISTRY_AUTH`), `KAFKA_TOPIC_POSITIONS`/`KAFKA_TOPIC_STATIC`,
`PG*` (PostgreSQL), `AIS_MAX_CONNECTIONS`, `PUBLISH_RATE_LIMIT`.

> El código es production-ready pero no se ejecuta contra Supabase/Kafka reales en
> local; configura el entorno y despliega (imágenes ARM64 en OCI).
