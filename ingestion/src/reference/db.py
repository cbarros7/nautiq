"""
Conexión y esquema de las tablas de REFERENCIA en PostgreSQL (Supabase).

La capa Reference hace cargas puntuales (point-in-time) e importa los datos en
PostgreSQL **exactamente como en producción** (§1/§5). Flink consume estas tablas
(LEFT JOIN por IMO / resolución de destino) para construir y enriquecer el maestro.

Tablas:
- `ports`      : UN/LOCODE -> coordenadas (resolución de destinos, ruta).
- `thetis_mrv` : ficha anual THETIS-MRV por IMO (DWT/GT/EEXI + consumo/CO₂ anuales).
"""

from __future__ import annotations

import psycopg

from .. import config

SCHEMA = """
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
"""


def connect() -> psycopg.Connection:
    """Abre una conexión a PostgreSQL con las variables discretas (`config.PG_DSN`)."""
    return psycopg.connect(**config.PG_DSN)


def init_schema(conn: psycopg.Connection) -> None:
    """Crea las tablas de referencia si no existen (idempotente)."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def upsert_ports(conn: psycopg.Connection, rows: list[dict]) -> int:
    """Carga masiva de puertos (UPSERT por locode)."""
    sql = """
        INSERT INTO ports (locode, name, country, lat, lon)
        VALUES (%(locode)s, %(name)s, %(country)s, %(lat)s, %(lon)s)
        ON CONFLICT (locode) DO UPDATE SET
            name = EXCLUDED.name, country = EXCLUDED.country,
            lat = EXCLUDED.lat, lon = EXCLUDED.lon
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def upsert_thetis(conn: psycopg.Connection, rows: list[dict]) -> int:
    """Carga masiva de la ficha THETIS-MRV (UPSERT por IMO)."""
    sql = """
        INSERT INTO thetis_mrv (imo, name, ship_type, dwt, gt, eexi,
                                annual_fuel_t, annual_distance_nm, annual_co2_t, loaded_at)
        VALUES (%(imo)s, %(name)s, %(ship_type)s, %(dwt)s, %(gt)s, %(eexi)s,
                %(annual_fuel_t)s, %(annual_distance_nm)s, %(annual_co2_t)s, now())
        ON CONFLICT (imo) DO UPDATE SET
            name = EXCLUDED.name, ship_type = EXCLUDED.ship_type,
            dwt = EXCLUDED.dwt, gt = EXCLUDED.gt, eexi = EXCLUDED.eexi,
            annual_fuel_t = EXCLUDED.annual_fuel_t,
            annual_distance_nm = EXCLUDED.annual_distance_nm,
            annual_co2_t = EXCLUDED.annual_co2_t, loaded_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)
