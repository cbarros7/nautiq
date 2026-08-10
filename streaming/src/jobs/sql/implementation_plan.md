# Plan de Implementación: Adaptación a Ingesta y Filtrado por Puerto/Buque

## 1. Actualización de Metadatos (Prefijo `_`)
Dado que los contratos ahora incluyen `_ingested_at`, actualizaremos todas las columnas técnicas inyectadas por Flink para que sigan esta convención y no colisionen con los datos de negocio.
**Cambios:**
- En `schema_utils.py`, modificaremos los nombres: `_kafka_ingestion_time`, `_kafka_partition`, `_kafka_offset`, `_flink_processing_time`, `_schema_version`, `_dt`.
- Actualizaremos los archivos `insert_*.sql` y `enriched_positions.sql` para referenciar los nuevos nombres.

## 2. Filtrado de Buques Objetivo en Flink
Dado que AISStream ahora envía todo el bounding box, Flink debe encargarse de dejar pasar **únicamente** los buques de carga (70-79) con destino BCN, Algeciras o Valencia.

### Estrategia de filtrado seguro (Stateful Streaming)
Para no romper los *Watermarks* de Flink necesarios para el cálculo de Spoofing (trigonometría), calcularemos la telemetría de todos los buques del bounding box en memoria, pero **al momento de escribir en el Data Lake**, realizaremos un `JOIN` con el flujo de datos estáticos para descartar los que no cumplen los criterios.

**Lógica de filtrado (Puertos):**
```sql
ship_type BETWEEN 70 AND 79
AND (
    UPPER(destination) LIKE '%VALENCIA%' OR 
    UPPER(destination) LIKE '%ALGECIRAS%' OR UPPER(destination) LIKE '%ALG%' OR
    UPPER(destination) LIKE '%BARCELONA%' OR UPPER(destination) LIKE '%BCN%'
)
```

**Cambios:**
- Crear una nueva vista `sql/target_ships.sql` que contenga los MMSI que cumplen las condiciones.
- Actualizar `insert_static.sql`, `insert_positions_valid.sql` e `insert_spoofing_dlq.sql` para hacer un `INNER JOIN` con `target_ships`.
- Modificar `pipelines/telemetry.py` y `pipelines/static_data.py` para registrar esta nueva vista temporal.

## User Review Required
> [!IMPORTANT]
> **Pregunta sobre `event_time`**: Hemos estado calculando `event_time` a partir de `timestamp` (del contrato Avro) para usarlo en el Watermark. ¿Le añadimos también el prefijo guion bajo (`_event_time`) por ser una columna computada internamente por Flink, o lo dejamos como está?

> [!WARNING]
> **Performance**: Hacer un JOIN entre Telemetría y Estáticos en Flink requiere mantener el estado de ambos en memoria. Hemos configurado el State TTL en 24 horas, por lo que la RAM aguantará sin problema, pero si un barco de carga pierde señal durante más de 24 horas y luego reaparece sin enviar su dato estático primero, Flink no lo escribirá en ADLS hasta que reciba un nuevo evento estático. ¿Estamos de acuerdo con este comportamiento?
