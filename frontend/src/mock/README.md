# `events.json` — grabación, no maqueta

16 eventos con la forma exacta que devuelve `SELECT * FROM oracle_recommendations`, así que
`feed.ts` no distingue el fixture de la tabla. Validados contra
`contracts/oracle_recommendation_v1.schema.json`: **0 errores**.

Dos procedencias, ambas reales:

- **13 eventos grabados** ejecutando el grafo del oráculo (`feature/math_oracle` @ `07086cb`)
  de punta a punta. Rutas de `searoute`, oleaje y viento de Open-Meteo, CII y velocidad de
  diseño con las filas reales de `thetis_mrv` leídas del `.xlsx` del repo. Se sustituyó solo
  `db_conn` (almacén en memoria) y `adls_conn` (`esta_configurado() → False`), para no
  escribir en la infraestructura del equipo.
- **3 filas reales** de `oracle_recommendations`, tal como las dejó `replay_alertas.py`. Están
  para que quien toque el panel vea **prosa de LLM de verdad**: los 13 grabados salieron sin
  `GEMINI_API_KEY`, así que su `rationale` es el resumen determinista de respaldo.

## El realineado temporal

El fixture se graba una vez y se lee meses después, así que cada evento lleva una
**traslación uniforme**: a todas las marcas de tiempo del payload se les suma el mismo delta
para colocar el evento en la línea temporal de la demo. Uniforme importa —- se conservan
intactas todas las relaciones internas: ETA frente a emisión, ETA de cada waypoint, desfase
entre fix y emisión. Solo se mueve la escena en el tiempo.

Las tres filas reales conservan por eso una particularidad suya: su `emitted_at` está unos
cinco días **después** de su `position_at`, porque `replay_alertas.py` sella la emisión con
`now()` mientras la posición viene de la alerta capturada. No se ha corregido: es lo que el
replay produce de verdad, y ejercita el caso —- el marcador sale atenuado y el panel explica por
qué (ver `opacidadPosicion` en `feed.ts`).

## Cobertura

Por resultado JIT: **1** llega a tiempo ahorrando combustible, **4** llegan a tiempo pero
acelerando (emiten más), **3** no son ejecutables, y **7** van a fondear igual. Ese reparto no
es un defecto del fixture: es la forma del problema con el modelo de esperas actual (ver §7.10
de FRONTEND.md).

| Escenario | Qué ejercita |
| :-- | :-- |
| `MSC PRATITI` → Algeciras | cola larga, frena a v_min, CII +52,9 % — **el caso frecuente** |
| `SAGA FLORA` → Barcelona | `excede_v_diseno`, `alerta_cii`, y el único `fuel_saved_t` no nulo (**negativo**: combustible extra) |
| `MSC MASHA 3` → Valencia | sin IMO → CII por `fallback_admiralty` y `vessel.name` nulo |
| `CONTSHIP ZEN` → Algeciras | `heading` ausente → círculo, no triángulo |
| `MAERSK NAMIBIA` → Barcelona | sin `ETA_dynamic` → `eta_current` e `idle_hours_avoided` nulos |
| `HAMBURG EXPRESS` → Valencia | puerto despejado → 9 → 32,4 kn, CII −1191 % |
| `ELBTOWER` → Valencia | ventana JIT alcanzable → `convergio: true`, pero acelerando (el CII empeora) |
| `AL MANAMAH` → Algeciras | **LLM caído**: se inyecta un generador de texto que lanza excepción, así que `rationale_degradado: true` sale del camino real del código |
| **`SALGUEIRO` → Valencia** | **el caso que el proyecto persigue**: llega JIT **frenando** de 17,5 a 13,0 kn, CII +45,1 %, y evita 6 h de fondeo. Es el único de los 15 |
| `SIARGAO` → Valencia (×4) | **una sesión completa**: 4 avisos con la cola vaciándose y cambio de régimen al final |
| `BULK VALOR`, `MSC CHINA`, `MINOAN PIONEER` → Barcelona | filas reales: prosa de LLM con énfasis Markdown, esperas de 39–129 h, desfase fix/emisión |

## Orden de la lista

El caso `SALGUEIRO` se coloca como el **más reciente** del fixture: es el que hay que ver al
abrir, y a mitad de lista salía atenuado por las reglas de caducidad. El resto conserva su
orden relativo. Es una decisión de escaparate, no un dato alterado.

## Un detalle del grabador

`ETA_dynamic` es una **entrada** del webhook, y el grabador la calcula sobre la distancia
**navegable** de `searoute`, no sobre la línea recta. Con la geodésica (205 nm frente a 278
reales en el caso de Valencia) el ETA sale optimista e `idle_hours_avoided` queda inflado: el
panel mostraría «travesía 16 h» y «atraque libre en 22 h» —- 6 h de margen— junto a una cifra
grande de 10 h, contradiciéndose en pantalla.

Las 3 filas reales sí descuadran 3–8 h, porque su `ETA_dynamic` viene de Flink y no es
consciente de la ruta. Está documentado en §13 de FRONTEND.md; no se corrige aquí porque son
datos reales.

## Regenerar

El grabador vive fuera del repo (herramienta de un uso, no código de producto). Necesita el
código del oráculo y `uv run --with langgraph --with geopy --with searoute`. Si el contrato
cambia, lo primero es `contracts/oracle_recommendation_v1.schema.json` y `npm run gen:types`.
