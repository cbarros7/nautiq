# Contracts — fuente de verdad de los esquemas

`contracts/` define los esquemas de los eventos que Ingestion publica en Kafka. Es
la **única fuente de verdad**: toda publicación debe cumplir estos contratos y
Flink genera sus POJOs/validaciones a partir de aquí (shift-left, SAD §6.1).

## Esquemas (Avro, compatibles con Schema Registry)

| Fichero | Topic Kafka | Mensaje AIS |
|---------|-------------|-------------|
| `ais_position_v1.avsc` | `vessel.positions.raw` | `PositionReport` |
| `ais_static_v1.avsc`   | `vessel.static.raw`    | `ShipStaticData` |

Se eligió **Avro** por ser el formato de facto en Kafka y estar soportado por
Karapace (Aiven) y `confluent_kafka.schema_registry.avro`. La estrategia de subject
es `TopicNameStrategy` (`<topic>-value`).

## Validación y serialización

1. **Pydantic** (`ingestion/src/ais/models.py`) valida rangos escalares y
   obligatoriedad sobre el mensaje crudo de AISStream (gatekeeping del contrato).
2. El payload validado se **serializa con Avro** contra estos `.avsc` y se publica.
   El **ULID** de linaje viaja en los *headers* de Kafka, no en el payload.

## Evolución

Cambios **aditivos** (campos nuevos con `default`) mantienen compatibilidad
`BACKWARD` en Schema Registry. Para cambios incompatibles, crear `..._v2.avsc` y un
topic nuevo. Los modelos Pydantic pueden modificarse libremente siempre que el
payload serializado siga cumpliendo el `.avsc` vigente.
