"""
Publicador Kafka con serialización **Avro vía Schema Registry** (§2 Services, §3).

Un `AvroTopicPublisher` por topic (cada uno con su esquema de `contracts/`). La
clave de partición es el **MMSI** (orden causal por buque en Flink; evita el
round-robin). El **ULID** de linaje viaja en los *headers* de Kafka.

`DLQPublisher` publica en JSON plano (sin Avro) los mensajes que no superan el
contrato Pydantic, incluyendo la razón del fallo.
"""

from __future__ import annotations

import json
from pathlib import Path

import ulid
from confluent_kafka import Producer, SerializingProducer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import StringSerializer

from .. import config

_CONTRACTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "contracts"


class AvroTopicPublisher:
    """Productor SSL + Avro para un único topic/esquema."""

    def __init__(self, topic: str, schema_file: str):
        self.topic = topic
        schema_str = (_CONTRACTS_DIR / schema_file).read_text(encoding="utf-8")

        sr_conf = {"url": config.SCHEMA_REGISTRY_URL}
        if config.SCHEMA_REGISTRY_AUTH:
            sr_conf["basic.auth.user.info"] = config.SCHEMA_REGISTRY_AUTH
        self._sr = SchemaRegistryClient(sr_conf)
        self._value_serializer = AvroSerializer(self._sr, schema_str)
        self._key_serializer = StringSerializer("utf_8")

        self._producer = SerializingProducer(
            {
                "bootstrap.servers": config.KAFKA_BROKER_URL,
                "security.protocol": "SSL",
                "ssl.ca.location": config.KAFKA_CERTS["ca"],
                "ssl.certificate.location": config.KAFKA_CERTS["cert"],
                "ssl.key.location": config.KAFKA_CERTS["key"],
                "key.serializer": self._key_serializer,
                "value.serializer": self._value_serializer,
            }
        )

    def publish(self, value: dict, *, mmsi: int, correlation_id: str | None = None) -> None:
        """Publica `value` con MMSI como key y ULID en headers (linaje)."""
        headers = [("correlation_id", (correlation_id or str(ulid.ULID())).encode())]
        self._producer.produce(
            topic=self.topic,
            key=str(mmsi),
            value=value,
            headers=headers,
            on_delivery=self._on_delivery,
        )
        self._producer.poll(0)  # sirve callbacks sin bloquear

    @staticmethod
    def _on_delivery(err, msg):
        if err is not None:
            print(f"[ERROR][Kafka] fallo de entrega en {msg.topic()}: {err}")

    def flush(self, timeout: float = 10.0) -> int:
        """Vacía el buffer; devuelve mensajes pendientes (0 = todo entregado)."""
        return self._producer.flush(timeout)


_SSL_CONF = {
    "bootstrap.servers": config.KAFKA_BROKER_URL,
    "security.protocol": "SSL",
    "ssl.ca.location": config.KAFKA_CERTS["ca"],
    "ssl.certificate.location": config.KAFKA_CERTS["cert"],
    "ssl.key.location": config.KAFKA_CERTS["key"],
}


class DLQPublisher:
    """Publica mensajes rechazados por el contrato Pydantic en JSON plano (sin Avro)."""

    def __init__(self, topic: str):
        self.topic = topic
        self._producer = Producer(_SSL_CONF)

    def publish(self, raw_message: dict, *, reason: str) -> None:
        """Publica el mensaje original + razón del fallo. MMSI como key si está disponible."""
        mmsi = (raw_message.get("MetaData", {}).get("MMSI")
                or raw_message.get("Message", {})
                       .get(raw_message.get("MessageType", ""), {})
                       .get("UserID"))
        payload = json.dumps({
            "reason": reason,
            "message_type": raw_message.get("MessageType"),
            "raw": raw_message,
        }, default=str).encode()
        headers = [("correlation_id", str(ulid.ULID()).encode())]
        self._producer.produce(
            topic=self.topic,
            key=str(mmsi) if mmsi else None,
            value=payload,
            headers=headers,
            on_delivery=self._on_delivery,
        )
        self._producer.poll(0)

    @staticmethod
    def _on_delivery(err, msg):
        if err is not None:
            print(f"[ERROR][DLQ] fallo de entrega en {msg.topic()}: {err}")

    def flush(self, timeout: float = 10.0) -> int:
        return self._producer.flush(timeout)


def build_publishers() -> dict[str, AvroTopicPublisher]:
    """Crea los publicadores de los dos topics AIS (topics obligatorios vía entorno)."""
    if not config.TOPIC_POSITIONS or not config.TOPIC_STATIC:
        raise RuntimeError(
            "Faltan los topics en el entorno: define KAFKA_TOPIC_POSITIONS y "
            "KAFKA_TOPIC_STATIC en el .env."
        )
    return {
        "position": AvroTopicPublisher(config.TOPIC_POSITIONS, "ais_position_v1.avsc"),
        "static": AvroTopicPublisher(config.TOPIC_STATIC, "ais_static_v1.avsc"),
    }


def build_dlq_publisher() -> DLQPublisher | None:
    """Crea el publicador DLQ si KAFKA_TOPIC_DLQ está definido; None si no."""
    return DLQPublisher(config.TOPIC_DLQ) if config.TOPIC_DLQ else None
