import os

# ==========================================
# CONSTANTES DE NEGOCIO Y DOMINIO
# ==========================================

# Bounding box global para buscar barcos en todo el mundo
GLOBAL_BOUNDING_BOX = [[[-90, -180], [90, 180]]]

# Bounding box del Puerto de Valencia y alrededores
VALENCIA_BOUNDING_BOX = [[[39.176027, -0.344696], [39.659786, 0.466919]]]

# Tipos de barcos de carga según el estándar AIS (70-79)
CARGO_SHIP_TYPES = set(range(70, 80))


# ==========================================
# CONFIGURACIÓN TEMPORAL DEL PROTOTIPO MVP
# ==========================================

# Tiempos de ejecución en segundos
SCRAPER_DURATION_SECONDS = 5 * 60  # 5 minutos
TRACKER_DURATION_SECONDS = 30 * 60  # 30 minutos

# Ruta para el JSON temporal (relativa a la raíz del proyecto)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_DIR = os.path.join(BASE_DIR, "tmp")
MMSI_TARGETS_FILE = os.path.join(TMP_DIR, "mmsi_targets.json")
