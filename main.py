import asyncio
import sys

from ingestion.src.producer import run_producer_orchestrator


async def main():
    await run_producer_orchestrator()

    print("\n[ÉXITO] Ejecución completa de Scraper y Tracker finalizada.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INTERRUPCIÓN] Ejecución general detenida por el usuario.")
