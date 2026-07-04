"""
Adapter de la conexión WebSocket de AISStream.

Oculta los detalles de red y expone un generador asíncrono con **reconexión
automática y backoff exponencial. AISStream limita a UNA
conexión por API key y exige el mensaje de suscripción en los primeros 3 s.
"""

import asyncio
import json

import websockets

_URL = "wss://stream.aisstream.io/v0/stream"


class AISStreamClient:
    """Cliente resiliente de AISStream."""

    def __init__(self, api_key: str, url: str = _URL,
                 max_backoff: float = 60.0):
        self.api_key = api_key
        self.url = url
        self.max_backoff = max_backoff

    def _subscription(self, bounding_boxes, message_types, filter_mmsis=None) -> dict:
        msg = {"APIKey": self.api_key, "BoundingBoxes": bounding_boxes}
        if message_types:
            msg["FilterMessageTypes"] = message_types
        if filter_mmsis:
            # AISStream limita a 50 MMSI por conexión.
            msg["FiltersShipMMSI"] = [str(m) for m in filter_mmsis][:50]
        return msg

    async def stream(self, bounding_boxes, message_types=None, filter_mmsis=None):
        """
        Generador asíncrono de mensajes con reconexión + backoff exponencial.
        Reintenta indefinidamente ante cortes de red; se detiene con CancelledError.
        """
        backoff = 1.0
        subscription = self._subscription(bounding_boxes, message_types, filter_mmsis)
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    await ws.send(json.dumps(subscription))
                    backoff = 1.0  # conexión sana -> resetea backoff
                    async for raw in ws:
                        yield json.loads(raw)
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.ConnectionClosed as e:
                print(f"[ADVERTENCIA][AIS] Desconectado ({e}); reintento en {backoff:.0f}s")
            except Exception as e:  # noqa: BLE001 — resiliencia operacional
                print(f"[ERROR][AIS] {type(e).__name__}: {e}; reintento en {backoff:.0f}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.max_backoff)
