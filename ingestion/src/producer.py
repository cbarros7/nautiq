import asyncio
import sys
import time

from .config import ConfigProvider, AISSTREAM_API_KEY
from . import constants
from .core.ais_client import AISStreamAdapter
from .core.kafka_publisher import KafkaPublisher
from .services.target_scraper import TargetScraper
from .services.telemetry_tracker import TelemetryTracker


async def run_producer_orchestrator():
    """
    Patrón Facade.
    Punto de entrada unificado para la aplicación de ingesta.
    """
    print("[INICIO] NÚCLEO DE INGESTA (PRODUCER ORCHESTRATOR)")

    if not AISSTREAM_API_KEY:
        print("[ERROR] AISSTREAM_API_KEY no encontrada en la configuración.")
        sys.exit(1)

    # 1. Inicializar dependencias / Infraestructura (Inyección de Dependencias)
    config_prov = ConfigProvider()
    ais_client = AISStreamAdapter(api_key=AISSTREAM_API_KEY)

    # En producción este adapter leerá los certificados de Vault
    kafka_certs = config_prov.get_kafka_certs()
    kafka_pub = KafkaPublisher(certs=kafka_certs)

    # 2. Inicializar Servicios (Reglas de negocio)
    scraper = TargetScraper(ais_client=ais_client)
    tracker = TelemetryTracker(ais_client=ais_client, kafka_pub=kafka_pub)

    # 3. Flujo Lógico de Ingesta (El pipeline)
    print("--- FASE 1: ADQUISICIÓN DE OBJETIVOS ---")
    target_mmsis = await scraper.find_fleet_to_valencia(
        duration=constants.SCRAPER_DURATION_SECONDS
    )

    if not target_mmsis:
        print("[INFO] No se encontraron barcos de carga hacia Valencia. Finalizando.")
        return

    print(
        f"\n--- FASE 2: RASTREO Y PUBLICACIÓN A KAFKA ({len(target_mmsis)} barcos) ---"
    )
    await tracker.monitor_fleet_and_port(
        target_mmsis=target_mmsis, duration=constants.TRACKER_DURATION_SECONDS
    )

    print("[FIN] ORQUESTADOR FINALIZADO CON ÉXITO")


if __name__ == "__main__":
    try:
        asyncio.run(run_producer_orchestrator())
    except KeyboardInterrupt:
        print("\n[INTERRUPCIÓN] Orquestador detenido por el usuario.")
