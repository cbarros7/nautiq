import asyncio
import websockets
import json

class AISStreamAdapter:
    """
    Patrón Adapter para la conexión con el WebSocket de AISStream.
    Oculta los detalles de bajo nivel de la red y expone un generador asíncrono.
    """
    def __init__(self, api_key: str, url: str = "wss://stream.aisstream.io/v0/stream"):
        self.api_key = api_key
        self.url = url

    async def subscribe(self, bounding_boxes=None, filter_mmsis=None, message_types=None):
        """Genera un stream de mensajes de telemetría."""
        subscribe_message = {
            "APIKey": self.api_key,
        }
        if bounding_boxes:
            subscribe_message["BoundingBoxes"] = bounding_boxes
        if filter_mmsis:
            # AISStream limita a un máximo por conexión, pero el adapter lo abstrae
            subscribe_message["FiltersShipMMSI"] = [str(m) for m in filter_mmsis][:50]
        if message_types:
            subscribe_message["FilterMessageTypes"] = message_types

        try:
            async with websockets.connect(self.url) as websocket:
                await websocket.send(json.dumps(subscribe_message))
                async for msg_str in websocket:
                    yield json.loads(msg_str)
        except asyncio.CancelledError:
            print("[INFO][AISClient] Conexión cerrada intencionalmente.")
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[ADVERTENCIA][AISClient] Desconectado del servidor AIS: {e}")
        except Exception as e:
            print(f"[ERROR][AISClient] Error inesperado: {e}")
