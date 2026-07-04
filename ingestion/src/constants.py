"""Constantes de dominio de Ingestion (puertos objetivo, tipos de buque)."""

import os

# ==========================================
# PUERTOS OBJETIVO (bounding boxes + destinos AIS)
# ==========================================
# Formato AISStream: [[[lat1, lon1], [lat2, lon2]]].
PORTS = {
    "valencia": {
        "locode": "ESVLC",
        "bbox": [[[39.176027, -0.344696], [39.659786, 0.466919]]],
        "dest_keywords": ["VAL", "VLC", "ESVLC"],
    },
    "algeciras": {
        "locode": "ESALG",
        "bbox": [[[35.997, -5.520], [36.180, -5.330]]],
        "dest_keywords": ["ALG", "ESALG", "ALGECIRAS"],
    },
    "barcelona": {
        "locode": "ESBCN",
        "bbox": [[[41.300, 2.090], [41.400, 2.260]]],
        "dest_keywords": ["BCN", "ESBCN", "BARCELONA"],
    },
}

# Mediterráneo occidental: cobertura común de aproximación a los tres puertos.
WESTERN_MED_BBOX = [[[35.0, -6.0], [44.0, 10.0]]]

# Tipos de barco de carga según el estándar AIS (70-79).
CARGO_SHIP_TYPES = set(range(70, 80))

# ==========================================
# OPERACIÓN
# ==========================================
# Conexiones AIS concurrentes (paralelismo del tracker). AISStream limita a 1 por
# API key; >1 requiere keys/cuentas adicionales.
AIS_MAX_CONNECTIONS = int(os.getenv("AIS_MAX_CONNECTIONS", "1"))
# Rate limit defensivo de publicación a Kafka (mensajes/seg, 0 = sin límite).
PUBLISH_RATE_LIMIT = int(os.getenv("PUBLISH_RATE_LIMIT", "0"))
# Ráfaga tolerada por el rate limit tras un período ocioso (nº de mensajes, 1 = sin ráfaga).
PUBLISH_RATE_BURST = int(os.getenv("PUBLISH_RATE_BURST", "1"))
# Duración de la fase de scraping de objetivos (s).
SCRAPER_DURATION_SECONDS = int(os.getenv("SCRAPER_DURATION_SECONDS", str(5 * 60)))
