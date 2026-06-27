# API — Web App + capa cognitiva (FastAPI)

> **Estado: documental.** La funcionalidad aún no está implementada. Este README
> describe la arquitectura prevista. El diseño matemático ya presente
> (`app/agents/`) es el núcleo de la capa cognitiva que aquí se integrará.

## Responsabilidades

La API (Azure App Service, FastAPI) es el **sumidero reactivo**: ociosa por
defecto, "despierta" al recibir alertas de Flink (SAD §6.3).

1. **Recepción de alertas desde Flink** — webhook (`app/api/webhooks.py`) que
   recibe el disparador JIT de Flink (ETA crudo + congestión) con su `correlation_id`
   (ULID) para linaje.
2. **Lógica de la Web App** — endpoints REST + WebSockets para el operador
   (notificaciones en tiempo real, modo broadcast single-tenant, ADR 003).
3. **Capa cognitiva (LangGraph)** — al recibir la alerta (que ya trae ruta y
   contexto meteorológico calculados por Flink), el agente:
   - ejecuta el **oráculo matemático** (modelos deterministas);
   - emite la recomendación de *Adaptive Slow Steaming* para mitigar el *Idle Burn*.
4. **Persistencia cognitiva** — checkpoints de LangGraph y embeddings RAG en
   Supabase PostgreSQL (ADR 006), junto al ULID para reconciliación analítica.

## Oráculo matemático (`app/agents/`)

Código determinista incrustado como herramientas `@tool` de LangGraph (ADR 004,
sin MCP externo en el MVP):

| Módulo | Rol |
|--------|-----|
| `math_oracle.py` | Punto de entrada de las herramientas matemáticas (Kwon/Euler). |
| `app/agents/README.md` | **Diseño + código de referencia** del modelo de consumo bottom-up (IMO 4th GHG) y del early-warning CII (MEPC.337/338/339). Documental: aún no integrado como `@tool`. |

Flujo cognitivo: curva base (consumo) → corrección Kwon por meteo → integración
Euler → CO₂ del trayecto → contraste CII → recomendación.

## Integración con Flink

```
Flink (alerta JIT con ruta + meteo, webhook) ──▶ FastAPI /webhooks
                                                      │
                                                      ├─▶ oráculo matemático (consumo + Kwon/Euler + CII)
                                                      └─▶ recomendación ──▶ Web App (WebSocket) + Supabase
```

Flink decide *cuándo* despertar a la API (heurística barata: ETA crudo, congestión)
y adjunta ruta (searoute) y meteo (Open-Meteo). La API hace el cómputo cognitivo
caro (modelos deterministas + LLM) solo bajo demanda.

## Conexión a Supabase

La API usa Supabase de dos formas (ver `app/db/supabase.py` y `app/core/config.py`):
- **Cliente Supabase (PostgREST)** con `SUPABASE_URL` + clave *publishable* para
  CRUD a nivel de aplicación (sujeto a RLS).
- **PostgreSQL directo** (psycopg / `langgraph-checkpoint-postgres`) con la cadena de
  conexión (`PG*`) para checkpoints del agente y operaciones que requieren DDL.

## Pendiente de implementar

- Endpoints FastAPI + WebSockets.
- Grafo LangGraph + checkpointer PostgreSQL.
- Cableado de `consumption_curve` / `cii` (ver `app/agents/README.md`) como `@tool`.
- Cálculo del combustible por trayecto (entrada del CII) desde la curva calibrada.
