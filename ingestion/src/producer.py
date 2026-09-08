"""
Servicio de ingesta AIS (Facade) — production-ready.

Responsabilidad ÚNICA: adquirir AIS crudo y publicarlo validado en Kafka.
Sin lógica de negocio (eso es Flink), sin selección de buques, sin enriquecimiento.

Un solo proceso con dos conexiones AIS perpetuas (AISStream limita a 1 por API key):

  ShipStaticData -> validar contrato -> vessel.static.raw
  PositionReport -> validar contrato -> vessel.positions.raw

Se publica **todo** lo que entrega la suscripción. El único criterio de selección es la
bounding box, que aplica AISStream: si un buque sale del área deja de llegar, sin estado
en el productor. Sobre ese crudo, Flink deriva lo que necesite (flota con destino a los
tres puertos, atraques, cupo, congestión) — y puede rehacer cualquier criterio a
posteriori, algo imposible si se filtrase aquí.
"""

import asyncio
import sys

from . import config, constants
from .ais.client import AISStreamClient
from .ais.publisher import build_dlq_publisher, build_publishers
from .ais.tracker import AISTracker


async def _build_feeds():
    """
    Reparte los dos tipos de mensaje entre las API keys disponibles.

    AISStream admite UNA conexión por key: con dos keys se dedica una conexión a cada
    tipo (aísla el caudal de posiciones del de estáticas, de modo que un backoff en uno
    no ciega al otro); con una sola key, ambos tipos comparten conexión.

    Con `AIS_SYNTHETIC=true` (temporal, ver `ais/synthetic.py`) se sustituye por un
    único feed generado localmente, con la misma interfaz `.stream()`: el tracker no
    distingue el origen de los mensajes.
    """
    if constants.AIS_SYNTHETIC:
        from .ais import synthetic
        fleet = await synthetic.build_fleet()
        con_imo = sum(1 for v in fleet.vessels if v.imo)
        print(f"[SINTETICO] {len(fleet.vessels)} buques simulados "
              f"({con_imo} con IMO real de THETIS).")
        return [(synthetic.SyntheticAISClient(fleet), ["ShipStaticData", "PositionReport"])]

    static_client = AISStreamClient(config.AISSTREAM_API_KEY)
    if config.AISSTREAM_AUX_API_KEY:
        return [
            (static_client, ["ShipStaticData"]),
            (AISStreamClient(config.AISSTREAM_AUX_API_KEY), ["PositionReport"]),
        ]
    print("[ADVERTENCIA] Sin AISSTREAM_AUX_API_KEY: ambos tipos por una sola conexión.")
    return [(static_client, ["PositionReport", "ShipStaticData"])]


async def run_ingestion_service():
    print("[INICIO] SERVICIO DE INGESTA AIS -> KAFKA")

    if constants.AIS_SYNTHETIC:
        print("[SINTETICO] Generando datos sinteticos: NO hay conexion a AISStream real. "
              "Desactivar con AIS_SYNTHETIC=false en cuanto el proveedor se recupere.")
    elif not config.AISSTREAM_API_KEY:
        print("[ERROR] AISSTREAM_API_KEY no encontrada en la configuración.")
        sys.exit(1)

    tracker = AISTracker(
        build_publishers(),
        rate_limit=constants.PUBLISH_RATE_LIMIT,
        rate_burst=constants.PUBLISH_RATE_BURST,
        dlq_pub=build_dlq_publisher(),
    )

    await tracker.run(await _build_feeds(), constants.AIS_COVERAGE_BBOX,
                      stats_interval=constants.STATS_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(run_ingestion_service())
    except KeyboardInterrupt:
        print("\n[INTERRUPCIÓN] Servicio de ingesta detenido por el usuario.")
