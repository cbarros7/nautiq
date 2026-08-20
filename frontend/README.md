# `frontend/` — frontal del Oráculo

Mapa de solo lectura que pinta las recomendaciones de Adaptive Slow Steaming que el oráculo
escribe en `oracle_recommendations`. El plan y las decisiones de diseño están en
[FRONTEND.md](FRONTEND.md); esto es solo cómo se ejecuta.

Fuera del workspace `uv` a propósito: es JS, su ciclo de vida es `npm`.

## Arrancar

```bash
npm install
npm run dev
```

Sin configurar nada arranca con el **fixture**: 11 eventos reales grabados del grafo del
oráculo (`src/mock/events.json`, ver su [README](src/mock/README.md)). La interfaz lo anuncia
con una insignia en la cabecera. Es el modo de desarrollo y no toca la red más que para las
teselas del mapa.

Para leer la tabla de verdad, copia `.env.example` a `.env` y rellena:

```
VITE_SUPABASE_URL=...
VITE_SUPABASE_ANON_KEY=...     # publica por diseno: protege la RLS, no el secreto
```

Con credenciales presentes lee la tabla; `VITE_USE_MOCK=true` fuerza el fixture aunque las haya.

## Comandos

| | |
| :-- | :-- |
| `npm run dev` | servidor de desarrollo |
| `npm run build` | `tsc` + build de producción a `dist/` |
| `npm run typecheck` | solo tipos |
| `npm run gen:types` | **regenera `src/types.ts`** desde `../contracts/oracle_recommendation_v1.schema.json` |

`src/types.ts` está **generado**: no se edita a mano. Si el contrato del oráculo cambia, se
actualiza el esquema en `contracts/` y se ejecuta `gen:types` —- los errores de compilación
señalan qué hay que tocar. El workflow de despliegue falla si el fichero generado no coincide
con el esquema.

## Mapa de ficheros

| Fichero | Qué resuelve |
| :-- | :-- |
| `src/feed.ts` | `SELECT` inicial, repesca cada 30 s, reglas de caducidad, modo fixture |
| `src/status.ts` | severidad, saturación y fiabilidad derivadas de las señales del oráculo |
| `src/douglas.ts` | escala Douglas de estado del mar y su rampa de color |
| `src/map.ts` · `route-layer.ts` · `markers.ts` | MapLibre, ruta teñida por oleaje, marcadores |
| `src/panel.tsx` · `session.tsx` · `chart.tsx` | panel lateral, evolución de la aproximación, gráficos |
| `src/format.ts` | cómo se ve un `null` — decidido en un solo sitio |

## Despliegue

`.github/workflows/deploy_frontend.yml` → Azure Static Web Apps (plan Free). Necesita tres
secretos de GitHub: `AZURE_STATIC_WEB_APPS_API_TOKEN`, `VITE_SUPABASE_URL` y
`VITE_SUPABASE_ANON_KEY`.
