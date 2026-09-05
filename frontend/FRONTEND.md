# Frontal de visualización — plan de ejecución

> **Estado.** Quinta pasada: el frontal está **implementado y contrastado contra la tabla
> real**. Los TODOs de §12 están hechos en `feature/math_oracle` (`07086cb`) y hay filas en
> `oracle_recommendations`; §14 recoge la verificación. Este documento pasa de plan a
> memoria de lo construido y de lo que quedó pendiente de otros equipos. Revisado contra
> `feature/math_oracle` en `dbe92d0`
> (*"uv + schema + gitignore"*, 20 ago 2026). El oráculo **ya está implementado de punta a punta y
> ya escribe el contrato**: grafo de 12 nodos con arista condicional, CII, Kwon-Euler, cola de
> atraque, resumen por LLM y persistencia en `oracle_recommendations`. La tabla y su RLS están en
> `ingestion/src/reference/schema.sql`.
>
> Eso invierte la dirección del trabajo: **el contrato ya no se propone, se lee del código.** La
> fuente de verdad de hecho es `construir_evento_contrato()` en
> `api/app/agents/math_oracle.py`. Este documento se ajusta a lo que el oráculo emite hoy, no al
> revés.
>
> **Alcance.** Solo trabajo dentro de `frontend/`. Lo que hace falta fuera está en §12, y ahora son
> pocas cosas y baratas: el oráculo ya cerró casi todo lo que la pasada anterior pedía.
>
> **Qué cambió respecto de la pasada anterior** — resumen para quien ya leyó la v2, detalle en §4.1:
> desaparecen `status` y `confidence` (el frontal los deriva, §7.1), no hay `vessel.name`,
> `port.locode`, `context_radius_nm` ni `snapshot_at` (llegan `null`), aparecen `session_id`, el
> bloque `recommendation.cii` y un `rationale` que es prosa de LLM.

## 1. Principio rector

El frontal **no es el foco del proyecto**. Todo el documento se somete a esa restricción:

- Nada de backend nuevo dedicado al frontal si se puede evitar.
- Nada de estado de servidor propio, colas propias ni auth propia.
- Si una funcionalidad exige datos que no existen, **no entra**: se pinta como "sin dato", no se
  falsea. Con el contrato real en la mano (§4) esto ha pasado de precaución a requisito central:
  hay campos que llegan `null` **siempre**.
- Un solo desarrollador debería poder mantenerlo sin contexto profundo del pipeline.
- El frontal no puede bloquearse esperando a otro componente ni bloquear a ninguno.

Criterio de éxito: **en una demo, se ve un barco acercándose demasiado rápido a un puerto con cola,
y se ve la recomendación del oráculo al lado.** Nada más.

---

## 2. El flujo real

```
AISStream (WebSocket, BBox mediterránea)          ingestion/src/constants.py
    ▼
Kafka Aiven + Schema Registry (Karapace)          contracts/*.avsc
    ▼
Flink                                              streaming/src/jobs/
    ├─ anti-spoofing (LAG por mmsi, umbral 50 kn)  sql/enriched_positions.sql
    ├─ ETA crudo + detección de congestión         anomaly_detection.py
    └─ sink Bronze (parquet, particionado por dt)  abfss://bronze@…/telemetry
    │
    ▼ webhook HTTP — paquete_1 (buque) + paquete_2 (estado del puerto)
      se dispara CADA 30 MIN mientras el buque está a <12 h del puerto
Oráculo matemático — LangGraph, 12 nodos          api/app/agents/math_oracle.py
    │  fetch_datos_buque → fetch_route → fetch_weather → fetch_cii_inicial
    │  → fetch_tiempo_espera (cola de atraque) → fetch_velocidad_jit (Kwon-Euler)
    │  → fetch_cii_jit → build_informe → fetch_historial
    │  → [arista condicional según si el CII mejora o empeora]
    │       ├─ fetch_resumen_ahorro
    │       └─ fetch_resumen_alerta      (informe_llm.py, LLM inyectado; Gemini o determinista)
    │  → publicar_recomendacion
    ▼
oracle_recommendations (Supabase)   ◄── LA FRONTERA (§5)
    │  psycopg directo, db_conn.guardar_recomendacion, ON CONFLICT DO NOTHING
    │  doble uso: contrato con el frontal Y historial que da contexto al LLM
    ▼
Frontal estático (Azure Static Web Apps)
    SELECT al cargar + repesca incremental
```

**Dos consecuencias de la cadencia de 30 minutos**, y las dos afectan al frontal:

1. **El feed no es escaso.** La pasada anterior razonaba sobre "anomalías poco frecuentes". Falso: un
   buque en aproximación genera un evento cada media hora durante hasta 12 h — hasta 24 eventos por
   aproximación. Las reglas de caducidad de marcadores (§5.4) se recalibran con eso.
2. **`session_id` agrupa la aproximación completa.** Eso convierte al frontal en algo mejor que una
   foto: se puede enseñar **cómo evolucionó la recomendación** mientras el buque se acercaba (§7.4).
   Sale gratis, porque la tabla ya lo guarda todo.

### Sobre emitir en paralelo a Bronze

El frontal puede mostrar una recomendación que falló al persistirse en Bronze. Para un frontal de
demostración es un intercambio aceptable — pero no lo es si algún día alguien concilia lo que se vio
en pantalla contra la capa analítica. Si eso llega a importar, el orden pasa a ser
*persistir → emitir*, y el frontal asume la latencia extra.

---

## 3. Procedencia de cada dato

Lo que el frontal recibe **de verdad**, hoy, con el oráculo en `dbe92d0`.

| Dato | En el evento | Estado real |
| :-- | :-- | :-- |
| `mmsi`, `lat`, `lon`, `speed_kn`, `heading`, `nav_status` | `vessel.*` | ✅ del webhook (`paquete_1`) |
| `imo` | `vessel.imo` | ✅ del webhook |
| `destination_raw`, `eta_ais_raw` | `vessel.*` | ✅ crudos, sin normalizar |
| `is_container` | `vessel.is_container` | ✅ derivado del `tipo_normalizado` del CII |
| **Nombre del buque** | `vessel.name` | ❌ **siempre `null`** — se etiqueta por MMSI (§7.2, **TODO 2**) |
| Nombre del puerto | `port.name` | ✅ texto del webhook (`"ALGECIRAS"`), **no un locode** |
| **LOCODE del puerto** | `port.locode` | ❌ **siempre `null`** — el webhook manda lat/lon, no se resuelve contra `ports` |
| lat/lon del puerto | `port.lat/lon` | ✅ del webhook |
| **Radio de contexto** | `port.context_radius_nm` | ❌ **siempre `null`** — no se dibuja el círculo (§7.3) |
| **Hora del snapshot** | `port.snapshot_at` | ❌ **siempre `null`** — se usa `emitted_at` como sustituto rotulado |
| Conteos de puerto | `port.berthed_count` · `anchored_count` · `inbound_count` | ✅ longitudes de las listas de `paquete_2` |
| Buques del contexto | `context_vessels.berthed/anchored/inbound` | ✅ con `mmsi`, `lat`, `lon`; **`name` siempre `null`** |
| Espera de cada buque | `context_vessels.*.estimated_wait_hours` | ✅ **MODELADA** por `jit_calculus`, no observada — el nombre del campo lo dice y la UI también debe decirlo |
| Ruta navegable | `route.distance_nm` · `duration_hours` · `waypoints` | ✅ SeaRoute |
| Estado del mar en ruta | `route_weather[]` (ola + viento + ETA por waypoint) | ✅ Open-Meteo, ola y viento ya fusionados por waypoint |
| Velocidad recomendada | `recommendation.recommended_speed_kn` · `speed_delta_kn` | ✅ Kwon-Euler |
| ETAs | `recommendation.eta_current` · `eta_optimized` | ✅ · `eta_current` es `null` si el webhook no manda `ETA_dynamic` |
| Horas de ralentí evitadas | `recommendation.idle_hours_avoided` | ✅ · `null` sin `ETA_dynamic` |
| **CII antes / después** | `recommendation.cii.inicial` · `jit` · `ahorro_pct` · `metodo` | ✅ **nuevo y muy pintable** (§7.5) |
| Combustible ahorrado | `recommendation.fuel_saved_t` | ⚠️ **solo si `thetis_mrv` da DWT real** para ese IMO; si no, `null`. Decisión deliberada del oráculo |
| Señales de fiabilidad | `recommendation.convergio` · `excede_v_diseno` · `nota` · `alerta_cii` | ✅ sustituyen a `status`/`confidence` (§7.1) |
| Justificación en prosa | `recommendation.rationale` | ✅ **texto de LLM** (Gemini, o determinista sin clave), coherente entre avisos de la misma sesión |
| **Posición en cola y espera del buque objetivo** | — | ❌ **se calcula y no se emite** (**TODO 1**, es la justificación de la recomendación) |
| Ocupación del puerto en % / atraque libre | — | ❌ fuera de alcance |
| Ahorro en € | — | ❌ fuera de alcance |

---

## 4. El contrato del evento

**Fuente de verdad de hecho: `construir_evento_contrato()` en `api/app/agents/math_oracle.py`.**
`contracts/oracle_recommendation_v1.schema.json` está referenciado en dos sitios — el comentario de
la tabla en `schema.sql` y el docstring de `math_oracle` — pero **el fichero no existe todavía**.
Escribirlo es trabajo del frontal y es la fase 0 (§10), porque es quien más lo necesita: se
**extrae** ejecutando el `__main__` del grafo y capturando `evento_contrato`, no se inventa.

Este es el evento tal como sale hoy, anotado con lo que el frontal puede dar por bueno:

```jsonc
{
  "event_id": "01M08APDG115DX8X6KEKVXKHQE",   // = correlation_id del webhook; clave de idempotencia
  "session_id": "01M08B...",                  // agrupa la aproximación (mismo mmsi+puerto, hueco <24h)
  "emitted_at": "2026-08-20T11:45:30Z",
  "schema_version": 1,

  "vessel": {
    "mmsi": 352986151,          // ⚠️ NÚMERO aquí; la columna `mmsi` de la tabla es text (§5.3)
    "imo": 9520675,
    "name": null,               // SIEMPRE null
    "lat": 35.9836, "lon": -5.3651,
    "speed_kn": 9.8,
    "heading": 74.0,            // de paquete_1["direccion"]; puede faltar
    "nav_status": 0,            // código AIS numérico
    "destination_raw": "ALGECIRAS",
    "eta_ais_raw": "2026-08-17 18:00:00",
    "position_at": "2026-08-20T11:44:10Z",
    "is_container": false
  },

  "port": {
    "locode": null,             // SIEMPRE null
    "name": "ALGECIRAS",        // nombre, no locode — así se etiqueta en el mapa
    "lat": 36.12972, "lon": -5.42278,
    "context_radius_nm": null,  // SIEMPRE null
    "berthed_count": 2,
    "anchored_count": 2,
    "inbound_count": 3,         // ⚠️ INCLUYE al propio buque objetivo (§7.2)
    "snapshot_at": null         // SIEMPRE null
  },

  "context_vessels": {
    "berthed":  [ { "mmsi": 538009654, "name": null, "lat": 36.1209, "lon": -5.4180 } ],
    "anchored": [ { "mmsi": 538006140, "name": null, "lat": 36.1567, "lon": -5.4210,
                    "estimated_wait_hours": 6.3 } ],   // MODELADA, no observada
    "inbound":  [ { "mmsi": 636017075, "name": null, "lat": 36.2601, "lon": -4.9511,
                    "estimated_wait_hours": 9.1 } ]    // sin distance_nm ni eta_estimated
  },

  "route": {
    "distance_nm": 18.4,
    "duration_hours": 1.9,
    "waypoints": [[-5.3651, 35.9836], [-5.4228, 36.1297]]   // [lon, lat]
  },

  "route_weather": [
    { "lat": 35.9836, "lon": -5.3651, "eta": "2026-08-20T11:45:00Z",
      "wave_height": 1.4, "wave_direction": 210, "wave_period": 6.2,
      "wind_speed_kn": 17.3, "wind_direction": 205, "wind_gusts_kn": 24.1 }
  ],

  // Justificacion de la recomendacion: la cola de ESTE buque. A nivel raiz, hermano de
  // `recommendation`, porque describe el estado del mundo, no la decision.
  "queue": {
    "estimated_wait_hours": 129.0,
    "queue_position": 5,
    "berth_segment": "large"               // los atraques se agrupan por eslora
  },

  "recommendation": {
    "recommended_speed_kn": 6.4,
    "speed_delta_kn": -3.4,
    "eta_current": "2026-08-20T12:41:00Z",   // null si el webhook no manda ETA_dynamic
    "eta_optimized": "2026-08-20T14:38:00Z",
    "idle_hours_avoided": 1.9,               // null si no hay ETA_dynamic. OJO: es EXPOSICION
                                             // al fondeo, no ahorro. Ver §7.9
    "fuel_saved_t": null,                    // null si thetis_mrv no da DWT real
    "rationale": "…",                        // PROSA de LLM, varios párrafos posibles

    // Señales nativas del cálculo. NO hay status ni confidence: los deriva el frontal (§7.1)
    "convergio": true,
    "excede_v_diseno": false,
    "alerta_cii": false,
    "nota": null,
    "weather_speed_loss_pct": 1.6,           // correccion Kwon: cuanto se come el mar
    "cii": { "inicial": 12.8, "jit": 11.1, "metodo": "eexi", "ahorro_pct": 13.3 }
  }
}
```

### 4.1 Las desviaciones respecto de lo que se propuso, y por qué se aceptan

El oráculo se apartó del contrato de la pasada anterior en cinco puntos, y **los cinco están bien
razonados**. Se aceptan tal cual; lo que cambia es el frontal.

| Se propuso | Se implementó | Veredicto |
| :-- | :-- | :-- |
| `status` (`ok/alert/critical`) y `confidence` | Nada de eso; se exponen `convergio`, `excede_v_diseno`, `alerta_cii`, `nota`, `cii.metodo` | ✅ **Mejor.** Un `status` en el oráculo habría sido una regla de presentación disfrazada de dato. Las señales nativas son verificables; el mapeo a color es del frontal y va en un solo fichero (§7.1) |
| `wait_hours` + `anchored_since` | `estimated_wait_hours` | ✅ **Mejor.** El nombre delata que es un valor modelado por `jit_calculus`, no observado por un tracker con estado. Y de paso desaparece la dependencia del TTL de 24 h de Flink |
| `fuel_saved_t` estimado siempre | Solo con DWT real de `thetis_mrv`; `null` si no | ✅ **Mejor.** Un ahorro calculado sobre un DWT geométrico tiene la incertidumbre del propio DWT. `null` es más honesto que un número que nadie puede defender |
| `locode` como columna e identidad | `puerto` (nombre) como columna, `locode` a `null` | ⚠️ **Aceptado.** El webhook manda lat/lon del puerto, así que no hay resolución nombre→LOCODE. El frontal etiqueta por nombre. Coste: no se puede unir con `ports` ni agrupar dos grafías del mismo puerto |
| — | `session_id` | ✅ **Añadido y valioso.** Es lo que permite el panel de evolución de §7.4 |
| `recommendation.queue` | `queue` a nivel raíz | ✅ **Mejor.** La cola es estado del mundo, no parte de la decisión. El esquema se movió a donde está el dato (§13) |
| `queue.kwon_loss_pct` | `recommendation.weather_speed_loss_pct` | ✅ **Mejor nombre.** Dice qué mide, no de qué fórmula sale |

---

## 5. El modelo de comunicación oráculo → frontal

### 5.1 La tabla es la frontera

El frontal lee **una tabla de Supabase y nada más**. No conoce al oráculo, ni su URL, ni su ciclo de
despliegue. Esto ya no es una propuesta: está implementado y documentado en el propio
`schema.sql`, que describe la tabla como *"frontera de contrato entre `api/` (que escribe) y
`frontend/` (que sólo lee)"*.

La tabla tiene **doble uso**, y conviene tenerlo presente: además de alimentar al frontal, es el
historial que `fetch_historial` consulta para dar contexto al LLM entre avisos sucesivos. Una
consecuencia práctica: **la tabla no se puede purgar agresivamente** sin degradar la coherencia de
los resúmenes. Cualquier retención tiene que respetar la ventana de 24 h que usa
`get_historial_recomendaciones`.

### 5.2 La tabla, tal como está

En `ingestion/src/reference/schema.sql` (no en `infrastructure/`, como se propuso — vive junto a
`ports` y `thetis_mrv`, que es coherente):

```sql
CREATE TABLE IF NOT EXISTS oracle_recommendations (
    event_id     text PRIMARY KEY,   -- ULID, = correlation_id del webhook
    session_id   text NOT NULL,      -- agrupa la misma aproximación buque/puerto (hueco < 24h)
    emitted_at   timestamptz NOT NULL DEFAULT now(),
    mmsi         text NOT NULL,
    puerto       text NOT NULL,      -- NOMBRE del puerto, no locode
    alerta_cii   boolean NOT NULL,   -- CII con velocidad JIT peor que el inicial
    payload      jsonb NOT NULL      -- evento completo (oracle_recommendation_v1)
);
-- + índices por emitted_at, (session_id, emitted_at), (mmsi, puerto, emitted_at)
-- + RLS: SELECT para anon, sin policy de escritura
```

Las cuatro columnas promovidas **no** son las que se propusieron, y las que hay son mejores para el
frontal de lo que parece:

- **`alerta_cii`** permite filtrar *"enséñame solo lo preocupante"* sin abrir el `jsonb`.
- **`session_id`** permite traer una aproximación completa con un índice dedicado.
- **`puerto`** permite el filtro por puerto de §13 sin parsear el payload.
- **No hay `status` ni `confidence`** porque el oráculo no los emite (§4.1). El frontal los deriva.

### 5.3 Escritura — ya hecha, del lado del oráculo

`db_conn.guardar_recomendacion` con **psycopg directo**, no PostgREST. Resuelve la idempotencia con
`ON CONFLICT (event_id) DO NOTHING` — el propio docstring señala que consigue lo mismo que el
`Prefer: resolution=ignore-duplicates` que se había pedido, sin salir de psycopg. Correcto, y una
dependencia menos.

Dos cosas que el frontal debe asumir de esa escritura:

- **`mmsi` es `text` en la columna y número en el `payload`.** El frontal **normaliza a string** al
  entrar (`String(payload.vessel.mmsi)`) y usa eso como clave del `Map`. Si no, `context_vessels` y
  `vessel` no se cruzan de forma fiable.
- **`puerto` es texto libre del webhook.** `"ALGECIRAS"` y `"Algeciras"` serían dos puertos
  distintos para la tabla. El frontal agrupa por el valor tal cual y no pretende arreglarlo.

Queda un punto abierto del lado del oráculo: **un fallo al publicar hace fallar el nodo**, y con él
el grafo entero. Es **TODO 3**.

### 5.4 Lectura — lado frontal

Un solo cliente, `@supabase/supabase-js`:

```ts
// frontend/src/feed.ts
// 1. Arranque en frío: las últimas 50 decisiones (resuelve el mapa vacío).
const { data } = await sb.from('oracle_recommendations')
  .select('*').order('emitted_at', { ascending: false }).limit(50)

// 2. Repesca incremental cada 30 s: solo lo posterior a lo ya visto.
const { data: nuevas } = await sb.from('oracle_recommendations')
  .select('*').gt('emitted_at', ultimoVisto).order('emitted_at', { ascending: true })

// 3. Una aproximación completa, para el panel de evolución (§7.4).
const { data: sesion } = await sb.from('oracle_recommendations')
  .select('*').eq('session_id', id).order('emitted_at', { ascending: true })
```

Estado en memoria: `Map<string /* mmsi */, Evento>` con el evento más reciente de cada buque, más
`Map<string /* session_id */, Evento[]>` para el panel de evolución.

**Reglas de caducidad, recalibradas a la cadencia real de 30 min** (§2). La versión anterior usaba
30 min / 6 h, que se escribió pensando que las alertas eran raras; con un aviso cada media hora,
30 minutos de silencio ya es una señal:

| Antigüedad del último evento | Comportamiento | Por qué |
| :-- | :-- | :-- |
| < 40 min | plena opacidad | un ciclo de 30 min más margen de jitter |
| 40 min – 3 h | atenuado, con la antigüedad en el hover | se han perdido de 1 a 5 ciclos: puede ser un hueco o el fin de la aproximación |
| > 3 h | se retira del mapa | la aproximación terminó (el buque salió de la ventana de <12 h) |

La sesión sigue consultable en el historial aunque el marcador desaparezca del mapa.

**La `anon key` va en el bundle y es pública.** Es el diseño de Supabase: lo que protege la base es
la RLS, no el secreto de la clave. Se inyecta en build como `VITE_SUPABASE_URL` /
`VITE_SUPABASE_ANON_KEY`. Las credenciales `PG*` que usa `db_conn.py` **jamás** tocan el frontal.

### 5.5 Por qué repesca y no Realtime ni WebSocket

| Opción | Infra nueva | Arranque en frío | Veredicto |
| :-- | :-- | :-- | :-- |
| **Tabla + repesca cada 30 s** ⭐ | ninguna | ✅ el mismo `SELECT` | **Elegida.** Con eventos cada 30 min, 30 s de latencia es ruido. Cero servidor, y el frontal queda desacoplado del despliegue del oráculo |
| Supabase Realtime | ninguna | ✅ | ~5 líneas más, pero exige habilitar replicación y razonar RLS sobre el canal. **Preparado, no activado** (§13) |
| WebSocket en el App Service | ninguna | ❌ | Exige habilitar WebSockets en App Service y *sticky sessions* con más de una instancia. Y acopla la conexión al ciclo de despliegue del oráculo |
| Topic Kafka nuevo | ninguna | ❌ | Un navegador no habla Kafka: la opción anterior **más** un relay |
| Event Hub / Web PubSub · Redis | sí | ❌ | Infra nueva para un problema que Postgres ya resuelve |

La cadencia de 30 minutos refuerza la decisión: **el argumento de "hace falta tiempo real" se cae
solo** cuando la fuente emite dos veces por hora.

Contrapartida honesta: ata el frontal al SDK de Supabase. Son ~300 líneas de TS. Aceptable.

### 5.6 Arranque en frío y retención

El `SELECT` inicial es la respuesta a *"¿qué está pasando ahora?"*. No es una API sobre el pipeline:
es leer resultados ya calculados, los mismos que se emiten en vivo.

**Retención: no tocar por ahora.** Y con un motivo nuevo respecto de la pasada anterior: la tabla es
también el historial del LLM (§5.1). Cualquier purga debe dejar intacta la ventana de 24 h de
`get_historial_recomendaciones`, así que un borrado de >30 días es seguro y uno más agresivo no.

---

## 6. Python o TypeScript

El monorepo es `uv` y Python es la preferencia. En el navegador no cabe, y conviene el argumento
explícito antes que la excusa:

- El destino es **Azure Static Web Apps**: activos estáticos, sin servidor. **Streamlit, Dash o
  Panel exigen un proceso vivo** — App Service o Container App: créditos, una región que elegir, y
  el frontal acoplado a un recurso de cómputo. Contradice §1 y tira la mejor propiedad del plan.
- Python en el navegador es **Pyodide**: ~10 MB antes del primer pixel, para un mapa que tiene que
  sentirse instantáneo en una demo.
- La capa de mapa (MapLibre GL, WebGL) es JS de todos modos; envolverla en Python añade una capa sin
  quitar la de abajo.

**Decisión: TypeScript en el navegador, y el contrato canónico versionado en `contracts/`.** El
monorepo se reparte por responsabilidad:

| Pieza | Lenguaje | Vive en |
| :-- | :-- | :-- |
| Esquema del evento | JSON Schema | `contracts/oracle_recommendation_v1.schema.json` — junto a los `.avsc` |
| Emisión y validación | Python | `api/`, miembro del workspace `uv` |
| Tipos del frontal | TypeScript **generado** | `frontend/src/types.ts`, vía `npm run gen:types` |
| Mapa y panel | TypeScript | `frontend/` |

`frontend/` queda **fuera** de `[tool.uv.workspace] members`: es JS, su ciclo de vida es `npm`.

**Con el oráculo ya implementado, la dirección se invierte:** el esquema se extrae del evento que el
grafo emite hoy, y a partir de ahí pasa a ser el contrato que ambos lados respetan. Escribirlo a
mano "como debería ser" es lo único que garantizaría que no coincide con la realidad.

---

## 7. Qué se pinta

```
              🚢 352986151 · IMO 9520675  ── 9.8 kn → 6.4 kn ──▶   (ámbar)
                ╲
                 ╲  ruta navegable teñida por altura de ola   ← elemento principal
                  ╲___
                      ◉  ALGECIRAS                            ← nombre, NO locode
                     ╱ ╲   2 atracados · 2 fondeados · 3 en camino
              ⚓ ⚓  ▪▪  🔵🔵                                   ← conteos del evento, sin radio
            fondeados atrac. en camino
```

### 7.1 El estado visual lo deriva el frontal

El oráculo **no emite `status` ni `confidence`**, y con razón (§4.1). El frontal los deriva de las
señales nativas, **en un solo fichero** (`src/status.ts`) para que la regla sea auditable y no esté
repartida por los componentes:

> **Corregido tras implementar.** La versión anterior de este documento usaba
> `convergio === false` como alerta. **Es un error**, y lo demuestran los datos: sobre 11
> eventos reales del oráculo, `convergio` es `false` en 7. Habría pintado de rojo casi
> todo el mapa.
>
> `convergio` **no es un indicador de error, es un indicador de saturación**, y cubre dos
> situaciones opuestas que `nota` distingue en prosa: *«sobra tiempo incluso a v_min»* —- que
> es el caso BUENO del JIT, hay que frenar al mínimo, y es además el más frecuente— y
> *«la ventana no llega ni a v_max»*, que sí merece atención. El discriminador robusto es
> el signo de `speed_delta_kn`, no una coincidencia de cadenas sobre `nota`.

Implementado en `src/status.ts`:

```ts
// Eje 1 — severidad, decide el COLOR del buque y de la ruta
critical  ⟵  recommendation.excede_v_diseno === true
              // la recomendación pide más velocidad que la de diseño del casco:
              // no es ejecutable y el buque llegará tarde de todos modos
alert     ⟵  recommendation.alerta_cii === true
              // es ejecutable, pero CUESTA emisiones: el oráculo mismo enrutó a
              // fetch_resumen_alerta porque el CII empeora al seguirla
ok        ⟵  el resto — frenar mejora el CII, que es lo que justifica el proyecto

// Eje aparte — saturación, es una INSIGNIA, no severidad
'ninguna'            ⟵  convergio === true
'frenando-al-minimo' ⟵  !convergio && speed_delta_kn < 0    // el caso bueno
'a-maxima-velocidad' ⟵  !convergio && speed_delta_kn > 0    // no llega ni a tope

// Eje 2 — fiabilidad, decide la ATENUACIÓN y el rótulo. Nunca oculta nada
baja      ⟵  cii.metodo === "fallback_admiralty"
              // el CII sale de un DWT geométrico, no del EEXI declarado
alta      ⟵  cii.metodo === "eexi" && fuel_saved_t !== null
media     ⟵  el resto (que en la práctica es casi todo: ver §3, `fuel_saved_t`)
```

Sobre el fixture, esto reparte 4 `ok`, 4 `alert` y 3 `critical` —- un mapa que informa.

Dos reglas sobre esto, y son de las que separan un mapa útil de uno que engaña:

- **`nota` se enseña siempre que no sea `null`.** Es el aviso que Kwon-Euler escribe sobre su propia
  solución; suprimirlo es esconder la letra pequeña del número grande.
- **La fiabilidad baja se rotula, no solo se atenúa.** Un color más pálido no comunica *"este CII es
  geométrico"*. El texto sí.

### 7.2 Los buques: sin nombre, y con un duplicado

- **No hay `vessel.name`.** La etiqueta es el **MMSI**, con el IMO como segunda línea si viene. Es
  peor de leer y no hay nada que hacer en el frontal — pero sí hay un arreglo barato del lado del
  oráculo: **TODO 2**.
- **El buque objetivo aparece también en `context_vessels.inbound`.** Está confirmado en el ejemplo
  del propio `math_oracle.__main__`: el mmsi `352986151` viene en `num_buques_en_camino`. Sin
  filtrar, el mapa lo pinta dos veces y el conteo `inbound_count` lo cuenta a él mismo. **El frontal
  deduplica por `mmsi` contra `vessel.mmsi`** y rotula el conteo como *"3 en camino (incluido este)"*
  en vez de restar en silencio.
- **La orientación es `heading`, y puede faltar.** Sin él, círculo, no casco: no se inventa un
  rumbo.
- **Nunca interpolar posiciones.** Cada buque se dibuja en su último fix, con `position_at` visible.

### 7.3 El puerto: sin radio y sin hora de snapshot

- **La etiqueta es `port.name`**, no un LOCODE. `port.locode` llega `null` siempre.
- **No se dibuja el círculo de contexto.** `context_radius_nm` llega `null`, así que dibujarlo
  exigiría inventarse el radio — exactamente lo que §1 prohíbe. En su lugar, los conteos se rotulan
  como *"contexto del puerto según el evento"*, sin sugerir una geometría que no conocemos.
- **`snapshot_at` llega `null`**, así que la hora del contexto es `emitted_at`, **rotulada como tal**:
  *"contexto a las 11:45 (hora de emisión)"*. Es una aproximación y la UI lo dice.

### 7.4 El panel: la sesión, no la foto

Aquí está la mejor consecuencia de `session_id`. Un buque en aproximación genera hasta 24 eventos, y
la tabla los guarda todos. El panel enseña:

1. **La recomendación actual** — velocidad actual → recomendada, ETAs, horas de ralentí evitadas.
2. **El `rationale` del LLM**, como prosa. Es coherente entre avisos de la misma sesión porque
   `fetch_historial` le pasa los tres anteriores: se puede leer la secuencia y tiene sentido.
3. **La evolución de la sesión** — velocidad recomendada y `cii.ahorro_pct` a lo largo de la
   aproximación. Es lo que demuestra que el sistema *reacciona* en vez de opinar una vez.
4. **El perfil de ola y viento contra distancia**, con el punto actual del buque marcado.
5. **La cola del puerto** — las tres listas con su `estimated_wait_hours`, **rotulado *estimada***.

### 7.5 El CII, antes y después

`recommendation.cii` es nuevo y es la prueba visual más directa del valor del proyecto: el mismo
buque, la misma ruta, dos velocidades, dos CII. Se pinta como par antes/después con el
`ahorro_pct` — y con `metodo` a la vista, porque un CII por `eexi` y uno por `fallback_admiralty` no
son comparables entre buques (así lo documenta `thetis_mrv.technical_efficiency`).

Cuando `ahorro_pct` es negativo, es el caso `alerta_cii`: frenar empeora el CII. **Ese caso se pinta,
no se esconde.** Es el resultado más interesante que produce el oráculo.

### 7.6 Tabla de elementos

| Elemento | Forma | Color | Interacción |
| :-- | :-- | :-- | :-- |
| **Ruta navegable** | polilínea de `route.waypoints` | **teñida por `wave_height`** por tramo | hover → ola, viento y ETA de ese waypoint |
| Buque con novedad | silueta de casco a `heading`, círculo si falta | severidad del eje 1 (§7.1) | clic → panel de sesión (§7.4) |
| Puerto | círculo + **nombre** | neutro; borde ámbar si `anchored_count > 0` | clic → las tres listas del contexto |
| Atracados | rectángulo pequeño | gris oscuro | hover → MMSI |
| Fondeados | ancla pequeña | gris | hover → MMSI + espera **estimada** |
| En camino | triángulo pequeño | azul | hover → MMSI + espera **estimada** |

Reglas de honestidad que se mantienen: el color codifica el estado de la recomendación, **no la
velocidad**; se muestran **conteos**, nunca porcentajes de ocupación; la ruta es **calculada**, no
la derrota observada, y se dibuja punteada y rotulada como *ruta prevista*; y las posiciones no se
interpolan.

### 7.7 Rectificación: la honestidad no se narra

La primera versión del panel rotulaba cada ausencia y cada matiz de procedencia: *«sin DWT real en
THETIS-MRV para este IMO»*, *«CII declarado (EEXI), sin DWT real»*, *«estimada, no observada»*, *«el
evento no trae el radio con que se armó el contexto»*. La intención era no afirmar más de lo que el
dato aguanta. El efecto era el contrario del buscado: **una pantalla que parece disculparse
transmite que el sistema no tiene datos**, y el ruido tapaba el número que importa.

La regla correcta es más simple, y es la que rige ahora:

- **Lo que no hay, no se muestra.** Si `fuel_saved_t` es `null`, no aparece la métrica —- ni vacía, ni
  con un guion, ni con una nota. Omitir no es ocultar: es no afirmar. Enseñar un hueco rotulado sí
  era afirmar algo, y lo que afirmaba era «aquí falta algo».
- **El matiz de procedencia solo se rotula si cambia la lectura.** Un CII por
  `fallback_admiralty` no es comparable con el de otro buque, así que lleva un rótulo: **una
  palabra**, «estimado», con la explicación completa en el `title`. Un CII por EEXI no lleva nada,
  porque no había nada que advertir.
- **Mejor arreglar el dato que explicarlo.** `port.inbound_count` incluye al propio buque, y eso
  obligaba a una nota aclarando por qué la lista de abajo tenía uno menos. Ahora el conteo se hace
  sobre el contexto ya deduplicado (`es_objetivo`): el número sale correcto y no hay nada que
  aclarar.
- **La jerga del cálculo va al tooltip.** La `nota` de Kwon (*«sobra tiempo incluso a v_min_kn…»*)
  decía en jerga lo mismo que la etiqueta de saturación en claro. Se conserva como `title`.

Lo que **no** cambia: no se inventa un rumbo que no existe, no se interpolan posiciones, no se
presenta una ruta calculada como observada y no se convierte una estimación en una medida. La
honestidad está en no afirmar, no en narrar lo que falta.

### 7.8 El objetivo es llegar a tiempo, no navegar despacio

El panel lideraba con el CII y enterraba las horas de fondeo evitadas en una celda pequeña. Estaba
mal jerarquizado: el proyecto existe para que un buque **llegue cuando hay atraque libre** y no
queme combustible esperando fondeado. El ahorro de emisiones es la consecuencia de esa decisión, no
su objetivo.

Ahora el bloque principal se llama *Llegada Just-In-Time*, y el número más grande del panel es
`idle_hours_avoided` —- las horas que el buque no pasa fondeado—, por encima de la velocidad y muy
por encima del CII, que baja a sección secundaria. Las etiquetas de estado dejaron de hablar de CII
y hablan de llegada, sin cambiar las señales que las deciden:

| Señal del oráculo | Antes | Ahora |
| :-- | :-- | :-- |
| `excede_v_diseno` | «No ejecutable» | **«No llega a tiempo»** |
| `alerta_cii` | «Frenar empeora el CII» | **«Llega a tiempo, emitiendo más»** |
| resto | «Frenar mejora el CII» | **«Llega a tiempo emitiendo menos»** |
| `!convergio` y frena | «Slow steaming máximo» | **«Incluso al mínimo llega antes de tener atraque»** |
| `!convergio` y acelera | «A máxima velocidad» | **«Ni a máxima velocidad alcanza el hueco»** |


### 7.9 `idle_hours_avoided` no son horas ahorradas

El nombre del campo engaña, y el panel lo amplificaba a titular. El oráculo lo calcula así:

```
idle_hours_avoided = espera_hasta_atraque − ETA_dynamic
```

Es decir: **las horas que el buque pasaría fondeado si no cambia nada**. Eso coincide con las
horas *evitadas* solo cuando Kwon-Euler consigue estirar la travesía hasta la ventana de
atraque — cuando `convergio` es `true`.

En el caso saturado al mínimo no coincide en absoluto. MSC PRATITI, con los números reales del
fixture:

| | |
| :-- | :-- |
| Distancia | 36,7 nm |
| Travesía a 14,2 kn (actual) | 2,6 h |
| Travesía a 9,8 kn (recomendada) | 3,8 h |
| Atraque libre en | 63,6 h |
| Fondeo si no cambia nada | **61,0 h** |
| Fondeo siguiendo la recomendación | **59,8 h** |
| Fondeo realmente evitado | **1,2 h** |

El panel anunciaba «61 h menos fondeado quemando combustible». Lo cierto es que va a fondear
unas 60 h de todos modos: frenar de 14,2 a 9,8 kn no puede rellenar un hueco de 61 h con una
travesía de 3 h. Lo que la recomendación consigue ahí es **gastar menos en el trayecto** (CII
+52,9 %), no evitar el fondeo.

No era un caso raro: pasa en **7 de los 14 eventos del fixture y en los 3 de la tabla real**.
Es decir, el titular era falso en el 100 % de los datos de producción.

Corregido separando los dos enunciados, con la misma cifra:

- `convergio === true` → «X h menos fondeado quemando combustible, llegando cuando se libera el
  atraque». Legítimo: el buque sí alcanza la ventana.
- saturado al mínimo → «X h fondeado esperando atraque, incluso frenando al mínimo. Reducir la
  velocidad no lo evita: recorta el consumo de la travesía». Misma cifra, enunciado verdadero, y
  sin el color de estado, que ahí se leía como un logro.

### 7.10 El caso que el proyecto persigue existe, y es una franja estrecha

Al enunciar §7.9 quedó a la vista algo incómodo: en las primeras 14 grabaciones **ninguna**
llegaba a tiempo ahorrando combustible. Las que convergían lo hacían **acelerando** (y el CII
empeoraba); las que ahorraban combustible **fondeaban igual**. Y el proyecto persigue las dos
cosas a la vez.

No era casualidad de los escenarios: es geometría. Para llegar JIT **frenando** hace falta que
la espera caiga en una franja concreta:

```
travesía a velocidad actual   <   espera hasta atraque   <   travesía a velocidad mínima
```

- Si la espera es **menor** que la travesía actual → hay que acelerar → el CII empeora.
- Si es **mayor** que la travesía al mínimo → ni frenando al máximo se llena el hueco →
  fondea igual.

La anchura de esa franja es el rango del casco: `v_actual / v_min`, o sea como mucho un factor
de ~1,7. Con el modelo de esperas actual produciendo **20–185 h** frente a travesías de **3–30
h**, casi todos los casos se salen por arriba.

Buscándolo a propósito, el caso aparece y es el que hay que enseñar:

| `SALGUEIRO` → Valencia | |
| :-- | :-- |
| Velocidad | 17,5 → **13,0 kn** (frena 4,5) |
| Travesía a velocidad actual | 15,9 h |
| Atraque libre en | 21,9 h (1.º en cola, segmento *medium*) |
| Fondeo evitado | **6 h** — llega justo cuando se libera el atraque |
| CII | 14,74 → 8,10 (**+45,1 %**) |

Llega a tiempo **y** emite un 45 % menos por milla. Sin ancla, chip verde, y la aritmética
cuadra en pantalla: 22 − 16 = 6.

**Lo que esto dice del sistema, y no del frontal:** que el caso bueno sea 1 de 15 depende
directamente de lo grandes que sean las esperas que estima `jit_calculus`. Si esas esperas
están sobreestimadas —- y 129 h para el 5.º de la cola implica ~26 h de servicio por buque—, el
sistema dirá «fondeará igual» casi siempre y el JIT quedará inutilizado en la práctica. Es la
misma pregunta de negocio de §13, ahora con una consecuencia concreta y medible.

### 7.11 El color dice una cosa y el titular otra, a propósito

Al enunciar bien §7.9 saltó una contradicción en cascada: el chip de MSC PRATITI decía
«Llega a tiempo emitiendo menos» justo encima de «61 h fondeado». La etiqueta de estado se
derivaba de la severidad sola, que no mira la saturación.

Los dos ejes están ahora separados y dicen cosas distintas porque **miden cosas distintas**:

| | Qué codifica | Valores |
| :-- | :-- | :-- |
| **Color** (mapa, lista, chip) | calidad del **ajuste de velocidad** | reduce emisiones · las aumenta · no ejecutable |
| **Titular** (`titular()`) | el **resultado JIT** de este evento | fondeará igual · llega a tiempo (emitiendo más o menos) · necesita más velocidad de la de diseño |
| **⚓** (`fondearaIgual()`) | el buque **va a fondear** haga lo que haga | presente / ausente |

Por eso un buque puede salir en **verde con ancla**: frenar es buen consejo (menos emisiones) y
aun así va a esperar fondeado, porque el puerto está saturado. Son dos hechos verdaderos a la
vez, y colapsarlos en un solo eje obligaba a mentir en uno de los dos.

El símbolo no es decoración: **7 de los 14 eventos del fixture y los 3 de la tabla real** lo
llevan. Sin él, media flota sale en verde y el mapa sugiere que el JIT está funcionando cuando
lo que pasa es que el puerto no da atraque. El glifo del chip sigue al titular por lo mismo: un
«✓» junto a «fondeará igual» se contradice.

**Consecuencia para §15:** dar la cifra *real* de horas evitadas en el caso saturado exige
`tiempo_transito_estimado_h` del oráculo. Deja de ser un *nice to have*: es lo único que
permitiría afirmar un ahorro de fondeo sin inventarlo.

### 7.12 El mapa: de negro a carta náutica

Feedback recibido: la escala de negros no contrastaba y no llamaba la atención. Al ir a
tocarlo apareció algo peor: **las teselas de CARTO llegan con una marca de agua «API KEY
REQUIRED · carto.com/basemaps/apikey» incrustada en la imagen.** Responden 200 sin clave, así
que no fallaba nada visiblemente en consola, pero el texto sale impreso sobre el mapa —- y
contradice la premisa de §9 («sin token, sin licencia propietaria»).

Se cambió a **OpenFreeMap**: teselas vectoriales OpenMapTiles, sin clave, con sus propios
glifos. Tres cosas mejoran a la vez:

1. **Sin marca de agua** y sin depender de una cuenta.
2. **Color exacto por capa.** Al ser vectorial no hay que conformarse con lo que traiga la
   imagen: se repinta cada capa. La paleta elegida —- comparada renderizando cuatro
   candidatas, no a ojo— pone la **tierra más clara que el mar**, que es lo que separa la
   costa de un vistazo y lo que hace saltar la ruta naranja y los colores de estado.
3. **Etiquetas de verdad.** Con el estilo ráster eran imposibles sin montar un servidor de
   fuentes; ahora se ven Valencia, Algeciras, Gibraltar y el resto.

| Rol | Color |
| :-- | :-- |
| Mar | `#041b2d` |
| Tierra | `#242c32` |
| Líneas (fronteras, costa) | `#38454d` |
| Texto del mapa | `#8698a3` |

Dos detalles del estilo base que hubo que corregir: se retira `ne2_shaded` —- el relieve de
Natural Earth, que a poco zoom pinta África más oscura que Europa y rompe la lectura
tierra/mar— y se silencian las capas de ciudad (edificios, carreteras, pistas), que a escala
de Mediterráneo son ruido.

**Si OpenFreeMap no responde**, el mapa cae a un estilo mínimo de un solo color y la
aplicación sigue funcionando: buques, ruta, puertos y contexto son GeoJSON propio. Probado
bloqueando el dominio: 13 avisos y 16 marcadores siguen pintándose. Peor mapa, no aplicación
rota.

### 7.13 Aviso de llegada

Un frontal que se deja abierto en una pantalla necesita avisar cuando entra algo. Suena una
vez **por tanda**, no por fila: una ráfaga de Flink son hasta 17 alertas por minuto y un pitido
por cada una sería una ametralladora.

- **Sonido sintetizado con Web Audio**, sin fichero de audio: nada que servir, nada que pueda
  fallar al descargarse, y el timbre se ajusta en el código. Dos timbres — uno normal de dos
  notas y otro descendente de tres para lo que no es ejecutable, para distinguirlo sin mirar.
- **Señal visual siempre**, suene o no: barra lateral ámbar en el aviso nuevo durante 12 s y
  una insignia «N nuevos» en la cabecera. El aviso nunca depende solo del audio, que puede
  estar en silencio o el usuario no llevar altavoces.
- **Interruptor en la cabecera**, con la preferencia en `localStorage`.

El navegador no deja sonar nada hasta que el usuario interactúa con la página, así que el
`AudioContext` nace suspendido y se reanuda en el primer gesto. Ojo con el orden: `resume()`
es asíncrono, y un aviso disparado por ese mismo gesto llegaría **antes** de que el contexto
esté listo, perdiendo justo el primero. Por eso `reproducirAviso` reanuda y emite al
resolverse en vez de descartar. Verificado contando osciladores: 0 antes del primer clic, 2
después, 4 tras el segundo, y ninguno más con el sonido apagado.

En modo fixture no hay repesca, así que el aviso no se dispararía nunca: hay un botón
**«Probar aviso»** para lanzarlo a mano. Solo aparece con datos de ejemplo.

Las animaciones respetan `prefers-reduced-motion`, como el resto.

---

### 7.14 Los dos indicadores de la cabecera

Preguntados en revisión, y uno de los dos no se sostenía.

**Balizamiento** enciende la superposición de **OpenSeaMap**: boyas, luces con sus sectores y
marcas de navegación. Comprobado midiendo las teselas: a zoom 12 sobre el puerto de Valencia
traen 3–7 KB de contenido y se ven balizas laterales verdes y rojas, sectores de luz y marcas
de puerto; a zoom 9 son ~900 bytes, es decir, nada. **Solo aporta acercándose a un puerto**, y
en la vista general —- donde el frontal pasa la mayor parte del tiempo— no dibuja absolutamente
nada. Por eso nace apagada, y ahora el interruptor lo explica en su texto de ayuda en vez de
dejar al usuario adivinando.

**«Sin repesca» se ha retirado.** Era jerga propia y, en modo fixture, repetía lo que la
chapa de entorno ya dice al lado (§7.15). Conectado tampoco valía gran cosa: anunciar
«repesca cada 30 s» describe una intención, no un hecho —- si la conexión se cae, el cartel
sigue diciendo lo mismo.

Lo sustituye un indicador vivo, **solo en modo conectado**: un punto que late y **«leído hace
N s»**, que sube segundo a segundo. Si pasan dos ciclos y medio sin lectura correcta, el punto
se vuelve ámbar y deja de latir —- así una caída se ve sin necesidad de un mensaje de error. La
cadencia teórica pasa al texto de ayuda, que es donde estorba menos.


### 7.15 La chapa de entorno, en el hueco que ocupaba el aviso de ejemplo

El centro de la cabecera lo ocupaba un aviso ámbar de «datos de ejemplo». Con **dos
despliegues** —- uno por entorno, leyendo tablas distintas— lo que de verdad hace falta saber
de un vistazo es otra cosa: **cuál de los dos se está mirando, y de qué tabla sale lo que se
ve**. Que los datos sean de ejemplo pasa a ser un matiz dentro de esa misma chapa.

```
DEV  datos de ejemplo              PRO  prod_oracle_recommendations
```

**Producción se distingue por relleno, no por color.** Los colores saturados están reservados
para el estado de los datos (§7.11) y gastar uno aquí lo devaluaría; un fondo sólido en medio
de una interfaz de contornos se ve igual de rápido y no compite con el mapa. El texto de ayuda
completa la información: el nombre largo del entorno y si el nombre de la tabla está derivado
o fijado a mano.

Enseñar el nombre de la tabla no es un detalle técnico de más: es lo primero que se querrá
comprobar el día que dos despliegues muestren cosas distintas.

---

## 8. Dos entornos, dos despliegues

Misma lógica y mismo código; **lo único que cambia es de qué tabla se lee**.

### La convención no la decide el frontal

`src/entorno.ts` es **espejo de `api/app/config.py`**. Si divergen, un despliegue lee la tabla
del otro, así que se copia tal cual —- incluidos los dos detalles que invitan a "arreglarlos":

| `NAUTIQ_ENV` | Tabla |
| :-- | :-- |
| `DEV` | `oracle_recommendations_dev` |
| `PRO` | `oracle_recommendations_prod` |

- El entorno va como **sufijo**, y `PRO` es `prod` (no `pro`), igual que los topics de Kafka
  en Aiven.
- **Solo DEV y PRO.** `ingestion` admite además `PRE`, pero el oráculo no tiene entorno de
  preproducción y por tanto esa tabla no existe. Aceptar `PRE` aquí daría un frontal
  apuntando a una tabla inexistente, que es peor que rechazarlo: se avisa por consola y se
  cae a DEV.

Las dos tablas viven en el **mismo proyecto de Supabase**, ambas con RLS y policy de lectura
para `anon` (verificado). Así que los dos despliegues comparten `VITE_SUPABASE_URL` y
`VITE_SUPABASE_ANON_KEY`: lo único que los diferencia es `VITE_NAUTIQ_ENV`.

`VITE_ORACLE_RECOMMENDATIONS_TABLE` sobreescribe el nombre —- mismo papel y mismo patrón de
validación que `ORACLE_RECOMMENDATIONS_TABLE` en el oráculo— para poder corregirlo sin volver
a desplegar.

### El despliegue

**Static Web Apps no se puede usar en esta suscripción.** La política de *Azure for Students*
rechaza las **cinco** regiones donde ese servicio existe —- probadas una por una— y los recursos
reales de la suscripción están todos en `austriaeast`, donde no está disponible. Hacerlo por el
portal falla igual: la política se aplica también ahí, no es una limitación del CLI.

El frontal se sirve desde **Azure Storage con sitio estático**, que sí existe en esa región:

| Entorno | Cuenta | URL |
| :-- | :-- | :-- |
| DEV | `stnautiqfrontdevaue` | `https://stnautiqfrontdevaue.z49.web.core.windows.net/` |
| PRO | `stnautiqfrontproaue` | `https://stnautiqfrontproaue.z49.web.core.windows.net/` |

Ambas en `rg-nautiq-front-{dev,pro}-aue`, región Austria East, plan Standard LRS. El coste es
de céntimos: unos MB y el tráfico de un demo.

**El despliegue es manual**, con los scripts de `infrastructure/azure/`:

```bash
./infrastructure/azure/subir_estatico.sh dev
./infrastructure/azure/subir_estatico.sh pro
```

Se ejecuta con la sesión de `az` del operador, así que **no hay ninguna credencial guardada en
el repositorio**. Automatizarlo en GitHub Actions exigiría la clave de la cuenta como secreto
o un service principal, y en un tenant universitario la creación de service principals suele
estar restringida.

`crear_storage_estatico.sh` solo se necesita para recrear la infraestructura desde cero; los
recursos ya existen.

Construye con las `VITE_*` del entorno (de `frontend/.env.<entorno>`, ignorados por git) y
sube. Dos detalles que el script resuelve y cuestan una tarde si no:

- **`--auth-mode login` no sirve aunque seas Owner de la suscripción.** Owner es plano de
  *control*; escribir blobs es plano de *datos* y necesitaría el rol *Storage Blob Data
  Contributor* asignado aparte. Se lee la clave al vuelo y no se guarda en ningún sitio.
- **`index.html` va con `no-store`.** Los ficheros de `/assets/` llevan hash y se cachean un
  año, pero `index.html` no: si se cachea, un redespliegue sigue sirviendo el bundle viejo
  hasta que caduque. Son dos pasadas de subida distintas.

Lo que se pierde frente a Static Web Apps: deja de ser gratis (céntimos), un dominio propio
con TLS necesitaría Front Door delante, y no hay previews por PR. El endpoint de Azure ya da
HTTPS y el enrutado se cubre con el documento de error 404 → `index.html`. Para un frontal de
solo lectura ninguna de esas pérdidas es grave.

---

## 9. Stack

```
frontend/                       ← fuera del workspace uv; ciclo de vida npm
├── index.html
├── package.json                # incluye gen:types
├── vite.config.ts
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── map.ts                  # MapLibre: init, capas, marcadores
    ├── route-layer.ts          # polilínea teñida por oleaje + capa de waypoints
    ├── feed.ts                 # Supabase: SELECT inicial + repesca + caducidad
    ├── status.ts               # severidad y fiabilidad derivadas (§7.1) — un solo sitio
    ├── alerta.ts               # aviso de llegada: sonido Web Audio + preferencia (§7.13)
    ├── entorno.ts              # entorno del despliegue y tabla de la que se lee (§8)
    ├── session.tsx             # panel de evolución de la aproximación (§7.4)
    ├── panel.tsx               # recomendación + rationale + CII + perfil meteo
    ├── types.ts                # GENERADO desde contracts/ — no editar a mano
    └── mock/events.json        # capturas reales del grafo (§10, fase 1)
```

- **MapLibre GL JS** (BSD): sin token, sin licencia propietaria. Teselas CARTO/OSM y la capa
  **OpenSeaMap** de superposición náutica, gratuita.
- **React + Vite + TypeScript.** El contrato tiene campos que son `null` *siempre* (§3); el
  compilador es lo que evita que se cuelen en pantalla. Los tipos se **generan**.
- **`@supabase/supabase-js`** es el único cliente.
- **Sin gestor de estado.** Dos `Map` en `useState` cubren el caso: decenas de marcadores, no cientos.
- **Sin backend propio.** Si aparece uno, hay que releer §1.

---

## 10. Lo construido

Todo dentro de `frontend/`, más el esquema compartido. Estado real, no estimación.

| Fase | Entregable | Estado |
| :-- | :-- | :-- |
| 0 | `contracts/oracle_recommendation_v1.schema.json` extraído del código del oráculo | ✅ |
| 0 | `frontend/` con Vite + React + TS; `npm run gen:types` → `src/types.ts` | ✅ |
| 1 | `src/mock/events.json`: **11 eventos reales grabados del grafo** | ✅ |
| 2 | Mapa, ruta teñida por oleaje, buque, puerto, contexto | ✅ |
| 2 | `src/status.ts` — severidad, saturación y fiabilidad derivadas (§7.1) | ✅ |
| 3 | Panel: recomendación, CII antes/después, `rationale`, perfiles meteo, tabla | ✅ |
| 3 | `src/session.tsx` — evolución de la aproximación | ✅ |
| 4 | `feed.ts` con `SELECT` inicial, repesca y caducidad; modo fixture | ✅ |
| 4 | Despliegue a Azure Storage estático, DEV y PRO en vivo | ✅ |

### El fixture es una grabación, no una maqueta

Se ejecutó el grafo real del oráculo de punta a punta y se capturó lo que emite. Rutas de
`searoute`, oleaje y viento de Open-Meteo, y CII calculado con las filas reales de
`thetis_mrv` leídas del `.xlsx` del repo. Lo único sustituido fue `db_conn`, por un almacén
en memoria, para **no escribir en la Supabase del equipo**. Detalle en
`src/mock/README.md`.

Cubre las tres severidades, las tres saturaciones, ambos métodos de CII, `heading` ausente,
`eta_current` nulo, el único `fuel_saved_t` no nulo (y es **negativo**) y una sesión de
cuatro avisos con cambio de régimen.

### Lo verificado

**Lógica y datos.** Ejecutando los módulos reales contra los 11 eventos: la derivación de
estado reparte 4 `ok` / 4 `alert` / 3 `critical` en vez de marcarlo todo; `route_weather` y
`route.waypoints` tienen siempre la misma longitud; las coordenadas caen en rango; la
distancia acumulada cuadra con `route.distance_nm` dentro del 8 %; y las cuatro series de los
gráficos no producen NaN ni se salen del `viewBox`. `tsc` y `vite build` limpios.

**Aspecto.** Renderizado en Chromium headless y revisado. El repaso visual encontró **tres
fallos reales que ni la validación de color ni la de geometría habrían detectado**:

1. **El mapa medía 0 px de alto.** MapLibre le pone al contenedor su propia clase
   `maplibregl-map`, que trae `position: relative`, y su hoja se importa *después* de
   `app.css`. Con una sola clase cada selector, ganaba la última del cascade y el canvas se
   quedaba en su fallback de 300 px. Arreglado subiendo la especificidad a `.app > .mapa`, que
   no depende del orden de los imports. Se añadió además un `ResizeObserver`, porque MapLibre
   mide el contenedor una sola vez y el cambio venía del CSS, no de un `resize` de ventana.
2. **El banner de datos de ejemplo quedaba debajo del panel lateral**, centrado en un viewport
   cuyos 430 px derechos ocupa el panel. Ahora vive dentro de la cabecera.
3. **La línea de ruta cruzaba la etiqueta del puerto y se leía como un tachado.** La etiqueta
   del puerto lleva fondo sólido en vez de solo sombra de texto.

Y dos ajustes de legibilidad: las etiquetas de buque se ocultan por debajo de zoom 6 (dos
buques a 30 nm son píxeles vecinos a zoom 5, y la identidad la lleva la lista de avisos, que
está al lado) y la escala del mapa se movió a la derecha, donde no la tapa la leyenda.

También se corrigió **el fixture**: el grabador fijaba `heading = 74°` en todos los escenarios,
así que todos los buques apuntaban al mismo sitio independientemente de su destino —- algo que
se ve al primer vistazo. Ahora el rumbo es la demora al puerto más un sesgo por escenario.

## 11. Decisiones

1. **Transporte.** Tabla `oracle_recommendations` + repesca cada 30 s. No Realtime (preparado, §13),
   no WebSocket. Con eventos cada 30 min, la latencia es irrelevante.
2. **Contrato.** El que el oráculo emite hoy (§4), extraído del código a
   `contracts/oracle_recommendation_v1.schema.json`. Las cinco desviaciones de §4.1 se aceptan.
3. **Estado visual.** Lo deriva el frontal de las señales nativas, en `src/status.ts` (§7.1). El
   oráculo hizo bien en no emitir un `status`.
4. **Radio de contexto.** **No se dibuja.** `context_radius_nm` llega `null` y no se inventa (§7.3).
5. **Fondeados, atracados y en camino.** Los tres, contados y pintados aparte. Ya vienen separados en
   el contrato, y la espera va rotulada como **estimada**, que es lo que es.
6. **Hora del contexto.** `emitted_at`, rotulado como hora de emisión, porque `snapshot_at` es `null`.
7. **Identidad del buque.** MMSI, con IMO de apoyo. Normalizado a string al entrar (§5.3).
8. **RLS.** `SELECT` para `anon` en `oracle_recommendations`, sin policy de escritura. Ya está escrita
   en `schema.sql` — con una salvedad operativa, **TODO 4**.
9. **Dónde se despliega.** **Azure Static Web Apps, plan Free**: 100 GB/mes, SSL y dominio propio,
   CDN global. Cero créditos y la región es irrelevante porque no se despliega cómputo gestionado.

---

## 12. TODOs para los otros equipos — cerrados

Todos hechos en `feature/math_oracle` (`0410d46` … `07086cb`) y verificados contra las filas
reales de `oracle_recommendations`.

| TODO | Estado |
| :-- | :-- |
| 1 · emitir la cola del puerto | ✅ `queue` con `estimated_wait_hours`, `queue_position` y `berth_segment` |
| 2 · nombre del buque | ✅ `vessel.name` desde `thetis_mrv`, sin consultas nuevas |
| 3 · publicar sin tumbar el grafo | ✅ y mejorado: Supabase es la fuente de verdad y ADLS solo se escribe si Supabase confirmó |
| 4 · `schema.sql` idempotente | ✅ tabla, índices y RLS aplicados |
| 5 · marcar el buque objetivo | ✅ `es_objetivo` en las tres listas del contexto |
| 6 · nulos de Open-Meteo | ✅ `list[float \| None]` en `_MarineHourly` y `_WindHourly` |
| 7 · DevOps | pendiente: crear el recurso de Static Web Apps y sus tres secretos |

Dos cosas que llegaron **de más** y el frontal ya usa:

- **`recommendation.weather_speed_loss_pct`** — la corrección Kwon (`perdida_media_pct`).
  Cuánta de la velocidad recomendada se la come el mar; se muestra junto a la saturación.
- **`api/scripts/replay_alertas.py`** — inyecta alertas capturadas de Flink en el grafo y deja
  el resultado en Supabase y ADLS. Es la siembra del arranque en frío de §5.6 y el guion
  reproducible de una demo.

---

## 13. Verificación contra la tabla real

Se validaron las filas de `oracle_recommendations` contra
`contracts/oracle_recommendation_v1.schema.json`. **Aparecieron tres desajustes, y los tres
eran del lado del frontal**, no del oráculo:

1. **`queue` se emite a nivel raíz**, no dentro de `recommendation` como decía el esquema. La
   ubicación del oráculo es la buena —- describe el estado del mundo que motiva la decisión, no
   la decisión— así que se movió el esquema. El frontal leía `recommendation.queue`, siempre
   `undefined`, y mostraba «el oráculo todavía no lo envía» teniendo el dato delante.
2. **`weather_speed_loss_pct` no estaba en el esquema** (se había previsto como
   `queue.kwon_loss_pct`). Se adoptó el nombre del oráculo, que además es más claro.
3. **El esquema rechazaba `estimated_wait_hours`**, y era un fallo propio: `WaitingVessel`
   heredaba de `ContextVessel` con `allOf`, pero cada rama de un `allOf` valida por separado y
   el `additionalProperties: false` del padre no ve las propiedades del hermano. Se declara
   completo en vez de heredar.

Tras corregir: **0 errores de validación** sobre las filas reales y sobre los 14 del fixture.

La tabla real trae además tres cosas que el esquema no anticipaba y el frontal ya trata:

- **El `rationale` del LLM viene con énfasis Markdown** (`*large*` al citar el segmento de
  atraque). Se resolvía como asteriscos literales en pantalla. Ahora se renderiza solo
  `*cursiva*`, partiendo el texto en nodos de React —- sin `dangerouslySetInnerHTML` ni un
  parser completo por tres asteriscos.
- **Esperas de 39 a 129 h** y hasta 118 h de ralentí evitado. Son coherentes con lo que ya se
  midió al grabar el fixture (§7.1) y con que Kwon-Euler sature en `v_min` casi siempre.
  Conviene que alguien de negocio confirme que 129 h de espera en el segmento *large* es
  plausible y no un artefacto de la capacidad de atraque inferida.
- **`emitted_at` puede ir días por detrás de `position_at`.** `replay_alertas.py` sella la
  emisión con `now()` mientras la posición viene de la alerta capturada. Eso obligó a separar
  dos relojes que el frontal confundía: la **lista** caduca por `emitted_at` (una decisión es
  una decisión) pero la **opacidad del marcador** va por `position_at`, porque el marcador
  afirma *dónde está el buque*. Antes se habría pintado a plena opacidad una posición de hace
  cinco días. El panel además lo dice explícitamente cuando el desfase pasa de una hora.

### El oráculo ya avisa cuando el texto es de respaldo

Preguntado por si existe un resultado determinista cuando falla el modelo: **sí, y el oráculo
ya lo señala**. `informe_llm._texto_con_fallback` llama al LLM y, si revienta (429 por rate
limit —- el free tier de Gemini ronda 15-30 RPM frente a ráfagas de 17 alertas/min—, un 5xx o
un `model_id` inválido), cae al resumen determinista y devuelve `degradado=True`. Eso llega al
evento como **`recommendation.rationale_degradado`**.

El criterio es el mismo que con las escrituras a Supabase y ADLS: el resumen es lo **último**
del pipeline, y dejar que un fallo del texto tumbe la invocación tiraría la ruta, la meteo, el
CII y el JIT ya calculados.

Ojo con el sentido del flag, que es sutil: **`false` significa «no ha fallado nada», no «esto
lo escribió un LLM»**. Un despliegue sin `GEMINI_API_KEY` usa el resumen determinista desde el
principio y emite `false`, porque no hay fallo que reportar.

El frontal lo marca con una etiqueta discreta junto a *Por qué* —- **solo cuando es `true`**—,
y el texto de ayuda deja claro lo que importa: **los cálculos no están afectados**, únicamente
la redacción. Por eso la marca va junto al texto y no junto a los números.

No estaba en el esquema porque las filas que se validaron son anteriores; se añadió como
**opcional**, ya que esas filas antiguas no lo llevan y ausente equivale a `false`. El fixture
cubre el caso con `AL MANAMAH`, grabado inyectando un generador de texto que lanza una
excepción: el `true` sale del camino real del código, no escrito a mano.

### `ETA_dynamic` de Flink no es consciente de la ruta

El panel pone juntos «travesía 14 h» (de `route.duration_hours`, que sale de searoute) y
«atraque libre en 129 h», así que invita a restar. Con las tres filas reales la resta **no
cuadra**: sobra entre 3 y 8 h.

| Buque | Travesía (searoute) | Espera | Ralentí esperado | `idle_hours_avoided` emitido |
| :-- | --: | --: | --: | --: |
| BULK VALOR | 13,9 h | 129,0 h | 115,1 h | 118,28 h |
| MSC CHINA | 11,2 h | 39,4 h | 28,2 h | 33,15 h |
| MINOAN PIONEER | 27,9 h | 75,3 h | 47,4 h | 55,25 h |

La causa: `idle_hours_avoided = espera − ETA_dynamic`, y `ETA_dynamic` lo manda Flink con su
propio cálculo, que es **sistemáticamente optimista** frente a la distancia navegable de
`searoute` —- probablemente una estimación sobre distancia directa. Se están mezclando dos
modelos de distancia en la misma resta.

No cambia ninguna decisión (3–8 h sobre magnitudes de 30–130 h) y no se disimula en el frontal:
cada número va rotulado con su origen. Pero conviene que streaming y la capa cognitiva usen la
misma distancia, o que el oráculo recalcule el ETA actual con su propia ruta en vez de fiarse
del que le llega.

### Divergencia deliberada con §2

El diagrama dice «emisión al frontal **en paralelo** a Bronze», con la salvedad de que el
frontal podría mostrar algo que falló al persistirse. El oráculo hizo algo mejor: **Supabase
primero como fuente de verdad, y ADLS solo si Supabase confirmó**. La salvedad de §2 ya no
aplica, y §2 queda desactualizado a la baja —- se deja constancia aquí en vez de reescribir el
diagrama.

---

## 14. Alcance

**MVP.** Mapa + evento del oráculo con su ruta, su estado del mar, su contexto de puerto, su CII
antes/después y la evolución de la aproximación.

**Después, si aporta.**

- Salto a **Supabase Realtime**: `sb.channel(...).on('INSERT')` en `feed.ts`, ~5 líneas más habilitar
  replicación. Solo si 30 s llegan a molestar, que con eventos cada 30 min no parece.
- **Filtro por `alerta_cii`** — *"solo lo preocupante"*. Es una columna promovida: sale casi gratis.
- **Filtro por puerto** — también columna promovida.
- Acumulado de combustible y CO₂ evitados por sesión. La tabla ya lo guarda todo.
- Rastro de posiciones (exige leer Bronze — otro asunto).

**No entra.** Ocupación de atraques en %, ahorro en €, autenticación, edición desde la UI. El frontal
es de solo lectura y debería seguir siéndolo.

---

## 15. *Nice to have* — información que existe y no se está usando

Nada de esto bloquea nada, y el frontal funciona sin ello. Está aquí porque es trabajo ya
hecho aguas arriba que hoy se queda por el camino, ordenado por lo que aporta frente a lo que
cuesta. Verificado campo por campo contra el código del oráculo y contra las filas reales.

### 14.1 El oráculo ya lo calcula y no lo emite

Están en el estado del grafo cuando `construir_evento_contrato` se ejecuta: son líneas de
copia, no cálculo nuevo.

- ~~**`velocidad_jit.v_diseno_kn`**~~ — **ENTREGADO** como `recommendation.design_speed_kn`.
  El panel ya dice «Su casco da 21,3 kn: pediría 25,5 kn» cuando la recomendación no es
  ejecutable, en vez de solo el adjetivo.
- ~~**`velocidad_jit.tiempo_transito_estimado_h`**~~ — **ENTREGADO** como
  `recommendation.estimated_transit_hours`, y resuelve lo que §7.9 dejaba abierto: ya se puede
  cuantificar el fondeo real (ver ahí). Sigue pendiente `tiempo_objetivo_h`, que solo serviría
  para dejar de deducir el caso por el signo de `speed_delta_kn` (§7.1) — cosmético al lado.
- **`cii_*.co2_estimado_kg`** — CO₂ absoluto de la travesía en cada escenario. **Ojo, aporta
  menos de lo que parece:** en la rama `eexi` está condicionado al MISMO DWT real que
  `fuel_saved_t` (`cii_calculus.py`, `if dwt_real is not None`), así que en el caso frecuente
  viene vacío igual. Solo añade cobertura en `fallback_admiralty`, que es justo la rama que el
  propio código decide no considerar fiable. Poco interés.

### 14.2 Ya viene en el evento y el frontal no lo pinta

- **`vessel.nav_status`** — si el buque está navegando (0), fondeado (1) o amarrado (5). Es el
  único estado del buque del evento que no se muestra, y distingue «viene de camino» de «ya
  está esperando fondeado», que no es un matiz menor en un producto sobre esperas.
- **Dirección de ola y de viento en cada waypoint** — viajan en el evento y llegan hasta las
  propiedades de la capa del mapa (`route-layer.ts`), pero solo se muestra la del viento en la
  posición del buque. Serían flechas a lo largo de la ruta.
- **`wave_period` y `wind_gusts_kn` a lo largo de la ruta** — hoy solo en la tabla desplegable.

### 14.3 Requiere una consulta más

- **`port.locode` resuelto por coordenadas.** La tabla `ports` tiene 16.665 filas, el 100 % con
  coordenadas, y probado sobre datos reales resuelve bien por las dos vías: por nombre exacto
  (1 coincidencia para los tres puertos objetivo) y por cercanía (el acierto está a 0–2,7 nm y
  el segundo candidato a 3–5 nm). **Debe hacerse por coordenadas, no por nombre**, porque las
  coordenadas son el único campo que nadie puede teclear mal.

  Hoy no resuelve un problema vivo: hay tres nombres canónicos y uniformes. Es un seguro para
  cuando `puerto` lleve texto de verdad, y arregla algo ya observable: **Barcelona llega con dos
  coordenadas distintas según quién armó el paquete** (`41.338, 2.1675` en el replay frente a
  `41.38258, 2.17707`), 2,7 nm de diferencia, así que el mismo puerto se puede dibujar en dos
  sitios. Con LOCODE la posición sale de `ports`, una sola pareja canónica. La capa analítica lo
  necesita más que el frontal: un nombre en texto libre es una clave mala para cruzar en el
  tiempo.
- **`thetis_mrv.co2_at_berth_t`** — CO₂ anual que ese buque emite **atracado**. Es la línea base
  directa del objetivo del proyecto y ya está cargada en Supabase; daría contexto real a las
  horas de ralentí evitadas.

### 14.4 Está mal etiquetado (arreglo gratis, y es del oráculo)

- **`vessel.destination_raw` no es el destino crudo.** Trae `paquete_1["puerto"]`, el MISMO
  string que `port.name` —- idénticos en las 17 filas comprobadas—, que el propio oráculo
  documenta como «solo un nombre para mostrar». El frontal dejó de mostrarlo: era repetir el
  nombre del puerto bajo una etiqueta falsa. El esquema ya documenta la discrepancia.

  Lo que hay que decidir en el oráculo: **o se emite ahí el destino AIS de verdad** —- el texto
  sucio que teclea la tripulación, que es el dato interesante y hoy no llega al evento—, **o se
  retira el campo** por duplicado.

---

## Anexo — nota sobre las ramas

Este documento vive en `feature/frontend`, que salió de `4e29a4a` y va **por detrás de `develop`**.
El oráculo que se describe aquí está en `feature/math_oracle` (`dbe92d0`), que también ha divergido
de `develop` — y que además toca `ingestion/src/reference/schema.sql`, fuera de `api/`.

**Antes de que esta rama lleve código: rebasar sobre `develop`,** y fusionar `feature/math_oracle`
primero, para que el frontal no se desarrolle contra una rama viva. El orden importa aquí más que en
la pasada anterior: la fase 0 **ejecuta** el grafo del oráculo para extraer el contrato, así que
necesita ese código presente y estable.
