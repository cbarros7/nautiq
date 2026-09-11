-- =============================================================================
-- Tablas de REFERENCIA de Nautiq (cargas puntuales).
-- Idempotente: se puede ejecutar tantas veces como haga falta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ports (
    locode   text PRIMARY KEY,
    name     text,
    country  text,
    lat      double precision,
    lon      double precision
);

COMMENT ON TABLE  ports IS
    'UN/LOCODE + coordenadas. Resuelve el campo `destination` del AIS (texto libre) a un puerto con posición.';
COMMENT ON COLUMN ports.locode  IS 'Código UN/LOCODE de 5 letras, país + localidad (p.ej. ESVLC = Valencia). Clave primaria.';
COMMENT ON COLUMN ports.name    IS 'Nombre de la localidad según UNECE.';
COMMENT ON COLUMN ports.country IS 'Código ISO de 2 letras del país.';
COMMENT ON COLUMN ports.lat     IS 'Latitud en grados decimales (WGS84). Origen: OSM/Wikidata, no UNECE.';
COMMENT ON COLUMN ports.lon     IS 'Longitud en grados decimales (WGS84).';



CREATE TABLE IF NOT EXISTS thetis_mrv (
    imo                 bigint PRIMARY KEY,
    name                text,
    ship_type           text,
    dwt                 numeric(12,2),
    gt                  numeric(12,2),
    eexi                numeric(10,3),
    annual_fuel_t       numeric(14,3),
    annual_distance_nm  numeric(14,2),
    annual_co2_t        numeric(14,3),
    loaded_at           timestamptz DEFAULT now()
);

-- Enriquecimiento con indicadores operacionales y de emisiones en puerto.
-- ALTER idempotente: la tabla ya existe en Supabase, así que el CREATE de arriba no
-- añadiría columnas nuevas por sí solo.
ALTER TABLE thetis_mrv
    ADD COLUMN IF NOT EXISTS reporting_period             integer,
    ADD COLUMN IF NOT EXISTS technical_efficiency         text,
    ADD COLUMN IF NOT EXISTS time_at_sea_h                numeric(8,2),
    ADD COLUMN IF NOT EXISTS fuel_per_distance_kg_per_nm  numeric(16,4),
    ADD COLUMN IF NOT EXISTS annual_co2eq_t               numeric(14,3),
    ADD COLUMN IF NOT EXISTS co2_at_berth_t               numeric(14,3),
    ADD COLUMN IF NOT EXISTS co2_in_port_t                numeric(14,3),
    ADD COLUMN IF NOT EXISTS co2_per_distance_kg_per_nm   numeric(16,4);

COMMENT ON TABLE thetis_mrv IS
    'Ficha anual THETIS-MRV (EMSA) por buque, indexada por IMO. Declaración obligatoria de consumo y emisiones de los buques que tocan puertos de la UE. Es el único origen que distingue portacontenedores de otra carga: el ship_type de AIS agrupa toda la carga en 70-79. Unidades: "m tonnes" del fichero = toneladas métricas; nm = millas náuticas.';

-- --- Identidad -----------------------------------------------------------------
COMMENT ON COLUMN thetis_mrv.imo IS
    'Número IMO del buque (7 dígitos). Clave primaria y única unión fiable con el AIS, que también reporta IMO en ShipStaticData.';
COMMENT ON COLUMN thetis_mrv.name IS
    'Nombre del buque según la declaración MRV. Puede diferir del nombre emitido por AIS.';
COMMENT ON COLUMN thetis_mrv.ship_type IS
    'Tipo de buque en la taxonomía de EMSA: "Container ship", "Bulk carrier", "Oil tanker", "Chemical tanker", "General cargo ship", etc. Cobertura 100%. ESTE es el campo que identifica portacontenedores.';
COMMENT ON COLUMN thetis_mrv.reporting_period IS
    'Año natural al que se refieren TODAS las métricas anuales de la fila. Imprescindible: la PK es solo el IMO, así que cargar el fichero de otro año sobrescribe la fila; sin esta columna no se sabría a qué ejercicio corresponde el dato.';
COMMENT ON COLUMN thetis_mrv.loaded_at IS
    'Momento en que Nautiq cargó la fila. Metadato de ingesta: NO es la fecha del dato (para eso, reporting_period).';

-- --- Dimensiones y eficiencia técnica -----------------------------------------
COMMENT ON COLUMN thetis_mrv.dwt IS
    'Peso muerto en toneladas. DERIVADO, no viene directo del fichero: se calcula desde el consumo por trabajo de transporte, así que solo existe para los buques que reportan en base dwt (~9% de la flota del fichero).';
COMMENT ON COLUMN thetis_mrv.gt IS
    'Arqueo bruto. El fichero público de THETIS-MRV NO trae esta columna, así que hoy siempre es NULL. Requiere otra fuente de referencia.';
COMMENT ON COLUMN thetis_mrv.eexi IS
    'Valor numérico del indicador de eficiencia técnica, en gCO₂ por tonelada y milla náutica. Es el número extraído de technical_efficiency; consulta esa columna para saber de qué métrica procede (EEXI, EEDI o EIV no son comparables entre sí).';
COMMENT ON COLUMN thetis_mrv.technical_efficiency IS
    'Indicador de eficiencia técnica tal cual lo declara el buque: "EEXI (4.11 gCO₂/t·nm)", "EIV (...)" o "Not Applicable". Conserva QUÉ métrica se usó, que el campo eexi pierde al quedarse solo con el número.';

-- --- Actividad anual -----------------------------------------------------------
COMMENT ON COLUMN thetis_mrv.annual_fuel_t IS
    'Combustible total consumido en el año, en toneladas métricas. Suma de todos los viajes y estancias en el ámbito MRV.';
COMMENT ON COLUMN thetis_mrv.annual_distance_nm IS
    'Distancia total recorrida en el año, en millas náuticas. DERIVADA: el fichero no trae distancia directa, se obtiene de annual_fuel_t / fuel_per_distance_kg_per_nm.';
COMMENT ON COLUMN thetis_mrv.time_at_sea_h IS
    'Horas en la mar durante el año (excluye estancia en puerto). Rango válido 0-8784 (año bisiesto). Un 0 significa que el buque no navegó en el periodo. Con annual_distance_nm da la velocidad media operativa.';

-- --- Emisiones anuales ---------------------------------------------------------
COMMENT ON COLUMN thetis_mrv.annual_co2_t IS
    'CO₂ total emitido en el año, en toneladas métricas. Solo CO₂.';
COMMENT ON COLUMN thetis_mrv.annual_co2eq_t IS
    'CO₂ equivalente total del año, en toneladas: incluye además CH₄ y N₂O. Es la métrica hacia la que van EU ETS y FuelEU Maritime, así que es la moneda adecuada para cuantificar ahorros con valor regulatorio.';
COMMENT ON COLUMN thetis_mrv.co2_at_berth_t IS
    'CO₂ emitido ATRACADO en puertos de la UE, en toneladas anuales. Línea base directa del objetivo de Nautiq: la quema en ralentí que se evita llegando Just-In-Time en vez de esperar. Es una de las cuatro categorías regulatorias del MRV y la que cuadra con el total: annual_co2_t ≈ voyages_between + departed + to + co2_at_berth_t (verificado en el 87% de las filas). Cobertura 100%: USA ESTA para cuantificar emisiones en puerto.';
COMMENT ON COLUMN thetis_mrv.co2_in_port_t IS
    'CO₂ emitido DENTRO de puertos de la UE, en toneladas anuales. NO es un superconjunto de co2_at_berth_t, aunque el nombre lo sugiera: en el fichero de 2024 coincide con atraque en el 66% de las filas, es mayor en el 19% (ahí sí añade maniobra y fondeo) y vale 0 en el 15% porque el buque no lo declara. Reportado de forma inconsistente; no asumir anidamiento ni restar una de otra sin comprobar que ambas son > 0.';

-- --- Ratios de eficiencia operativa -------------------------------------------
COMMENT ON COLUMN thetis_mrv.fuel_per_distance_kg_per_nm IS
    'Consumo medio por distancia, en kg por milla náutica. ATENCIÓN: el fichero de origen trae valores implausibles en unas pocas filas (se ha visto hasta 1,3e7 kg/nm); se cargan sin recortar, conviene acotar en Flink. Los buques que no navegaron traen "Division by zero!" en el fichero y aquí quedan en NULL.';
COMMENT ON COLUMN thetis_mrv.co2_per_distance_kg_per_nm IS
    'CO₂ medio por distancia, en kg por milla náutica. Contraparte en emisiones de fuel_per_distance_kg_per_nm: traduce directamente un cambio de velocidad en emisiones evitadas.';
-- --- Limpieza: indicadores condicionales del MRV que no aplican al caso de uso ----
-- Solo los reportan buques offshore o que miden la carga en volumen, así que en una
-- flota mercante venían vacíos (0%-18% de cobertura). Se retiran para no dejar
-- columnas muertas en la tabla que Flink consulta.
ALTER TABLE thetis_mrv
    DROP COLUMN IF EXISTS fuel_on_laden_t,
    DROP COLUMN IF EXISTS fuel_per_time_t_per_h,
    DROP COLUMN IF EXISTS fuel_dynamic_positioning_t,
    DROP COLUMN IF EXISTS cargo_density_t_per_m3;

-- Converge las instalaciones creadas antes de acotar los tipos: un `numeric` sin
-- precisión no mapea de forma determinista al DECIMAL(p,s) de Flink. Redondea al
-- vuelo, lo que además limpia el ruido de coma flotante de las columnas DERIVADAS
-- (`dwt` traía 18 decimales y `annual_distance_nm` 15, artefactos de la división).
-- Idempotente: si el tipo ya coincide, PostgreSQL no reescribe la tabla.
ALTER TABLE thetis_mrv
    ALTER COLUMN dwt                         TYPE numeric(12,2),
    ALTER COLUMN gt                          TYPE numeric(12,2),
    ALTER COLUMN eexi                        TYPE numeric(10,3),
    ALTER COLUMN annual_fuel_t               TYPE numeric(14,3),
    ALTER COLUMN annual_distance_nm          TYPE numeric(14,2),
    ALTER COLUMN annual_co2_t                TYPE numeric(14,3),
    ALTER COLUMN annual_co2eq_t              TYPE numeric(14,3),
    ALTER COLUMN co2_at_berth_t              TYPE numeric(14,3),
    ALTER COLUMN co2_in_port_t               TYPE numeric(14,3),
    ALTER COLUMN time_at_sea_h               TYPE numeric(8,2),
    ALTER COLUMN fuel_per_distance_kg_per_nm TYPE numeric(16,4),
    ALTER COLUMN co2_per_distance_kg_per_nm  TYPE numeric(16,4);

-- Recomendaciones del oráculo (Adaptive Slow Steaming) — frontera de
-- contrato entre api/ (que escribe) y frontend/ (que sólo lee); el
-- payload sigue contracts/oracle_recommendation_v1.schema.json.
-- Una sola tabla para dos usos, porque son el mismo objeto (una fila
-- por decisión del oráculo): sirve de historial para dar contexto al
-- LLM entre avisos sucesivos del mismo buque/puerto (la alerta se
-- dispara cada 30 min mientras el buque está a <12h del puerto) y es
-- la tabla que lee el frontal por polling.
--
-- Hay una tabla por entorno (ver api/app/config.py, decide segun
-- NAUTIQ_ENV): oracle_recommendations_dev / oracle_recommendations_prod.
-- Tablas separadas y no una columna "entorno" porque asi el aislamiento
-- no depende de que ninguna consulta se acuerde de filtrar: una
-- credencial mal apuntada escribe en la tabla equivocada, no ensucia
-- los datos buenos.
CREATE TABLE IF NOT EXISTS oracle_recommendations_dev (
    event_id     text PRIMARY KEY,          -- ULID, = correlation_id del webhook
    session_id   text NOT NULL,             -- agrupa la misma aproximación buque/puerto (hueco < 24h)
    emitted_at   timestamptz NOT NULL DEFAULT now(),
    mmsi         text NOT NULL,
    puerto       text NOT NULL,             -- nombre del puerto (aún sin locode real, ver payload)
    alerta_cii   boolean NOT NULL,          -- CII con velocidad JIT peor que el inicial
    payload      jsonb NOT NULL             -- evento completo (oracle_recommendation_v1)
);

CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_dev_recent
    ON oracle_recommendations_dev (emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_dev_session
    ON oracle_recommendations_dev (session_id, emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_dev_mmsi_puerto
    ON oracle_recommendations_dev (mmsi, puerto, emitted_at DESC);

COMMENT ON TABLE oracle_recommendations_dev IS
    'Decisiones del oraculo (Adaptive Slow Steaming) en DEV. Frontera de contrato entre api/ y frontend/: el payload sigue oracle_recommendation_v1. Tambien sirve de historial para dar contexto al LLM entre avisos sucesivos del mismo buque/puerto.';

ALTER TABLE oracle_recommendations_dev ENABLE ROW LEVEL SECURITY;

CREATE POLICY "lectura anonima" ON oracle_recommendations_dev
    FOR SELECT TO anon USING (true);
-- Deliberadamente SIN policy de INSERT/UPDATE/DELETE: el oraculo
-- escribe con las credenciales de servidor de db_conn.py (psycopg
-- directo), que saltan RLS. El navegador nunca escribe.


-- Misma tabla para PRODUCCION.
CREATE TABLE IF NOT EXISTS oracle_recommendations_prod (
    event_id     text PRIMARY KEY,          -- ULID, = correlation_id del webhook
    session_id   text NOT NULL,             -- agrupa la misma aproximación buque/puerto (hueco < 24h)
    emitted_at   timestamptz NOT NULL DEFAULT now(),
    mmsi         text NOT NULL,
    puerto       text NOT NULL,             -- nombre del puerto (aún sin locode real, ver payload)
    alerta_cii   boolean NOT NULL,          -- CII con velocidad JIT peor que el inicial
    payload      jsonb NOT NULL             -- evento completo (oracle_recommendation_v1)
);

CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_prod_recent
    ON oracle_recommendations_prod (emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_prod_session
    ON oracle_recommendations_prod (session_id, emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_recommendations_prod_mmsi_puerto
    ON oracle_recommendations_prod (mmsi, puerto, emitted_at DESC);

COMMENT ON TABLE oracle_recommendations_prod IS
    'Decisiones del oraculo (Adaptive Slow Steaming) en PRODUCCION. Misma estructura y contrato que oracle_recommendations_dev; el oraculo escribe en una u otra segun NAUTIQ_ENV.';

ALTER TABLE oracle_recommendations_prod ENABLE ROW LEVEL SECURITY;

CREATE POLICY "lectura anonima" ON oracle_recommendations_prod
    FOR SELECT TO anon USING (true);
-- Igual que en DEV: sin policy de INSERT/UPDATE/DELETE, el oraculo
-- escribe con credenciales de servidor que saltan RLS.
