import asyncio
from .. import constants
from ..core.ais_client import AISStreamAdapter
from ..core.kafka_publisher import KafkaPublisher


class TelemetryTracker:
    """
    Servicio de Dominio (Capa de Ingesta).
    Patrón Observer: Monitoriza eventos satelitales y los publica en Kafka.
    (La lógica de transformación y validación queda delegada al Data Engineer).
    """

    def __init__(self, ais_client: AISStreamAdapter, kafka_pub: KafkaPublisher):
        self.ais_client = ais_client
        self.kafka_pub = kafka_pub

    async def monitor_fleet_and_port(self, target_mmsis: set, duration: int):
        if not target_mmsis:
            print("[INFO] No hay barcos en la flota. Se omite rastreo.")
            return

        print(f"[INICIO] Monitorizando {len(target_mmsis)} barcos por {duration}s...")
        queue = asyncio.Queue()

        # 1. Tarea Productora (Listener del WebSocket)
        async def ais_listener_task():
            stream = self.ais_client.subscribe(
                bounding_boxes=constants.GLOBAL_BOUNDING_BOX,
                filter_mmsis=list(target_mmsis),
                message_types=["PositionReport"],
            )
            async for msg in stream:
                await queue.put(msg)

        # 2. Tarea Consumidora (Procesamiento y publicación a Kafka)
        async def processor_task():
            while True:
                data = await queue.get()

                if data.get("MessageType") == "PositionReport":
                    msg_payload = data["Message"]["PositionReport"]

                    # Imprimimos en consola para verificar que los WebSockets funcionan
                    mmsi = msg_payload.get("UserID", "Desconocido")
                    print(f"[TEST LOCAL] Telemetría recibida del barco MMSI: {mmsi}")

                    # TODO (Data Engineer):
                    # 1. Parsear el payload crudo de AISStream.
                    # 2. Validar contra el contrato de datos usando Pydantic.
                    # 3. Generar un identificador de linaje (ULID).
                    # 4. Obtener APP_ENV desde config.py para prefijar el tópico (ej: "dev_bronze.ais.telemetry")
                    # 5. Publicar usando: await self.kafka_pub.publish(topic=TOPIC_NAME, message=msg_payload)
                    # 6. Otra?? Siente libre de robustecer y mirar casuisticas que no se contempla hasta aqui.
                    # Esta es la MVP que estuve haciendo que pueede servirgte de base.

                queue.task_done()

        # Orquestación de subrutinas asíncronas
        tasks = [
            asyncio.create_task(ais_listener_task()),
            asyncio.create_task(processor_task()),
        ]

        # Mantener ejecución por el tiempo configurado
        await asyncio.sleep(duration)

        # Cierre controlado
        print("[FIN] Tiempo límite alcanzado. Cancelando tareas...")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
