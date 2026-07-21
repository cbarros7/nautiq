"""
AIS Tracker — consume los dos endpoints AIS y publica en dos topics Kafka.

Responsabilidad única:
  PositionReport  -> validar (contrato) -> Avro -> topic `vessel.positions.raw`
  ShipStaticData  -> validar (contrato) -> Avro -> topic `vessel.static.raw`

Gestiona:
  - **Paralelismo**: una tarea asyncio por bounding box (`constants.AIS_MAX_CONNECTIONS`).
  - **Rate limit**: token bucket asíncrono opcional para la publicación.
  - **Reintentos**: reconexión + backoff exponencial en `AISStreamClient`.

SIN lógica de negocio: nada de plausibilidad, DLQ ni enriquecimiento (eso es Flink).
Los mensajes que no cumplen el contrato simplemente NO se publican.
"""

import asyncio
import time

from .. import constants
from .client import AISStreamClient
from .models import AISPosition, AISStatic, ContractError
from .publisher import AvroTopicPublisher, DLQPublisher


class _RateLimiter:
    """Token bucket asíncrono simple (msgs/seg). rate<=0 -> sin límite."""

    def __init__(self, rate: int):
        self._interval = 1.0 / rate if rate > 0 else 0.0
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self._interval
        if wait > 0:
            await asyncio.sleep(wait)


class AISTracker:
    """Orquesta consumo AIS -> validación -> publicación Avro a Kafka."""

    def __init__(self, client: AISStreamClient, publishers: dict[str, AvroTopicPublisher],
                 rate_limit: int = 0, dlq_pub: DLQPublisher | None = None):
        self.client = client
        self.pos_pub = publishers["position"]
        self.static_pub = publishers["static"]
        self.dlq_pub = dlq_pub
        self.limiter = _RateLimiter(rate_limit)
        self.stats = {"position": 0, "static": 0, "rejected": 0}

    async def _handle(self, message: dict) -> None:
        mtype = message.get("MessageType")
        if mtype == "PositionReport":
            try:
                pos = AISPosition.from_message(message)
            except ContractError as e:
                self.stats["rejected"] += 1
                if self.dlq_pub:
                    self.dlq_pub.publish(message, reason=str(e))
                return
            await self.limiter.acquire()
            try:
                self.pos_pub.publish(pos.model_dump(by_alias=True), mmsi=pos.mmsi)
            except Exception as e:
                self.stats["rejected"] += 1
                if self.dlq_pub:
                    self.dlq_pub.publish(message, reason=f"fallo de serialización Avro: {e}")
                return
            self.stats["position"] += 1
        elif mtype == "ShipStaticData":
            try:
                static = AISStatic.from_message(message)
            except ContractError as e:
                self.stats["rejected"] += 1
                if self.dlq_pub:
                    self.dlq_pub.publish(message, reason=str(e))
                return
            await self.limiter.acquire()
            try:
                self.static_pub.publish(static.model_dump(by_alias=True), mmsi=static.mmsi)
            except Exception as e:
                self.stats["rejected"] += 1
                if self.dlq_pub:
                    self.dlq_pub.publish(message, reason=f"fallo de serialización Avro: {e}")
                return
            self.stats["static"] += 1

    async def _consume_bbox(self, bbox, filter_mmsis) -> None:
        """Una conexión AIS (ambos endpoints) sobre un bounding box."""
        stream = self.client.stream(
            bounding_boxes=bbox,
            message_types=["PositionReport", "ShipStaticData"],
            filter_mmsis=filter_mmsis,
        )
        async for message in stream:
            await self._handle(message)

    async def run(self, bounding_boxes_list, filter_mmsis=None) -> None:
        """
        Lanza una tarea por bounding box (hasta AIS_MAX_CONNECTIONS) y corre hasta
        cancelación. Cada tarea reconecta con backoff por sí misma.
        """
        boxes = bounding_boxes_list[: constants.AIS_MAX_CONNECTIONS]
        print(f"[INICIO][Tracker] {len(boxes)} conexión(es) AIS -> topics "
              f"{self.pos_pub.topic} / {self.static_pub.topic}")
        tasks = [asyncio.create_task(self._consume_bbox(b, filter_mmsis)) for b in boxes]
        try:
            await asyncio.gather(*tasks)
        finally:
            self.pos_pub.flush()
            self.static_pub.flush()
            if self.dlq_pub:
                self.dlq_pub.flush()
            print(f"[FIN][Tracker] {self.stats}")
