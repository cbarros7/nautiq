"""
AIS Tracker — consume los dos endpoints AIS y publica en dos topics Kafka.

Publica **todo** lo que entrega la suscripción, sin seleccionar buques:
  PositionReport  -> validar (contrato) -> Avro -> `vessel.positions.raw`
  ShipStaticData  -> validar (contrato) -> Avro -> `vessel.static.raw`

El único criterio de selección es la **bounding box de la suscripción**, y lo aplica
AISStream: si un buque sale del área deja de llegar, sin que el productor mantenga
estado alguno. Decidir qué buques interesan (carga, destino declarado, atraque, cupo)
es de Flink, que puede rehacer cualquier criterio sobre el crudo — filtrar aquí sería
irreversible.

Gestiona:
  - **Paralelismo**: una tarea asyncio por conexión AIS (una por API key).
  - **Rate limit**: token bucket asíncrono opcional para la publicación.
  - **Reintentos**: reconexión + backoff exponencial en `AISStreamClient`.

SIN lógica de negocio: nada de flota, plausibilidad ni enriquecimiento (eso es Flink).
"""

import asyncio
import time

from .client import AISStreamClient
from .models import AISPosition, AISStatic, ContractError
from .publisher import AvroTopicPublisher, DLQPublisher


class _RateLimiter:
    """Token bucket asíncrono (msgs/seg con ráfaga). rate<=0 -> sin límite."""

    def __init__(self, rate: int, burst: int = 1):
        self._rate = rate
        self._capacity = float(max(1, burst))
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._rate <= 0:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self._capacity,
                                   self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)


class AISTracker:
    """Orquesta consumo AIS -> validación de contrato -> publicación Avro."""

    def __init__(self, publishers: dict[str, AvroTopicPublisher],
                 rate_limit: int = 0, rate_burst: int = 1,
                 dlq_pub: DLQPublisher | None = None):
        self.pos_pub = publishers["position"]
        self.static_pub = publishers["static"]
        self.dlq_pub = dlq_pub
        self.limiter = _RateLimiter(rate_limit, rate_burst)
        self.stats = {"position": 0, "static": 0, "rejected": 0}
        # MessageType -> (contrato Pydantic, publicador, contador). Ambos tipos siguen
        # exactamente el mismo camino, así que la ruta es una tabla y no dos ramas.
        self._routes = {
            "PositionReport": (AISPosition, self.pos_pub, "position"),
            "ShipStaticData": (AISStatic, self.static_pub, "static"),
        }

    def _reject(self, message: dict, reason: str) -> None:
        self.stats["rejected"] += 1
        if self.dlq_pub:
            self.dlq_pub.publish(message, reason=reason)

    async def _handle(self, message: dict) -> None:
        """Valida contra el contrato y publica; lo que no cumple va a la DLQ."""
        route = self._routes.get(message.get("MessageType"))
        if route is None:
            return
        contract, pub, counter = route

        try:
            model = contract.from_message(message)
        except ContractError as e:
            self._reject(message, str(e))
            return

        await self.limiter.acquire()
        try:
            pub.publish(model.model_dump(by_alias=True), mmsi=model.mmsi)
        except Exception as e:  # noqa: BLE001 — fallo de serialización -> DLQ
            self._reject(message, f"fallo de serialización Avro: {e}")
            return
        self.stats[counter] += 1

    async def _consume(self, client: AISStreamClient, bboxes, message_types) -> None:
        """Una conexión AIS perpetua; reconecta con backoff por su cuenta."""
        stream = client.stream(bounding_boxes=bboxes, message_types=message_types)
        async for message in stream:
            await self._handle(message)

    async def _report(self, interval: int) -> None:
        """Informe periódico de estado (el proceso es perpetuo: hay que poder verlo)."""
        while True:
            await asyncio.sleep(interval)
            print(f"[ESTADO][Tracker] {self.stats}")

    async def run(self, feeds: list[tuple[AISStreamClient, list[str]]], bboxes,
                  stats_interval: int = 0) -> None:
        """
        Lanza una tarea perpetua por feed `(client, message_types)` y corre hasta
        cancelación. Con dos API keys hay un feed por tipo de mensaje; con una sola,
        un único feed con ambos tipos.
        """
        print(f"[INICIO][Tracker] {len(feeds)} conexión(es) AIS -> topics "
              f"{self.pos_pub.topic} / {self.static_pub.topic}")
        tasks = [asyncio.create_task(self._consume(c, bboxes, mt)) for c, mt in feeds]
        if stats_interval > 0:
            tasks.append(asyncio.create_task(self._report(stats_interval)))
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            self.pos_pub.flush()
            self.static_pub.flush()
            if self.dlq_pub:
                self.dlq_pub.flush()
            print(f"[FIN][Tracker] {self.stats}")
