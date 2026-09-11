"""
Configuración por entorno de la capa Oráculo.

Equivalente en `api/` de ingestion/src/config.py: una sola variable
(NAUTIQ_ENV) decide a qué entorno apunta el servicio —tabla de
Supabase, carpeta de ADLS— sin tocar ninguna otra. Antes cada módulo
leía y validaba NAUTIQ_ENV por su cuenta (lo hacía adls_conn), y con la
tabla de Supabase pasando también a depender del entorno eso serían dos
copias de la misma validación que pueden divergir.

Convención de nombres: DEV -> "dev", PRO -> "prod". PRO es la excepción
al simple `.lower()`, igual que en los topics de Kafka de ingestion (los
existentes en Aiven usan "prod-", no "pro-").

Nota sobre PRE: ingestion admite DEV/PRE/PRO, aquí solo DEV/PRO. El
oráculo no tiene entorno de preproducción propio; añadirlo es sumar la
entrada a los dos diccionarios de abajo y crear la tabla.
"""

from __future__ import annotations

import os
import re

from dotenv import load_dotenv

load_dotenv()

NAUTIQ_ENV = os.getenv("NAUTIQ_ENV", "DEV").upper()

_ENV_SLUG = {"DEV": "dev", "PRO": "prod"}
if NAUTIQ_ENV not in _ENV_SLUG:
    raise ValueError(f"NAUTIQ_ENV={NAUTIQ_ENV!r} inválido; debe ser DEV o PRO.")

#: Nombre corto del entorno ("dev" / "prod"), tal y como aparece en las
#: rutas de ADLS y en el sufijo de las tablas.
ENV_SLUG = _ENV_SLUG[NAUTIQ_ENV]

# Tabla de recomendaciones por entorno.
_TABLA_RECOMENDACIONES = {
    "DEV": "oracle_recommendations_dev",
    "PRO": "oracle_recommendations_prod",
}

_NOMBRE_TABLA_VALIDO = re.compile(r"^[a-z_][a-z0-9_]*$")


def _resolver_tabla_recomendaciones() -> str:
    """
    Tabla de recomendaciones para este entorno, con override opcional.

    El nombre acaba interpolado en el SQL de db_conn (los identificadores
    no admiten parámetros `%s` en Postgres), así que el override se valida
    contra un patrón estricto: sin esa comprobación, quien controlase la
    variable de entorno controlaría un trozo de la sentencia. Los valores
    del diccionario son literales del código y no necesitan validarse,
    pero pasan por el mismo sitio para que la garantía sea una sola.
    """
    nombre = os.getenv("ORACLE_RECOMMENDATIONS_TABLE") or _TABLA_RECOMENDACIONES[NAUTIQ_ENV]
    if not _NOMBRE_TABLA_VALIDO.match(nombre):
        raise ValueError(
            f"ORACLE_RECOMMENDATIONS_TABLE={nombre!r} inválido: solo se admiten "
            "minúsculas, dígitos y guion bajo (sin esquema, sin comillas)."
        )
    return nombre


#: Tabla de Supabase donde el oráculo publica y de la que lee el historial.
TABLA_RECOMENDACIONES = _resolver_tabla_recomendaciones()


if __name__ == "__main__":
    print(f"NAUTIQ_ENV={NAUTIQ_ENV}  ->  slug={ENV_SLUG!r}")
    print(f"Tabla de recomendaciones: public.{TABLA_RECOMENDACIONES}")
