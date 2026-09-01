"""
Comprueba que la Function desplegada sirve realmente el build esperado.

Por qué sondea en vez de mirar una vez
--------------------------------------
OneDeploy responde 202 en cuanto acepta el paquete, pero el host tarda en
recargar: medido contra la app real, el build nuevo empieza a servirse
~80 s después. Una comprobación única tras un `sleep` fijo fallaría de
forma intermitente aunque el despliegue fuese correcto.

Y los reintentos de curl no sirven para esto: la app responde 200 durante
toda la ventana, solo que con el código anterior. Para curl eso es un
éxito, así que no reintenta — hay que comparar el contenido, no el
código HTTP.

Qué verifica
------------
1. `build` == el commit desplegado. Sin esto, un despliegue que no llega
   pasa por bueno: la app sigue respondiendo igual con código viejo.
2. `entorno` == el esperado. NAUTIQ_ENV mal puesta no da ningún error;
   simplemente escribe en las tablas y carpetas del otro entorno.

Uso:
    python scripts/verificar_despliegue.py <host> <build_esperado> <DEV|PRO>
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

INTENTOS = 12
ESPERA_S = 15  # 12 x 15 s = 3 min de margen (el peor caso medido fue ~80 s)


def _consultar_health(host: str) -> dict | None:
    """Devuelve el JSON de /api/health, o None si aún no responde."""
    try:
        with urllib.request.urlopen(f"https://{host}/api/health", timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"  (sin respuesta todavía: {type(exc).__name__})")
        return None


def verificar(host: str, build_esperado: str, entorno_esperado: str) -> dict:
    print(f"Sondeando https://{host}/api/health")
    salud = None

    for intento in range(1, INTENTOS + 1):
        time.sleep(ESPERA_S)
        salud = _consultar_health(host)
        if salud is None:
            continue

        build = salud.get("build", "")
        print(f"  intento {intento}/{INTENTOS}: build={build}")
        if build == build_esperado:
            break
    else:
        actual = (salud or {}).get("build", "sin respuesta")
        print(
            f"::error::Tras {INTENTOS * ESPERA_S}s la app sigue sirviendo build "
            f"'{actual}' en vez de '{build_esperado}'. El paquete se aceptó pero "
            "no llegó a cargarse; revisa los logs de despliegue de la Function App."
        )
        raise SystemExit(1)

    entorno = salud.get("entorno", "")
    if entorno != entorno_esperado:
        print(
            f"::error::La app reporta NAUTIQ_ENV='{entorno}' y se esperaba "
            f"'{entorno_esperado}'. Revisa las Application Settings: con el valor "
            "equivocado escribiría en las tablas y carpetas del otro entorno."
        )
        raise SystemExit(1)

    print(f"Build confirmado: {salud['build']}")
    print(f"Entorno confirmado: {entorno} (tabla {salud.get('tabla_recomendaciones')}, "
          f"ADLS {salud.get('carpeta_adls')}, LLM {salud.get('llm_configurado')})")
    return salud


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Uso: python scripts/verificar_despliegue.py <host> <build> <DEV|PRO>")
    verificar(sys.argv[1], sys.argv[2], sys.argv[3])
