import asyncio
import time
from .. import constants
from ..core.ais_client import AISStreamAdapter

class TargetScraper:
    """
    Servicio de Dominio (Fase 1).
    Se encarga de identificar la flota objetivo que se dirige al puerto.
    """
    def __init__(self, ais_client: AISStreamAdapter):
        self.ais_client = ais_client

    async def find_fleet_to_valencia(self, duration: int) -> set:
        """
        Escanea el tráfico global durante X segundos buscando barcos de carga hacia Valencia.
        """
        targets = set()
        start_time = time.time()
        
        print(f"[INICIO][TargetScraper] Buscando buques de carga hacia Valencia durante {duration}s...")
        
        # Nos suscribimos al stream pidiendo la data estática
        stream = self.ais_client.subscribe(
            bounding_boxes=constants.GLOBAL_BOUNDING_BOX,
            message_types=["ShipStaticData"]
        )

        try:
            async for message in stream:
                # Comprobar límite de tiempo
                if time.time() - start_time >= duration:
                    print("[INFO][TargetScraper] Tiempo límite alcanzado. Cerrando búsqueda.")
                    break
                    
                if message.get("MessageType") == "ShipStaticData":
                    data = message.get("Message", {}).get("ShipStaticData", {})
                    ship_type = data.get("Type", 0)
                    destination = data.get("Destination", "").upper()
                    mmsi = data.get("UserID")
                    
                    if ship_type in constants.CARGO_SHIP_TYPES and mmsi:
                        if "VAL" in destination or "VLC" in destination:
                            if mmsi not in targets:
                                targets.add(mmsi)
                                print(f"[INFO][TargetScraper] Nuevo barco: MMSI {mmsi} | Tipo {ship_type} | Dest. {destination}")
        except Exception as e:
            print(f"[ERROR][TargetScraper] {e}")

        print(f"[FIN][TargetScraper] Se encontraron {len(targets)} barcos objetivo.")
        return targets
