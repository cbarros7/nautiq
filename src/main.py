import asyncio
from scraper import run_scraper
from tracker import main as run_tracker


async def main():
    print("[INICIO] FASE 1: EJECUTANDO SCRAPER DE FLOTA")
    await run_scraper()

    print("[INICIO] FASE 2: EJECUTANDO TRACKER DE PUERTO")
    await run_tracker()

    print("\n[ÉXITO] Ejecución completa de Scraper y Tracker finalizada.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INTERRUPCIÓN] Ejecución general detenida por el usuario.")
