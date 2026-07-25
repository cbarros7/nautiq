"""Constantes de dominio de Ingestion (área de cobertura AIS)."""

import os

# ==========================================
# ÁREA DE COBERTURA AIS
# ==========================================
# Formato AISStream: lista de cajas, cada caja [[lat1, lon1], [lat2, lon2]].
WESTERN_MED_BBOX = [[[35.0, -6.0], [44.0, 10.0]]]

# Único criterio de selección del productor, y lo aplica AISStream en el servidor: se
# entrega lo que cae dentro del área y nada más, así que un buque que sale deja de
# llegar sin que el productor mantenga estado. Todo lo que entra se publica en crudo;
# elegir qué buques interesan (carga, destino, atraque, cupo) es de Flink.
# Para cubrir otras regiones se añaden cajas a la lista.
AIS_COVERAGE_BBOX = WESTERN_MED_BBOX

# ==========================================
# OPERACIÓN
# ==========================================
# Rate limit defensivo de publicación a Kafka (mensajes/seg, 0 = sin límite).
PUBLISH_RATE_LIMIT = int(os.getenv("PUBLISH_RATE_LIMIT", "0"))
# Ráfaga tolerada por el rate limit tras un período ocioso (nº de mensajes, 1 = sin ráfaga).
PUBLISH_RATE_BURST = int(os.getenv("PUBLISH_RATE_BURST", "1"))
# Cadencia del informe de estado del proceso perpetuo (s, 0 = sin informe).
STATS_INTERVAL_SECONDS = int(os.getenv("STATS_INTERVAL_SECONDS", "60"))
