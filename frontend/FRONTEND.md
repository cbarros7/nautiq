# Frontal de visualización — plan de ejecución

> **Estado.** Cuarta pasada: el frontal está **implementado**. Este documento pasa de plan a
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
> **Alcance.** Solo trabajo dentro de `frontend/`. Lo que hace falta fuera está en §11, y ahora son
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
Escribirlo es trabajo del frontal y es la fase 0 (§9), porque es quien más lo necesita: se
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

  "recommendation": {
    "recommended_speed_kn": 6.4,
    "speed_delta_kn": -3.4,
    "eta_current": "2026-08-20T12:41:00Z",   // null si el webhook no manda ETA_dynamic
    "eta_optimized": "2026-08-20T14:38:00Z",
    "idle_hours_avoided": 1.9,               // null si no hay ETA_dynamic
    "fuel_saved_t": null,                    // null si thetis_mrv no da DWT real
    "rationale": "…",                        // PROSA de LLM, varios párrafos posibles

    // Señales nativas del cálculo. NO hay status ni confidence: los deriva el frontal (§7.1)
    "convergio": true,
    "excede_v_diseno": false,
    "alerta_cii": false,
    "nota": null,
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
- **`puerto`** permite el filtro por puerto de §12 sin parsear el payload.
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
| Supabase Realtime | ninguna | ✅ | ~5 líneas más, pero exige habilitar replicación y razonar RLS sobre el canal. **Preparado, no activado** (§12) |
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
- **La orientación es `heading`, y puede faltar.** Sin él, círculo, no triángulo: no se inventa un
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
| Buque con novedad | triángulo a `heading`, círculo si falta | severidad del eje 1 (§7.1) | clic → panel de sesión (§7.4) |
| Puerto | círculo + **nombre** | neutro; borde ámbar si `anchored_count > 0` | clic → las tres listas del contexto |
| Atracados | rectángulo pequeño | gris oscuro | hover → MMSI |
| Fondeados | ancla pequeña | gris | hover → MMSI + espera **estimada** |
| En camino | triángulo pequeño | azul | hover → MMSI + espera **estimada** |

Reglas de honestidad que se mantienen: el color codifica el estado de la recomendación, **no la
velocidad**; `fuel_saved_t` va rotulado *estimación* y desaparece cuando es `null`; se muestran
**conteos**, nunca porcentajes de ocupación; la ruta es **calculada**, no la derrota observada, y se
dibuja punteada y rotulada como *ruta prevista*.

---

## 8. Stack

```
frontend/                       ← fuera del workspace uv; ciclo de vida npm
├── index.html
├── package.json                # incluye gen:types
├── vite.config.ts
├── staticwebapp.config.json    # rutas SPA para Azure Static Web Apps
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── map.ts                  # MapLibre: init, capas, marcadores
    ├── route-layer.ts          # polilínea teñida por oleaje + capa de waypoints
    ├── feed.ts                 # Supabase: SELECT inicial + repesca + caducidad
    ├── status.ts               # severidad y fiabilidad derivadas (§7.1) — un solo sitio
    ├── session.tsx             # panel de evolución de la aproximación (§7.4)
    ├── panel.tsx               # recomendación + rationale + CII + perfil meteo
    ├── types.ts                # GENERADO desde contracts/ — no editar a mano
    └── mock/events.json        # capturas reales del grafo (§9, fase 1)
```

- **MapLibre GL JS** (BSD): sin token, sin licencia propietaria. Teselas CARTO/OSM y la capa
  **OpenSeaMap** de superposición náutica, gratuita.
- **React + Vite + TypeScript.** El contrato tiene campos que son `null` *siempre* (§3); el
  compilador es lo que evita que se cuelen en pantalla. Los tipos se **generan**.
- **`@supabase/supabase-js`** es el único cliente.
- **Sin gestor de estado.** Dos `Map` en `useState` cubren el caso: decenas de marcadores, no cientos.
- **Sin backend propio.** Si aparece uno, hay que releer §1.

---

## 9. Lo construido

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
| 4 | `.github/workflows/deploy_frontend.yml` → Azure Static Web Apps | ✅ |

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

## 10. Decisiones

1. **Transporte.** Tabla `oracle_recommendations` + repesca cada 30 s. No Realtime (preparado, §12),
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

## 11. TODOs para los otros equipos

La pasada anterior tenía seis TODOs; el oráculo cerró la mayoría. Quedan estos, ordenados por
relación valor/coste.

### TODO 1 · Oráculo — emitir la cola del puerto  ·  ~4 líneas

`fetch_tiempo_espera` ya calcula `estimacion_jit` con `tiempo_espera_estimado_h`, `posicion_cola` y
`segmento_atraque`, y `build_informe` los pone en `informe["cola_puerto"]`. **Pero `informe` no se
persiste**: `construir_evento_contrato` no los copia, así que el frontal no puede enseñar *"posición
4 en cola, espera estimada 6,3 h"* — que es literalmente la justificación de frenar.

- [ ] Añadir el bloque al evento, con los tres campos ya calculados:
      ```python
      "queue": {
          "estimated_wait_hours": state["estimacion_jit"]["tiempo_espera_estimado_h"],
          "queue_position":       state["estimacion_jit"]["posicion_cola"],
          "berth_segment":        state["estimacion_jit"]["segmento_atraque"],
      },
      ```
- [ ] *Si sale gratis:* `perdida_kwon_media_pct` de `velocidad_jit.perdida_media_pct` — cuánto
      castiga la meteo a este buque en esta ruta. Es un dato bonito y ya está en el estado.

### TODO 2 · Oráculo — el nombre del buque  ·  sin consultas nuevas

El docstring dice que el nombre no está *"ni en paquete_1/2 ni en thetis_mrv"*. Lo primero es cierto;
lo segundo no: **`thetis_mrv.name` existe** — `schema.sql` lo documenta como *"Nombre del buque según
la declaración MRV"*. Y `cii_calculus.estimar_cii` **ya trae la fila completa** por IMO
(`db_conn.get_thetis_mrv_record`, que hace `SELECT *`), así que el nombre ya está en memoria: **no
hace falta ninguna consulta nueva**.

- [ ] Exponerlo — p. ej. añadiéndolo a `CIIResult.detalles` junto a `tipo_normalizado`, que es el
      camino que `construir_evento_contrato` ya usa — y rellenar `vessel.name` cuando haya IMO;
      `null` cuando no.

Sin esto, todo el frontal etiqueta buques por MMSI de nueve dígitos. Es la mejora de legibilidad más
barata que queda en el sistema.

### TODO 3 · Oráculo — que publicar no tumbe el grafo

`publicar_recomendacion` llama a `db_conn.guardar_recomendacion` sin protección: si Supabase no
responde, el nodo lanza y **se pierde el cálculo entero**, incluida la llamada al LLM que ya se pagó.

- [ ] Envolver la escritura y **registrar el fallo sin propagarlo**, devolviendo `evento_contrato`
      igual. Mismo criterio que ya se aplicó en `ingestion/src/ais/tracker.py` (`d52a096`): un fallo
      al publicar en la DLQ no tumba el tracker.

### TODO 4 · Infra — `schema.sql` ya no es idempotente

El fichero declara en su cabecera *"Idempotente: se puede ejecutar tantas veces como haga falta"*, y
`ingestion/src/reference/db.py::init_schema` lo ejecuta entero. Pero PostgreSQL **no soporta
`CREATE POLICY IF NOT EXISTS`**, así que `CREATE POLICY "lectura anonima"` **falla en la segunda
ejecución** y se lleva por delante todo el `init_schema`.

- [ ] Precederla de `DROP POLICY IF EXISTS "lectura anonima" ON oracle_recommendations;`, o envolverla
      en un `DO $$ ... EXCEPTION WHEN duplicate_object THEN NULL; END $$;`.
- [ ] Aplicar el esquema en Supabase y entregar la **`anon` key** (pública, va al bundle del frontal).
      Las `PG*` de `db_conn.py` no salen del oráculo.
- [ ] Añadir a `.env.example`: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (build del frontal) y
      `GEMINI_API_KEY` (oráculo, hoy sin documentar).

### TODO 5 · Oráculo — marcar el buque objetivo en el contexto  ·  opcional

`jit_calculus.estimar_desde_contrato` ya devuelve `es_objetivo`, pero `_contexto_buques` no lo
propaga al evento. El frontal deduplica por `mmsi` de todos modos (§7.2), así que esto solo ahorra
una comparación — pero hace el contrato autoexplicativo.

- [ ] Propagar `es_objetivo` a los elementos de `context_vessels`.

### TODO 6 · Oráculo — Open-Meteo devuelve nulos y tumba el evento entero

**Encontrado al grabar el fixture, y se llevó 5 de 11 escenarios.** Open-Meteo devuelve
`wave_height: null` en celdas que el modelo de olas no cubre —- típicamente costeras, y una de
ellas era la propia posición del buque. Pero `_MarineHourly` en `open_meteo.py` declara
`wave_height: list[float]`, sin `Optional`, así que Pydantic lanza `ValidationError` y **se
pierde la recomendación completa**, incluida la llamada al LLM que ya se pagó.

```
ValidationError: 144 validation errors for _MarineLocationResult
hourly.wave_height.0  Input should be a valid number
```

- [ ] `list[float | None]` en `_MarineHourly` y `_WindHourly`, y propagar el `None` hasta el
      evento. El contrato ya lo admite: `route_weather[].wave_height` es `["number","null"]` y
      el frontal pinta ese tramo en el gris de «sin dato del modelo» en vez de mentir.
- [ ] El validador `_series_alineadas` sigue valiendo: lo que hay que relajar es el tipo del
      elemento, no la comprobación de longitudes.

### TODO 7 · DevOps

- [ ] Crear el recurso **Azure Static Web Apps (plan Free)** y guardar su token de despliegue como
      secreto de GitHub.
- [ ] `.github/workflows/deploy_frontend.yml`, filtrado por `frontend/**`, inyectando las `VITE_*`.
- [ ] **Aparte de este plan:** `deploy_fastapi.yml` hace `docker build .` contra la raíz, donde no
      hay `Dockerfile` — está en `api/` y sigue siendo solo comentarios. Ese workflow falla tal cual.
      Y `api/pyproject.toml` todavía tiene `fastapi`/`uvicorn` comentados, así que no hay servicio
      HTTP que reciba el webhook: el grafo solo se invoca desde su `__main__`.

---

## 12. Alcance

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

## Anexo — nota sobre las ramas

Este documento vive en `feature/frontend`, que salió de `4e29a4a` y va **por detrás de `develop`**.
El oráculo que se describe aquí está en `feature/math_oracle` (`dbe92d0`), que también ha divergido
de `develop` — y que además toca `ingestion/src/reference/schema.sql`, fuera de `api/`.

**Antes de que esta rama lleve código: rebasar sobre `develop`,** y fusionar `feature/math_oracle`
primero, para que el frontal no se desarrolle contra una rama viva. El orden importa aquí más que en
la pasada anterior: la fase 0 **ejecuta** el grafo del oráculo para extraer el contrato, así que
necesita ese código presente y estable.
