import os
from confluent_kafka import Producer


class KafkaPublisher:
    """
    Conexión base a Aiven Kafka.
    El desarrollo de la lógica de publicación queda a cargo del Data Engineer.
    """

    def __init__(self, certs: dict):
        self.certs = certs

        # Configuramos el cliente de Kafka según el entorno
        kafka_conf = {
            "bootstrap.servers": os.getenv("KAFKA_BROKER_URL"),
            "security.protocol": "SSL",
            "ssl.ca.location": certs["ca"],
            "ssl.certificate.location": certs["cert"],
            "ssl.key.location": certs["key"],
        }

        # Inicializamos la conexión al clúster
        self.producer = Producer(kafka_conf)
        print(f"[EXITO] Conectado a Aiven usando certificados en: {certs['ca']}")

    async def publish(self, topic: str, message: dict):
        # TODO: Implementar lógica de envío a Kafka
        pass
