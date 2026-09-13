# `frontend/` — frontal del Oráculo

Mapa de solo lectura que pinta las recomendaciones de Adaptive Slow Steaming que el oráculo
escribe en `oracle_recommendations`. El plan y las decisiones de diseño están en
[FRONTEND.md](FRONTEND.md); esto es solo cómo se ejecuta.

Fuera del workspace `uv` a propósito: es JS, su ciclo de vida es `npm`.

## Arrancar

**Desde `frontend/`, no desde la raíz del repositorio.** No hay `package.json` en la raíz a
propósito: el frontal queda fuera del workspace `uv` (es JS, no Python), así que `npm` solo
encuentra el proyecto aquí dentro.

```bash
cd frontend
npm install
npm run dev
```

Sin configurar nada arranca con el **fixture**: 11 eventos reales grabados del grafo del
oráculo (`src/mock/events.json`, ver su [README](src/mock/README.md)). La interfaz lo anuncia
con una insignia en la cabecera. Es el modo de desarrollo y no toca la red más que para las
teselas del mapa.

Para leer la tabla de verdad, copia `.env.example` a `.env` y rellena:

```
VITE_NAUTIQ_ENV=DEV            # DEV | PRO — decide la chapa y la tabla que se lee
VITE_SUPABASE_URL=...
VITE_SUPABASE_ANON_KEY=...     # publica por diseno: protege la RLS, no el secreto
```

Con credenciales presentes lee la tabla; `VITE_USE_MOCK=true` fuerza el fixture aunque las haya.

## Entornos

Misma lógica y mismo código en los dos despliegues; **lo único que cambia es de qué tabla se
lee**. Solo lleva prefijo la tabla que escribe el oráculo:

| `VITE_NAUTIQ_ENV` | Tabla | Despliegue |
| :-- | :-- | :-- |
| `DEV` | `oracle_recommendations_dev` | rama `develop` |
| `PRO` | `oracle_recommendations_prod` | rama `main` |

Es **espejo de `api/app/config.py`**: misma convención, mismos nombres, mismo override
(`VITE_ORACLE_RECOMMENDATIONS_TABLE`). Si divergen, un despliegue lee la tabla del otro. Solo
DEV y PRO —- el oráculo no tiene entorno de preproducción, así que la tabla de PRE no existe.

Las dos tablas están en el mismo proyecto de Supabase, así que ambos despliegues comparten
URL y anon key. La cabecera muestra siempre el entorno y la tabla que se está leyendo, y
producción se ve rellena para que no haya duda. Detalle en [FRONTEND.md §8](FRONTEND.md).

## Comandos

| | |
| :-- | :-- |
| `npm run dev` | servidor de desarrollo |
| `npm run build` | `tsc` + build de producción a `dist/` |
| `npm run typecheck` | solo tipos |
| `npm run test` | tests unitarios (Vitest) |
| `npm run gen:types` | **regenera `src/types.ts`** desde `../contracts/oracle_recommendation_v1.schema.json` |

`src/types.ts` está **generado**: no se edita a mano. Si el contrato del oráculo cambia, se
actualiza el esquema en `contracts/` y se ejecuta `gen:types` —- los errores de compilación
señalan qué hay que tocar. El workflow de despliegue falla si el fichero generado no coincide
con el esquema.

## Tests

Tests unitarios (Vitest) de la lógica pura del frontal: `format.ts` (cómo se ve un
`null`), `douglas.ts` (bandas de estado del mar) y `status.ts` (severidad, saturación y
fiabilidad derivadas del oráculo). Sin DOM ni red: se ejecutan con entorno `node`.

```bash
cd frontend
npm test
```

Cada fichero de test vive junto al módulo que cubre (`src/*.test.ts`).

## Mapa de ficheros

| Fichero | Qué resuelve |
| :-- | :-- |
| `src/entorno.ts` | entorno del despliegue y tabla de la que se lee |
| `src/feed.ts` | `SELECT` inicial, repesca cada 30 s, reglas de caducidad, modo fixture |
| `src/status.ts` | severidad, saturación y fiabilidad derivadas de las señales del oráculo |
| `src/douglas.ts` | escala Douglas de estado del mar y su rampa de color |
| `src/map.ts` · `route-layer.ts` · `markers.ts` | MapLibre, ruta teñida por oleaje, marcadores |
| `src/panel.tsx` · `session.tsx` · `chart.tsx` | panel lateral, evolución de la aproximación, gráficos |
| `src/alerta.ts` | aviso de llegada: sonido Web Audio + preferencia |
| `src/format.ts` | cómo se ve un `null` — decidido en un solo sitio |

## Despliegue

Azure Storage con sitio estático, región Austria East.

```bash
./infrastructure/azure/subir_estatico.sh dev   # o pro
```

| Entorno | URL |
| :-- | :-- |
| DEV | https://stnautiqfrontdevaue.z49.web.core.windows.net/ |
| PRO | https://stnautiqfrontproaue.z49.web.core.windows.net/ |

Necesita sesión de `az` y las credenciales de Supabase en `frontend/.env.dev` / `.env.pro`
(ignorados por git). Static Web Apps no es viable en esta suscripción: ver
[FRONTEND.md §8](FRONTEND.md).
