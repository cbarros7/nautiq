"""
Job principal de Flink para detección de anomalías.
Deberá contener:
- Definición de la fuente Kafka (Source).
- Cálculos geométricos simples (ej. ETA crudo basado en velocidad y destino).
- Detección de congestión.
- Definición del sumidero (Sink) que dispara peticiones HTTP (Webhook) hacia la API Cognitiva.
"""
