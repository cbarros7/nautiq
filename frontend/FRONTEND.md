# Frontal de visualización — lluvia de ideas

> Documento de discusión, no un plan cerrado. El objetivo es fijar **qué se puede pintar hoy con
> los datos que existen**, qué habría que construir para lo demás, y qué decisión de transporte
> hay que llevar al equipo de infraestructura.

## 1. Principio rector

El frontal **no es el foco del proyecto**. Todo el documento se somete a esa restricción:

- Nada de backend nuevo dedicado al frontal si se puede evitar.
- Nada de estado de servidor propio, colas propias ni auth propia.
- Si una funcionalidad exige datos que hoy no existen, **no entra en el MVP**: se anota como
  dependencia y se pinta como "sin dato" en la UI, no se falsea.
- Un solo desarrollador debería poder mantenerlo sin contexto profundo del pipeline.

Criterio de éxito: **en una demo, se ve un barco acercándose demasiado rápido a un puerto con cola,
y se ve la recomendación del oráculo al lado.** Nada más.

---

## 2. El flujo real (con anclas en el código)

```
AISStream (WebSocket, BBox mediterránea)          ingestion/src/constants.py:17
    │  todo lo que cae en el área se publica en crudo; filtrar es de Flink
    ▼
Kafka Aiven + Schema Registry (Karapace)          contracts/*.avsc
    │  vessel.positions.raw · vessel.static.raw
    ▼
Flink                                              streaming/src/jobs/
    ├─ anti-spoofing (LAG por mmsi, umbral 50 kn)  sql/enriched_positions.sql
    ├─ maestro de buques desde el topic static     ais_static_v1.avsc (doc del contrato)
    ├─ ETA crudo + detección de congestión         anomaly_detection.py  ← STUB, por construir
    └─ sink Bronze (parquet, particionado por dt)  abfss://bronze@…/telemetry
    │
    ▼ webhook HTTP                                 FASTAPI_WEBHOOK_URL
Oráculo matemático — LangGraph en Azure App Service
    │  recibe SIEMPRE los dos paquetes juntos:
    │    ① el buque en cuestión
    │    ② el puerto destino + fondeados + inbound al mismo puerto
    │  calcula velocidad recomendada, estado del puerto, estado óptimo JIT
    │                                              api/app/agents/math_oracle.py ← STUB
    ▼
    ├──────────────► Bronze (contenedor, lo consume la capa analítica)
    └──────────────► FRONTAL   ← aquí entra este documento
```

Dato relevante: el scaffolding del repo **ya anticipa esto**. `api/app/api/webhooks.py` documenta
literalmente *"Rutas WebSocket (opcional) para retransmitir las decisiones al frontend en tiempo
real"*. La intuición de reutilizar el oráculo como emisor está ya escrita en el diseño; no es un
añadido.

### Sobre emitir en paralelo a Bronze

Acordado: emisión al frontal **en paralelo** a la escritura en Bronze. Con una salvedad que conviene
dejar por escrito: en paralelo significa que **el frontal puede mostrar una recomendación que
falló al persistirse**. Para un frontal de demostración es un intercambio aceptable —- pero no lo es
si algún día alguien concilia lo que se vio en pantalla contra la capa analítica. Si eso llega a
importar, el orden pasa a ser *persistir → emitir*, y el frontal asume la latencia extra.

---

## 3. Procedencia de cada dato (la tabla que importa)

Esta es la parte útil del documento: separa lo que es **gratis** de lo que hay que **construir**.

| Dato | Fuente | Estado |
| :-- | :-- | :-- |
| `mmsi`, `lat`, `lon`, `speed`, `cog`, `heading`, `nav_status` | `vessel.positions.raw` | ✅ existe |
| `name`, `imo`, `callsign`, `ship_type`, `length_m`, `beam_m`, `draught_m`, `destination`, `eta` (cruda) | `vessel.static.raw` | ✅ existe |
| `locode`, nombre y **lat/lon del puerto** | tabla `ports` (Supabase, UN/LOCODE) | ✅ existe |
| `dwt`, `gt`, `eexi`, `annual_fuel_t`, `annual_co2_t` | tabla `thetis_mrv` (Supabase, JOIN por IMO) | ✅ existe |
| Identificación de **portacontenedores** | **solo** el JOIN por IMO con `thetis_mrv` — el `ship_type` de AIS no distingue contenedores | ⚠️ un buque sin IMO no se puede clasificar; en el mapa saldrá como tipo desconocido |
| Maestro de buques (mmsi → datos estáticos) | Flink, desde el topic static | 🔨 por construir |
| ETA crudo, detección de aproximación no-JIT | Flink | 🔨 stub |
| Buques fondeados en un puerto | derivable: `nav_status = 1` dentro de un radio R del `locode` | 🔨 por construir (R es una decisión de negocio) |
| Buques inbound al mismo puerto | derivable: `destination` == locode del paquete ① | 🔨 por construir; `destination` es **texto libre AIS**, sucio |
| Tiempo de espera de un fondeado | Flink con estado: instante en que `nav_status` pasó a 1 | 🔨 **atención**: `table.exec.state.ttl = 24 h` (`streaming/src/jobs/config.py`). Esperas > 24 h se pierden |
| Velocidad recomendada, estado óptimo JIT | oráculo (Kwon/Euler + Open-Meteo) | 🔨 stub |
| Ahorro de combustible físico | oráculo; aproximable con `annual_fuel_t` / `annual_distance_nm` de Thetis | 🔨 precisión limitada — etiquetarlo como estimación en la UI |
| Ocupación del puerto en % / atraque libre | **no hay fuente** | ❌ fuera de alcance |
| Ahorro en € | **no hay fuente** (haría falta precio de búnker) | ❌ fuera de alcance |

Los tres puertos objetivo **no están fijados en código**: se carga el catálogo UN/LOCODE completo en
`ports` y la selección es de Flink. Los ejemplos de abajo usan un LOCODE cualquiera como ilustración,
no como configuración.

---

## 4. Contrato del evento (revisado)

Un evento = una decisión del oráculo = un repintado del mapa. Campos marcados con su origen.

```jsonc
{
  "event_id": "01J...",            // ULID; el proyecto ya usa ULID para linaje
  "emitted_at": "2026-08-08T12:45:30Z",
  "schema_version": 1,

  // ① paquete del buque con la novedad
  "vessel": {
    "mmsi": 244930000,             // AIS positions
    "imo": 9876543,                // maestro de buques (null si AIS reporta 0)
    "name": "EJEMPLO MAERSK",      // maestro
    "lat": 41.5, "lon": -0.2,      // AIS positions
    "speed_kn": 12.5,              // AIS positions (SOG)
    "heading": 90,                 // AIS positions
    "nav_status": 0,               // AIS positions — 0 = en navegación
    "destination_raw": "VALENCIA", // AIS static, texto libre SIN normalizar
    "eta_ais_raw": "08151430",     // AIS static, cruda
    "position_at": "2026-08-08T12:44:10Z",   // frescura real del fix
    "is_container": true           // JOIN IMO ↔ thetis_mrv; null si no hay IMO
  },

  // ② paquete del puerto y su contexto
  "port": {
    "locode": "ESVLC",             // tabla ports
    "name": "Valencia",
    "lat": 39.4697, "lon": -0.3763,
    "context_radius_nm": 20,       // el radio con el que se construyó el contexto
    "anchored_count": 3,           // DERIVADO: nav_status = 1 dentro del radio
    "inbound_count": 1,            // DERIVADO: destination == locode
    "snapshot_at": "2026-08-08T12:45:00Z"   // el contexto es una FOTO, no un directo
  },

  "context_vessels": {
    "anchored": [
      { "mmsi": 244930001, "name": "MERCHANT PRIDE", "lat": 39.44, "lon": -0.30,
        "anchored_since": "2026-08-07T10:15:00Z",  // Flink con estado; null si > TTL 24 h
        "wait_hours": 3.5 }                        // null si anchored_since es null
    ],
    "inbound": [
      { "mmsi": 244930003, "name": "EASTERN WIND", "lat": 39.90, "lon": -0.85,
        "distance_nm": 35.2, "speed_kn": 14.1,
        "eta_estimated": "2026-08-10T08:00:00Z" }  // ETA crudo de Flink, no el del oráculo
    ]
  },

  // decisión del oráculo
  "recommendation": {
    "status": "alert",                    // ok | alert | critical
    "recommended_speed_kn": 10.2,
    "speed_delta_kn": -2.3,
    "eta_current": "2026-08-10T19:00:00Z",
    "eta_optimized": "2026-08-10T16:45:00Z",
    "idle_hours_avoided": 2.25,
    "fuel_saved_t": 0.72,                 // ESTIMACIÓN — etiquetar como tal en la UI
    "rationale": "Cola de 3 fondeados; reducir a 10.2 kn evita 2.25 h al ancla",
    "confidence": "medium"                // el oráculo debería poder decir "no estoy seguro"
  }
}
```

Decisiones de contrato que conviene discutir:

- **`snapshot_at` separado de `emitted_at`.** El contexto del puerto es una foto del instante en que
  Flink armó el paquete. Si el frontal lo pinta como si fuera un directo, va a parecer roto (barcos
  fondeados que no se mueven cuando el resto sí). La UI debe rotularlo: *"contexto a las 12:45"*.
- **`confidence`.** Si el oráculo puede devolver incertidumbre, el mapa puede degradar el color en
  vez de afirmar algo dudoso. Barato de añadir ahora, imposible de retrofitear en la UI después.
- **Todo lo derivado admite `null`.** `anchored_since` se pierde con el TTL, `imo` puede no venir,
  `is_container` puede ser indeterminable. La UI necesita un estado "sin dato" de primera clase.
- **`destination_raw` sin normalizar.** El destino AIS lo teclea la tripulación: `"VALENCIA"`,
  `"ESVLC"`, `"VLC"`, `"VALENCIA ANCH"`. La normalización a LOCODE es de Flink y va a fallar a
  veces. El frontal enseña el crudo y no pretende resolverlo.

---

## 5. El arranque en frío

Este es el problema de diseño de verdad, y la razón por la que el push del oráculo **no basta por sí
solo**.

Las alertas son anomalías: por definición, poco frecuentes. Si el frontal es puramente reactivo,
alguien que abre el navegador ve **un mapa vacío** hasta que salte la siguiente alerta, que puede
tardar horas. En una demo eso es fatal.

**No hace falta una API REST que sirva datos crudos**: el oráculo ya puede empujar. Pero sigue
haciendo falta *algo* que responda "¿qué está pasando ahora?" al cargar. Lo mínimo que resuelve esto:

> **Las últimas N recomendaciones quedan persistidas y el frontal las lee al conectar.**
> No es una API sobre el pipeline: es leer una tabla de resultados ya calculados —- los mismos que se
> emiten en vivo.

Eso son ~20 líneas, no un servicio. Y si la persistencia va a Postgres (§6), el mismo cliente hace
las dos cosas: `SELECT` inicial + suscripción al streaming, con un solo SDK y sin backend propio.

Detalles a decidir: cuántas recomendaciones se retienen (¿últimas 50? ¿últimas 24 h?) y cuándo un
barco desaparece del mapa (propuesta: se atenúa a los 30 min sin evento nuevo, se retira a las 6 h).

---

## 6. Transporte: opciones aterrizadas a la infra real

Inventario de lo que ya existe: **Kafka Aiven** (SSL + Karapace), **Postgres Supabase** (ya usado por
LangGraph para checkpoints, `PG_DSN` en `api/app/core/config.py`), **Azure ADLS Gen2** (contenedor
`bronze`), **Azure App Service** (donde vivirá el oráculo). **No hay Redis.**

| Opción | Infra nueva | Arranque en frío | Coste real |
| :-- | :-- | :-- | :-- |
| **A. Supabase Realtime** ⭐ | ninguna | ✅ el mismo cliente hace el `SELECT` | El oráculo hace un `INSERT` en una tabla `recommendations`. El frontal usa `supabase-js`: `SELECT` al cargar + `.on('INSERT')` en vivo. Cero servidor propio, cero WebSocket que escribir, reconexión y fan-out incluidos |
| B. WebSocket en el App Service | ninguna | ❌ hay que añadirlo aparte | Ya está previsto en `webhooks.py`. Pero: en App Service hay que **habilitar WebSockets explícitamente**, y con más de una instancia hacen falta *sticky sessions* (ARR affinity) o un backplane. Acopla la vida de la conexión al ciclo de despliegue del oráculo |
| C. Topic Kafka nuevo | ninguna | ❌ | Reutiliza lo que ya se paga, pero un navegador no habla Kafka: hace falta un relay consumidor + WebSocket. Es la opción B **más** un consumidor |
| D. Azure Event Hub / Web PubSub | sí | ❌ | La más robusta y la que menos encaja con "el frontal no es el foco" |
| E. Redis Pub/Sub | sí | ❌ | Añade un componente nuevo a la infra para un problema que Supabase resuelve con lo que ya hay |

**Recomendación: A.** No porque sea la más elegante, sino porque es la única que resuelve *también*
el arranque en frío sin escribir backend, y porque Postgres ya está en el camino del oráculo.

Contrapartidas honestas de A, para llevarlas a la conversación con infra:

- Ataría el frontal al SDK de Supabase. Si algún día se sale de Supabase, el frontal se reescribe
  (es un frontal pequeño: aceptable).
- Requiere habilitar replicación en la tabla y definir políticas RLS. Con datos AIS —- que son
  públicos —- una policy de solo-lectura con `anon` es suficiente, pero **hay que decidirlo
  conscientemente**, no dejarlo abierto por defecto.
- Añade una escritura a Postgres en la ruta del oráculo. Es una fila pequeña por alerta; irrelevante
  al volumen de anomalías esperado.

Si infra prefiere no tocar Supabase, el plan B es la opción B **con** la tabla de §5 para el
arranque en frío. Lo que no recomiendo es B sin resolver §5.

---

## 7. Qué se pinta

```
                    🚢 EJEMPLO MAERSK  ── 12.5 kn ──▶  (rojo, pulsando)
                          ╲
                           ╲ ruta punteada
                            ╲
                             ◉  ESVLC · Valencia          ← radio de contexto (20 nm), traslúcido
                            ╱ ╲     3 fondeados · 1 inbound
                     ⚓ ⚓ ⚓      🔵                       ← contexto a las 12:45
                   fondeados    inbound
```

| Elemento | Forma | Color | Interacción |
| :-- | :-- | :-- | :-- |
| Buque con novedad | triángulo orientado a `heading` | rojo `critical` / ámbar `alert` | clic → panel con la recomendación |
| Puerto | círculo + etiqueta LOCODE | neutro; borde ámbar si hay cola | clic → lista del contexto |
| Radio de contexto | círculo traslúcido | gris muy claro | ninguna — solo explica de dónde sale el contexto |
| Fondeados | ancla pequeña | gris | hover → nombre + espera (o *"espera desconocida"* si `null`) |
| Inbound | triángulo pequeño | azul | hover → nombre + ETA + distancia |
| Ruta al puerto | línea punteada | del color del estado | ninguna |

Reglas de honestidad visual —- caras de respetar, y la diferencia entre un mapa útil y uno que engaña:

- **La orientación es `heading`, y `heading` puede ser `null`.** Sin él, círculo, no triángulo: no se
  inventa un rumbo.
- **Nunca interpolar posiciones.** Un barco se dibuja donde dice su último fix, con la hora del fix
  visible. Animar entre puntos es inventar datos.
- **El contexto lleva su hora encima**, siempre, porque es una foto (§4).
- **El color codifica el estado de la recomendación, no la velocidad.** Un barco rápido no es un
  barco en alerta: lo que genera alerta es la relación entre su ETA y el estado del puerto.
- Nada de %-de-ocupación: se muestran **conteos** (`3 fondeados`), que sí son un dato real.

---

## 8. Stack

```
frontend/
├── index.html
├── package.json
├── vite.config.ts
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── map.ts              # MapLibre: init, capas, marcadores
    ├── feed.ts             # Supabase: SELECT inicial + suscripción
    ├── panel.tsx           # panel lateral de la recomendación
    ├── types.ts            # el contrato de §4
    └── mock/events.json    # eventos de ejemplo para desarrollar sin oráculo
```

- **MapLibre GL JS** (BSD) en vez de Mapbox GL: sin token, sin licencia propietaria. Teselas base de
  CARTO/OSM y —- opcional pero muy pertinente aquí —- la capa **OpenSeaMap** de superposición náutica,
  gratuita.
- **React + Vite + TypeScript.** TypeScript no por ceremonia: el contrato de §4 tiene muchos campos
  nullables y el compilador es lo que evita el `undefined` en pantalla.
- **`@supabase/supabase-js`** si se va por la opción A. Es el único cliente necesario.
- **Sin gestor de estado.** Un `Map<mmsi, evento>` en un `useState` cubre el caso. Un Zustand o una
  capa de virtualización son para cientos de marcadores; aquí hay decenas.
- **Sin backend propio.** Si aparece uno, hay que releer §1.

Fuera del monorepo `uv` (es JS, no Python): la carpeta `frontend/` no entra en
`[tool.uv.workspace] members`. Su ciclo de vida es `npm`, y su despliegue puede ser un Static Web App
de Azure —- estático, sin servidor.

---

## 9. Alcance

**MVP (lo que se demuestra).** Mapa + evento del oráculo pintado con su contexto.

- [ ] `frontend/` con Vite + MapLibre y las teselas resueltas
- [ ] Tipos de TypeScript del contrato de §4
- [ ] Fixture `mock/events.json` — **primero esto**: desbloquea todo el frontal sin esperar al oráculo
- [ ] Mapa con buque + puerto + fondeados + inbound desde el fixture
- [ ] Panel lateral con la recomendación
- [ ] Conectar al feed real (§6) y al `SELECT` inicial (§5)

**Después, si aporta.** Historial de recomendaciones, acumulado de combustible evitado, filtro por
puerto, rastro de posiciones (exige leer Bronze — otro asunto).

**No entra.** Ocupación de atraques, ahorro en €, autenticación de usuarios, edición desde la UI.
El frontal es de solo lectura, y debería seguir siéndolo.

Orden que importa: **el fixture antes que el feed.** Con `mock/events.json` el frontal entero se
construye y se revisa mientras el oráculo y el job de Flink siguen siendo stubs. También fija el
contrato de §4 por escrito antes de que el oráculo lo implemente, que es cuando aún es barato
cambiarlo.

---

## 10. Para llevar al equipo

1. **Transporte:** ¿opción A (Supabase Realtime) o B (WebSocket en el App Service)? Si es B, ¿quién
   resuelve el arranque en frío de §5?
2. **Contrato de §4:** ¿lo asume el oráculo tal cual? En particular `confidence` y `snapshot_at`, que
   son baratos ahora y caros después.
3. **Radio de contexto:** ¿20 nm? Determina qué cuenta como "fondeado en el puerto" y sale en la UI.
4. **TTL de 24 h:** las esperas al ancla de más de un día se pierden con el estado de Flink actual.
   ¿Se acepta y la UI dice *"espera desconocida"*, o se persiste el instante de fondeo en Postgres?
5. **Fondeados vs. amarrados:** `nav_status` distingue fondeado (1) de amarrado/atracado (5). El
   contexto ¿incluye los amarrados? Son ocupación real de atraque, y son señal de congestión.
6. **RLS en Supabase** si se va por A: los datos AIS son públicos, pero la policy hay que escribirla.
7. **Dónde se despliega** el estático y bajo qué dominio.

---

## Anexo — nota sobre esta rama

`feature/frontend-maritime-dashboard` salió de `4e29a4a` (punta de `feature/ingestion-pipeline`), **no**
de `feature/flink_implementation` (`b8582c1`). Por eso no contiene el trabajo de Flink que se cita en
§2 —- `schema_utils.py`, `sql/*.sql` —- aunque este documento sí lo tiene en cuenta. Para un cambio
solo-documentación da igual, pero conviene rebasar antes de que la rama lleve código.
