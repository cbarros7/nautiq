"""Shared Hypothesis strategies and pure reference math for Nautiq streaming tests."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EARTH_RADIUS_NM: float = 3440.065
SPOOFING_THRESHOLD_KNOTS: float = 50.0
MIN_ETA_SPEED_KNOTS: float = 0.5
DEFAULT_MAX_ETA_HOURS: float = 72.0

# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

st_latitude = st.floats(
    min_value=-90.0, max_value=90.0, allow_nan=False, allow_infinity=False
)

st_longitude = st.floats(
    min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False
)

st_coordinates: st.SearchStrategy[Tuple[float, float]] = st.tuples(
    st_latitude, st_longitude
)

st_mmsi: st.SearchStrategy[int] = st.integers(
    min_value=100000000, max_value=999999999
)

st_speed: st.SearchStrategy[float] = st.floats(
    min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False
)

st_nav_status: st.SearchStrategy[int] = st.integers(min_value=0, max_value=15)

st_vessel_dimensions: st.SearchStrategy[Dict[str, Any]] = st.fixed_dictionaries(
    {
        "length_m": st.floats(
            min_value=10.0, max_value=400.0, allow_nan=False, allow_infinity=False
        ),
        "beam_m": st.floats(
            min_value=3.0, max_value=65.0, allow_nan=False, allow_infinity=False
        ),
        "draught_m": st.floats(
            min_value=1.0, max_value=25.0, allow_nan=False, allow_infinity=False
        ),
        "ship_type": st.integers(min_value=70, max_value=79),
    }
)

st_port_name = st.sampled_from(
    ["VALENCIA", "ALGECIRAS", "BARCELONA", "BILBAO", "LAS PALMAS", "TANGER"]
)

st_port_dict: st.SearchStrategy[Dict[str, Any]] = st.fixed_dictionaries(
    {
        "name": st_port_name,
        "lat": st.floats(min_value=35.0, max_value=45.0, allow_nan=False, allow_infinity=False),
        "lon": st.floats(min_value=-10.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        "congestion_radius_nm": st.floats(min_value=1.0, max_value=25.0, allow_nan=False, allow_infinity=False),
        "aliases": st.lists(
            st.text(min_size=2, max_size=12, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
            min_size=1,
            max_size=5,
        ),
    }
)

st_target_ports: st.SearchStrategy[List[Dict[str, Any]]] = st.lists(
    st_port_dict, min_size=1, max_size=6, unique_by=lambda p: p["name"]
)

# ---------------------------------------------------------------------------
# Pure Reference Implementations (Nautiq Invariants)
# ---------------------------------------------------------------------------

def spherical_law_of_cosines_nm(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance in nautical miles using the spherical law of cosines with strict [-1, 1] clamping."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)

    cos_c = (
        math.sin(phi1) * math.sin(phi2)
        + math.cos(phi1) * math.cos(phi2) * math.cos(dlambda)
    )
    # Clamp to [-1.0, 1.0] to prevent math domain error (NaN) from floating-point inaccuracies
    cos_c = max(-1.0, min(1.0, cos_c))
    return EARTH_RADIUS_NM * math.acos(cos_c)


def calculate_implied_speed_knots(dist_nm: float, delta_hours: float) -> float:
    """Calculates implied vessel speed in knots. Returns 0.0 if delta_hours <= 0."""
    if delta_hours <= 0.0:
        return 0.0
    return dist_nm / delta_hours


def is_kinematic_spoofing(
    dist_nm: float,
    delta_hours: Optional[float],
    threshold_knots: float = SPOOFING_THRESHOLD_KNOTS,
) -> bool:
    """Classifies if a movement is spoofing. First reports (delta_hours is None or <= 0) are valid (not spoofing)."""
    if delta_hours is None or delta_hours <= 0.0:
        return False
    implied_speed = dist_nm / delta_hours
    return implied_speed > threshold_knots


def calculate_eta_dynamic_hours(
    dist_nm: float, speed_knots: float
) -> Optional[float]:
    """Calculates dynamic ETA in hours. Discards records where speed <= 0.5 knots."""
    if speed_knots <= MIN_ETA_SPEED_KNOTS:
        return None
    return dist_nm / speed_knots


def classify_port_vessel_status(
    lat: float,
    lon: float,
    speed: float,
    nav_status: int,
    port_lat: float,
    port_lon: float,
    port_radius_nm: float,
    max_eta_hours: float = DEFAULT_MAX_ETA_HOURS,
) -> Optional[str]:
    """
    Classifies a vessel status according to port_vessel_inventory.sql:
    - 'ATRACADO': nav_status = 5 and distance <= port_radius
    - 'FONDEADO': nav_status = 1 and distance <= port_radius
    - 'EN_CAMINO': distance > port_radius and speed > 0.5 and eta <= max_eta_hours
    - None: all other cases
    """
    dist_nm = spherical_law_of_cosines_nm(lat, lon, port_lat, port_lon)
    if dist_nm <= port_radius_nm:
        if nav_status == 5:
            return "ATRACADO"
        elif nav_status == 1:
            return "FONDEADO"
        return None
    else:
        if speed > MIN_ETA_SPEED_KNOTS:
            eta = dist_nm / speed
            if eta <= max_eta_hours:
                return "EN_CAMINO"
        return None


def assemble_alert_payload(
    mmsi: int,
    correlation_id: str,
    imo: int,
    puerto: str,
    estado: int,
    lon_buque: float,
    lat_buque: float,
    lon_port: float,
    lat_port: float,
    direccion: float,
    velocidad_buque: float,
    eslora: float,
    manga: float,
    calado_de_diseno: float,
    tipo_buque: int,
    eta_dynamic: float,
    eta_static: str,
    num_buques_atracados: List[Dict[str, Any]],
    num_buques_fondeados: List[Dict[str, Any]],
    num_buques_en_camino: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assembles the exact bi-partite JSON payload conforming to build_eta_alert_payload.sql."""
    payload_str = json.dumps(
        {
            "paquete_1": {
                "mmsi": mmsi,
                "correlation_id": correlation_id,
                "imo": imo,
                "puerto": puerto,
                "estado": estado,
                "lon_buque": lon_buque,
                "lat_buque": lat_buque,
                "lon_port": lon_port,
                "lat_port": lat_port,
                "direccion": direccion,
                "velocidad_buque": velocidad_buque,
                "eslora": eslora,
                "manga": manga,
                "calado_de_diseno": calado_de_diseno,
                "tipo_buque": tipo_buque,
                "ETA_dynamic": eta_dynamic,
                "ETA": eta_dynamic,
                "ETA_static": eta_static,
            },
            "paquete_2": {
                "puerto": puerto,
                "estados": {
                    "num_buques_atracados": num_buques_atracados,
                    "num_buques_fondeados": num_buques_fondeados,
                    "num_buques_en_camino": num_buques_en_camino,
                },
            },
        }
    )
    return json.loads(payload_str)
