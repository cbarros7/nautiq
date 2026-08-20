# `events.json` — grabación, no maqueta

11 eventos **reales** del grafo del oráculo (`feature/math_oracle` @ `dbe92d0`), capturados
ejecutándolo de punta a punta. Cada fila tiene la forma exacta que devuelve
`SELECT * FROM oracle_recommendations`, así que `feed.ts` no distingue el fixture de la tabla.

Lo que es real: rutas de `searoute`, oleaje y viento de Open-Meteo, CII y velocidad de diseño
calculados con las filas reales de `thetis_mrv` (leídas de `data/reference/thetis_mrv.xlsx`, no
inventadas), y buques con IMO reales de la flota sintética de `ingestion`.

Lo que se sustituyó para grabar sin escribir en la Supabase del equipo: solo `db_conn`, por un
almacén en memoria. Todo lo demás es el código del oráculo sin tocar.

Dos ajustes deliberados, para que quede dicho:

- **`emitted_at` realineado.** El oráculo lo sella con `datetime.now()`, así que los 11 eventos
  saldrían con la misma hora. Se reescribió al `position_at` de cada escenario + 3 s, para que el
  orden y los huecos sean los diseñados.
- **`rationale` es el resumen determinista**, no texto de LLM: se grabó sin `GEMINI_API_KEY`, que es
  el camino de respaldo de `informe_llm`. La forma del campo es la misma.

## Cobertura

| Escenario | Qué ejercita |
| :-- | :-- |
| `MSC PRATITI` → Algeciras | cola larga, frena a v_min, CII +52,9 % — **el caso frecuente** |
| `SAGA FLORA` → Barcelona | `excede_v_diseno`, `alerta_cii`, y el único `fuel_saved_t` no nulo (**negativo**: combustible extra) |
| `MSC MASHA 3` → Valencia | sin IMO → CII por `fallback_admiralty` (fiabilidad baja) |
| `CONTSHIP ZEN` → Algeciras | `heading` ausente → círculo, no triángulo |
| `MAERSK NAMIBIA` → Barcelona | sin `ETA_dynamic` → `eta_current` e `idle_hours_avoided` nulos |
| `HAMBURG EXPRESS` → Valencia | puerto despejado → 9 → 32,4 kn, CII −1191 % |
| `ELBTOWER` → Valencia | ventana JIT alcanzable → `convergio: true` |
| `SIARGAO` → Valencia (×4) | **una sesión completa**: 4 avisos de 30 min con la cola vaciándose y un cambio de régimen al final (converge → ventana insuficiente) |

## Regenerar

El grabador vive fuera del repo (es una herramienta de un uso, no código de producto). Para volver a
grabar hace falta el código del oráculo y `uv run --with langgraph --with geopy --with searoute`.
Si el contrato cambia, lo que hay que rehacer primero es
`contracts/oracle_recommendation_v1.schema.json` y `npm run gen:types`.
