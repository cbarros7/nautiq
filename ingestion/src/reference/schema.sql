CREATE TABLE IF NOT EXISTS ports (
    locode   text PRIMARY KEY,
    name     text,
    country  text,
    lat      double precision,
    lon      double precision
);

CREATE TABLE IF NOT EXISTS thetis_mrv (
    imo                 bigint PRIMARY KEY,
    name                text,
    ship_type           text,
    dwt                 numeric,
    gt                  numeric,
    eexi                numeric,
    annual_fuel_t       numeric,
    annual_distance_nm  numeric,
    annual_co2_t        numeric,
    loaded_at           timestamptz DEFAULT now()
);

-- Recomendaciones del oráculo (Adaptive Slow Steaming) — frontera de
-- contrato entre api/ (que escribe) y frontend/ (que sólo lee); el
-- payload sigue contracts/oracle_recommendation_v1.schema.json.
-- Una sola tabla para dos usos, porque son el mismo objeto (una fila
-- por decisión del oráculo): sirve de historial para dar contexto al
-- LLM entre avisos sucesivos del mismo buque/puerto (la alerta se
-- dispara cada 30 min mientras el buque está a <12h del puerto) y es
-- la tabla que lee el frontal por polling.
CREATE TABLE IF NOT EXISTS oracle_recommendations (
    event_id     text PRIMARY KEY,          -- ULID, = correlation_id del webhook
    session_id   text NOT NULL,             -- agrupa la misma aproximación buque/puerto (hueco < 24h)
    emitted_at   timestamptz NOT NULL DEFAULT now(),
    mmsi         text NOT NULL,
    puerto       text NOT NULL,             -- nombre del puerto (aún sin locode real, ver payload)
    alerta_cii   boolean NOT NULL,          -- CII con velocidad JIT peor que el inicial
    payload      jsonb NOT NULL             -- evento completo (oracle_recommendation_v1)
);

CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_recent
    ON oracle_recommendations (emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_session
    ON oracle_recommendations (session_id, emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_mmsi_puerto
    ON oracle_recommendations (mmsi, puerto, emitted_at DESC);

COMMENT ON TABLE oracle_recommendations IS
    'Decisiones del oraculo (Adaptive Slow Steaming). Frontera de contrato entre api/ y frontend/: el payload sigue oracle_recommendation_v1. Tambien sirve de historial para dar contexto al LLM entre avisos sucesivos del mismo buque/puerto.';

ALTER TABLE oracle_recommendations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "lectura anonima" ON oracle_recommendations
    FOR SELECT TO anon USING (true);
-- Deliberadamente SIN policy de INSERT/UPDATE/DELETE: el oraculo
-- escribe con las credenciales de servidor de db_conn.py (psycopg
-- directo), que saltan RLS. El navegador nunca escribe.
