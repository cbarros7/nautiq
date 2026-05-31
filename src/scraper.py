import asyncio
import websockets
import json
import os
import time

import config


async def run_scraper():
    if not config.AISSTREAM_API_KEY:
        print("[ERROR] AISSTREAM_API_KEY no encontrada en .env")
        return

    print(
        "[INICIO] Iniciando Scraper Global. Buscando buques de carga hacia Valencia..."
    )
    start_time = time.time()
    targets = set()

    os.makedirs(config.TMP_DIR, exist_ok=True)

    subscribe_message = {
        "APIKey": config.AISSTREAM_API_KEY,
        "BoundingBoxes": config.GLOBAL_BOUNDING_BOX,
        "FilterMessageTypes": ["ShipStaticData"],
    }

    try:
        async with websockets.connect(config.AISSTREAM_URL) as websocket:
            await websocket.send(json.dumps(subscribe_message))

            # Limitar la ejecución a 5 minutos (evitar un bucle infinito)
            while time.time() - start_time < config.SCRAPER_DURATION_SECONDS:
                try:
                    # Timeout pequeño en recv para poder chequear el tiempo en el while
                    message_json = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    message = json.loads(message_json)

                    if message.get("MessageType") == "ShipStaticData":
                        data = message.get("Message", {}).get("ShipStaticData", {})
                        ship_type = data.get("Type", 0)
                        destination = data.get("Destination", "").upper()
                        mmsi = data.get("UserID")

                        # Filtrar barcos de carga dirigidos a Valencia
                        if ship_type in config.CARGO_SHIP_TYPES and mmsi:
                            if "VAL" in destination or "VLC" in destination:
                                if mmsi not in targets:
                                    targets.add(mmsi)
                                    print(
                                        f"[INFO] Nuevo barco de carga: MMSI {mmsi} | Tipo {ship_type} | Dest. {destination}"
                                    )

                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    print(f"[ADVERTENCIA] Conexión cerrada por el servidor: {e}")
                    break
    except Exception as e:
        print(f"[ERROR] Error crítico en el scraper: {e}")

    # Guardar resultados en el JSON temporal
    targets_list = list(targets)
    with open(config.MMSI_TARGETS_FILE, "w") as f:
        json.dump(targets_list, f)

    print(
        f"\n[FIN] Scraper finalizado. Se encontraron {len(targets_list)} barcos de carga."
    )
    print(f"[INFO] Lista de MMSIs guardada en {config.MMSI_TARGETS_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(run_scraper())
    except KeyboardInterrupt:
        print("\n[INTERRUPCIÓN] Scraper interrumpido por el usuario.")
