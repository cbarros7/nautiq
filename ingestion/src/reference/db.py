"""
Conexión y esquema de las tablas de REFERENCIA en PostgreSQL (Supabase).

La capa Reference hace cargas puntuales (point-in-time) e importa los datos en
PostgreSQL **exactamente como en producción. Flink consume estas tablas
(LEFT JOIN por IMO / resolución de destino) para construir y enriquecer el maestro.

Tablas:
- `ports`      : UN/LOCODE -> coordenadas (resolución de destinos, ruta).
- `thetis_mrv` : ficha anual THETIS-MRV por IMO (DWT/GT/EEXI + consumo/CO₂ anuales).
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from .. import config

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


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
                                annual_fuel_t, annual_distance_nm, annual_co2_t,
                                technical_efficiency, time_at_sea_h,
                                fuel_per_distance_kg_per_nm, reporting_period,
                                annual_co2eq_t, co2_at_berth_t, co2_in_port_t,
                                co2_per_distance_kg_per_nm, loaded_at)
        VALUES (%(imo)s, %(name)s, %(ship_type)s, %(dwt)s, %(gt)s, %(eexi)s,
                %(annual_fuel_t)s, %(annual_distance_nm)s, %(annual_co2_t)s,
                %(technical_efficiency)s, %(time_at_sea_h)s,
                %(fuel_per_distance_kg_per_nm)s, %(reporting_period)s,
                %(annual_co2eq_t)s, %(co2_at_berth_t)s, %(co2_in_port_t)s,
                %(co2_per_distance_kg_per_nm)s, now())
        ON CONFLICT (imo) DO UPDATE SET
            name = EXCLUDED.name, ship_type = EXCLUDED.ship_type,
            dwt = EXCLUDED.dwt, gt = EXCLUDED.gt, eexi = EXCLUDED.eexi,
            annual_fuel_t = EXCLUDED.annual_fuel_t,
            annual_distance_nm = EXCLUDED.annual_distance_nm,
            annual_co2_t = EXCLUDED.annual_co2_t,
            technical_efficiency = EXCLUDED.technical_efficiency,
            time_at_sea_h = EXCLUDED.time_at_sea_h,
            fuel_per_distance_kg_per_nm = EXCLUDED.fuel_per_distance_kg_per_nm,
            reporting_period = EXCLUDED.reporting_period,
            annual_co2eq_t = EXCLUDED.annual_co2eq_t,
            co2_at_berth_t = EXCLUDED.co2_at_berth_t,
            co2_in_port_t = EXCLUDED.co2_in_port_t,
            co2_per_distance_kg_per_nm = EXCLUDED.co2_per_distance_kg_per_nm,
            loaded_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)
