"""Constantes de dominio de Ingestion (área de cobertura AIS)."""

import os

# ==========================================
# ÁREA DE COBERTURA AIS
# ==========================================
# Formato AISStream: lista de cajas, cada caja [[lat1, lon1], [lat2, lon2]].
#AISStream ordena [lat, lon]
#
# Mediterráneo completo hasta Creta + aproximación atlántica hasta las Azores:
#   lat  26.90°N .. 45.89°N   (bajo Canarias hasta el Adriático norte)
#   lon -25.84°E .. 25.40°E   (Azores hasta el Egeo)
# Cubre los tres puertos objetivo, el Estrecho de Gibraltar y las rutas de entrada por
# el Atlántico. Queda FUERA el Mediterráneo oriental: Chipre, Levante, Alejandría,
# Suez y el Bósforo — los buques que vienen de ahí aparecen al cruzar los 25.4°E.
MEDITERRANEAN_BBOX = [[[26.90248, -25.83984], [45.89001, 25.40039]]]

# Único criterio de selección del productor, y lo aplica AISStream en el servidor: se
# entrega lo que cae dentro del área y nada más, así que un buque que sale deja de
# llegar sin que el productor mantenga estado. Todo lo que entra se publica en crudo;
# elegir qué buques interesan (carga, destino, atraque, cupo) es de Flink.
# Para cubrir otras regiones se añaden cajas a la lista.
AIS_COVERAGE_BBOX = MEDITERRANEAN_BBOX

# ==========================================
# OPERACIÓN
# ==========================================
# Rate limit defensivo de publicación a Kafka (mensajes/seg, 0 = sin límite).
PUBLISH_RATE_LIMIT = int(os.getenv("PUBLISH_RATE_LIMIT", "0"))
# Ráfaga tolerada por el rate limit tras un período ocioso (nº de mensajes, 1 = sin ráfaga).
PUBLISH_RATE_BURST = int(os.getenv("PUBLISH_RATE_BURST", "1"))
# Cadencia del informe de estado del proceso perpetuo (s, 0 = sin informe).
STATS_INTERVAL_SECONDS = int(os.getenv("STATS_INTERVAL_SECONDS", "60"))
