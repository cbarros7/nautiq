"""
Replay de alertas reales por el oráculo, de punta a punta.

Lee un fichero de alertas capturadas de Flink (paquete_1 + paquete_2),
las inyecta en el grafo de math_oracle como si acabaran de llegar por el
webhook, y deja el resultado en los destinos REALES: Supabase
(oracle_recommendations, fuente de verdad) y ADLS Gen2 (copia analítica
para Databricks).

Sirve para tres cosas: probar el pipeline completo con datos reales,
sembrar la tabla para que el frontal tenga algo que pintar (el problema
del "arranque en frío"), y reproducir un escenario concreto en una demo.

Formato del fichero de entrada
------------------------------
Objetos JSON indentados y concatenados, SIN separador ni array
envolvente (lo que sale de volcar `json.dumps(..., indent=2)` en bucle):

    {
      "paquete_1": {...},
      "paquete_2": {...}
    }
    {
      "paquete_1": {...},
      ...

No es NDJSON, así que no se puede parsear línea a línea: se usa
`JSONDecoder.raw_decode` para ir consumiendo un objeto completo cada vez.

Uso
---
    # 3 primeras alertas (por defecto), con LLM si hay GEMINI_API_KEY
    uv run python scripts/replay_alertas.py ruta/al/fichero

    # 10 alertas saltando las 5 primeras, sin gastar cuota de Gemini
    uv run python scripts/replay_alertas.py fichero --limite 10 --desde 5 --sin-llm

    # ensayo en seco: calcula pero no escribe en Supabase ni ADLS
    uv run python scripts/replay_alertas.py fichero --dry-run

El límite por defecto es bajo a propósito: cada alerta hace 2 llamadas a
Open-Meteo, 1 a Gemini y 2 escrituras — replicar las 284 de una tacada
agota cuotas de API antes que otra cosa.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Permite ejecutar el script directamente (python scripts/replay_alertas.py)
# además de como módulo: la raíz de `api/` tiene que estar en sys.path para
# que `import app.agents...` resuelva.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.math_oracle import oracle_graph  # noqa: E402
from app.agents.tools import adls_conn, db_conn  # noqa: E402

logger = logging.getLogger("replay")


def cargar_alertas(ruta: Path) -> list[dict]:
    """Parsea el fichero de objetos JSON concatenados (ver docstring del módulo)."""
    contenido = ruta.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    alertas: list[dict] = []
    pos = 0
    while pos < len(contenido):
        while pos < len(contenido) and contenido[pos] in " \t\n\r":
            pos += 1
        if pos >= len(contenido):
            break
        obj, pos = decoder.raw_decode(contenido, pos)
        alertas.append(obj)
    return alertas


def _config_llm(sin_llm: bool) -> dict:
    """Inyecta Gemini en el grafo si hay API key y no se pidió --sin-llm."""
    if sin_llm:
        print("  LLM: desactivado (--sin-llm) -> resumen determinista")
        return {}

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  LLM: sin GEMINI_API_KEY -> resumen determinista")
        return {}

    from app.agents.tools.gemini_client import crear_generar_texto

    print("  LLM: Gemini activo")
    return {"configurable": {"generar_texto": crear_generar_texto(api_key)}}


def _desactivar_escrituras() -> None:
    """--dry-run: calcula todo pero no toca Supabase ni ADLS."""
    db_conn.buscar_session_id = lambda mmsi, puerto, horas=24: None
    db_conn.guardar_recomendacion = lambda **kw: True
    db_conn.get_historial_recomendaciones = lambda mmsi, puerto, limite=3, horas=24: []
    adls_conn.esta_configurado = lambda: False


def replay(
    ruta: Path,
    limite: int = 3,
    desde: int = 0,
    sin_llm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Ejecuta el replay y devuelve un resumen {procesadas, ok, fallidas}."""
    alertas = cargar_alertas(ruta)
    seleccion = alertas[desde : desde + limite]

    print("=" * 72)
    print(f"  REPLAY DE ALERTAS — {ruta.name}")
    print("=" * 72)
    print(f"  Alertas en el fichero: {len(alertas)}")
    print(f"  A procesar: {len(seleccion)} (desde el índice {desde})")
    if dry_run:
        print("  MODO: dry-run (NO se escribe en Supabase ni ADLS)")
        _desactivar_escrituras()
    else:
        print(f"  Supabase: {db_conn.DB_CONFIG['host']}")
        print(
            f"  ADLS: {adls_conn.ADLS_ACCOUNT}/{adls_conn.ADLS_CONTAINER}/"
            f"{adls_conn.ADLS_PREFIX}  (configurado: {adls_conn.esta_configurado()})"
        )
    config = _config_llm(sin_llm)
    print("-" * 72)

    ok, fallidas = 0, []
    for i, alerta in enumerate(seleccion, start=1):
        p1 = alerta["paquete_1"]
        etiqueta = f"[{i}/{len(seleccion)}] mmsi={p1.get('mmsi')} puerto={p1.get('puerto')}"
        try:
            resultado = oracle_graph.invoke(
                {"paquete_1": p1, "paquete_2": alerta["paquete_2"]},
                config=config,
            )
            evento = resultado["evento_contrato"]
            reco = evento["recommendation"]
            print(
                f"  {etiqueta}\n"
                f"      event_id={evento['event_id']} session={evento['session_id']}\n"
                f"      cola: {evento['queue']['estimated_wait_hours']}h "
                f"(pos {evento['queue']['queue_position']}) | "
                f"v: {reco['recommended_speed_kn']}kn "
                f"(actual {evento['vessel']['speed_kn']}kn) | "
                f"CII {reco['cii']['ahorro_pct']}%\n"
                f"      {reco['rationale'][:110]}..."
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001 — se registra y se sigue con la siguiente
            logger.exception("%s FALLÓ", etiqueta)
            fallidas.append({"indice": desde + i - 1, "mmsi": p1.get("mmsi"), "error": repr(exc)})
            print(f"  {etiqueta} -> ERROR: {type(exc).__name__}: {exc}")

    print("-" * 72)
    print(f"  OK: {ok} | Fallidas: {len(fallidas)}")
    for f in fallidas:
        print(f"    - índice {f['indice']} (mmsi {f['mmsi']}): {f['error'][:120]}")
    print("=" * 72)

    return {"procesadas": len(seleccion), "ok": ok, "fallidas": fallidas}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fichero", type=Path, help="Fichero de alertas capturadas de Flink")
    parser.add_argument("--limite", type=int, default=3, help="Cuántas alertas procesar (def. 3)")
    parser.add_argument("--desde", type=int, default=0, help="Índice desde el que empezar (def. 0)")
    parser.add_argument("--sin-llm", action="store_true", help="No llamar a Gemini (resumen determinista)")
    parser.add_argument("--dry-run", action="store_true", help="Calcular sin escribir en Supabase ni ADLS")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="      [%(levelname)s] %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)  # el SDK loguea cada request HTTP

    resumen = replay(
        ruta=args.fichero,
        limite=args.limite,
        desde=args.desde,
        sin_llm=args.sin_llm,
        dry_run=args.dry_run,
    )
    sys.exit(1 if resumen["fallidas"] else 0)


if __name__ == "__main__":
    main()
