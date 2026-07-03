"""
Servicio de ingesta AIS (Facade) — production-ready.

Responsabilidad ÚNICA: adquirir datos de AIS y publicarlos validados en Kafka.
Sin lógica de negocio (eso es Flink), sin DLQ, sin enriquecimiento.

  1. Scraper  -> descubre la flota objetivo hacia Valencia/Algeciras/Barcelona.
  2. Tracker  -> consume los dos endpoints AIS y publica en dos topics Avro:
                 PositionReport -> vessel.positions.raw
                 ShipStaticData -> vessel.static.raw

La carga de datos de referencia (THETIS, UN/LOCODE -> PostgreSQL) es independiente
y se ejecuta aparte (`python -m ingestion.src.reference.thetis|locode`).
"""

import asyncio
import sys

from . import config, constants
from .ais import scraper
from .ais.client import AISStreamClient
from .ais.publisher import build_dlq_publisher, build_publishers
from .ais.tracker import AISTracker


async def run_ingestion_service():
    print("[INICIO] SERVICIO DE INGESTA AIS -> KAFKA")

    if not config.AISSTREAM_API_KEY:
        print("[ERROR] AISSTREAM_API_KEY no encontrada en la configuración.")
        sys.exit(1)

    client = AISStreamClient(config.AISSTREAM_API_KEY)

    # 1. Descubrimiento de la flota objetivo (3 puertos).
    targets = await scraper.find_target_fleet(client, constants.SCRAPER_DURATION_SECONDS)

    # 2. Publicación a Kafka (Avro + Schema Registry).
    publishers = build_publishers()
    dlq_pub = build_dlq_publisher()
    tracker = AISTracker(client, publishers, rate_limit=constants.PUBLISH_RATE_LIMIT,
                         dlq_pub=dlq_pub)

    # Paralelismo: una conexión por puerto si la cuota de keys lo permite; si no,
    # una sola conexión sobre el Mediterráneo occidental (cubre los tres puertos).
    if constants.AIS_MAX_CONNECTIONS >= len(constants.PORTS):
        bboxes = [p["bbox"] for p in constants.PORTS.values()]
    else:
        bboxes = [constants.WESTERN_MED_BBOX]

    await tracker.run(bboxes, filter_mmsis=list(targets) or None)


if __name__ == "__main__":
    try:
        asyncio.run(run_ingestion_service())
    except KeyboardInterrupt:
        print("\n[INTERRUPCIÓN] Servicio de ingesta detenido por el usuario.")
