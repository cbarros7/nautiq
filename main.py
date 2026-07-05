import asyncio

from ingestion.src.producer import run_ingestion_service


async def main():
    await run_ingestion_service()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INTERRUPCIÓN] Ejecución detenida por el usuario.")
