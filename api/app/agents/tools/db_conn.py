
import psycopg
import os
from contextlib import contextmanager
from typing import Optional
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host" : os.getenv('PGHOST'),
    'port' : os.getenv('PGPORT'),
    'dbname' : os.getenv('PGDATABASE'),
    'user' : os.getenv('PGUSER'),
    'password' : os.getenv('PGPASSWORD'),
    'sslmode' : os.getenv('PGSSLMODE'),
    'connect_timeout':30,
}

def get_connection() -> psycopg.Connection:
    return psycopg.connect(**DB_CONFIG, row_factory = dict_row)

@contextmanager
def get_cursor(commit: bool = False):
    """
    Context manager que abre conexión + cursor y los cierra solo.
    Uso:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            print(cur.fetchall())
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
            if commit:
                conn.commit()
    finally:
        conn.close()

# ──────────────────────────────────────────────────────────────────────
#  thetis_mrv: resolución de ship_type / características del buque a
#  partir del IMO
# ──────────────────────────────────────────────────────────────────────

def get_ship_type(imo) -> Optional[str]:
    """
    Devuelve el ship_type registrado en thetis_mrv para un IMO dado,
    o None si no hay registro para ese IMO.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT ship_type FROM public.thetis_mrv WHERE imo = %s",
            (int(imo),),
        )
        row = cur.fetchone()
    return row["ship_type"] if row else None


def get_ship_types(imos: list) -> dict[str, str]:
    """
    Devuelve {imo (str): ship_type} para varios IMOs en una sola query.

    Pensada para resolver de golpe todos los buques de un contrato
    agregado de puerto (atracados + fondeados + en_camino), en vez de
    hacer una query por buque.
    """
    imos_int = sorted({int(imo) for imo in imos if imo is not None})
    if not imos_int:
        return {}

    with get_cursor() as cur:
        cur.execute(
            "SELECT imo, ship_type FROM public.thetis_mrv WHERE imo = ANY(%s)",
            (imos_int,),
        )
        rows = cur.fetchall()

    return {str(row["imo"]): row["ship_type"] for row in rows}


def get_thetis_mrv_record(imo) -> Optional[dict]:
    """
    Devuelve el registro completo de thetis_mrv para un IMO (ship_type,
    dwt, gt, eexi, ...), o None si no existe. cii_calculus lo usa para
    obtener eexi/dwt además del ship_type.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM public.thetis_mrv WHERE imo = %s",
            (int(imo),),
        )
        return cur.fetchone()


# ──────────────────────────────────────────────────────────────────────
#  ports: resolución de lat/lon del puerto destino a partir del locode
#  ("puerto" del webhook, paquete 1 y 2)
# ──────────────────────────────────────────────────────────────────────

def get_port(locode) -> Optional[dict]:
    """
    Devuelve el registro de la tabla ports (locode, name, country, lat,
    lon) para un locode dado, o None si no existe. math_oracle lo usa
    para construir el sea_route.Port a partir de paquete_1["puerto"].
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM public.ports WHERE locode = %s",
            (str(locode),),
        )
        return cur.fetchone()


def test_connection() -> None:
    """Prueba rápida de conectividad."""
    try:
        print('entra')
        with get_cursor() as cur:
            cur.execute("SELECT version();")
            resultado = cur.fetchone()
            print("✅ Conexión exitosa a Supabase")
            print(f"Versión de PostgreSQL: {resultado['version']}")
    except psycopg.OperationalError as e:
        print(f"❌ Error de conexión: {e}")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        
if __name__ == "__main__":
    print(DB_CONFIG)
    test_connection()
    with get_cursor() as cur:
        # cur.execute("SELECT * FROM public.ports limit 10;")
        # print('ports')        
        # print(cur.fetchall())
        # query = """SELECT * FROM public.thetis_mrv where dwt>=0 limit 10"""
        # cur.execute(query)
        # print('thetis_mrv')
        # print(cur.fetchall())
        cur.execute("SELECT * FROM public.ports WHERE locode = 'ESBCN'")
        print('Vessels type')
        print(cur.fetchall())