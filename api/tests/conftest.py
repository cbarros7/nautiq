"""
Fixtures compartidos de los tests del oráculo.

Los tests de esta carpeta son UNITARIOS: no tocan Supabase, ni ADLS, ni
Open-Meteo, ni ningún LLM. Prueban las dos fronteras del sistema —lo que
entra por el webhook y la forma del evento que sale— con datos fijos, de
modo que puedan correr en CI sin credenciales y sin depender de que
ninguna red o cuota esté disponible.

Los datos de `alerta_valida` son una alerta REAL del fixture de Flink
(buque 990645671 rumbo a Barcelona), recortada a los campos que el
pipeline consume. Usar una alerta real y no una inventada evita que los
tests pasen con una forma de mensaje que el productor nunca emite.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agents.tools.cii_calculus import CIIResult
from app.agents.tools.kwon_euler import VelocidadJIT
from app.agents.tools.sea_route import Port, Route


@pytest.fixture
def paquete_1() -> dict:
    """Mensaje del buque que dispara la alerta (formato real de Flink)."""
    return {
        "correlation_id": "01M05SDA6A8CH86B6C93HW7QBA",
        "mmsi": 990645671,
        "imo": 9471630,
        "puerto": "BARCELONA",
        "estado": 0,                # AIS: under way using engine
        "lat_buque": 42.629653,
        "lon_buque": 7.129181,
        "lat_port": 41.338,
        "lon_port": 2.1675,
        "direccion": 248.9,
        "velocidad_buque": 11.7,
        "eslora": 254,
        "manga": 27,
        "calado_de_diseno": 17.8,
        "tipo_buque": 79,
        "ETA_dynamic": 20.049831154821184,
        "ETA_static": "2026-08-17 13:03:00",
        "ingest_timestamp": "2026-08-16T17:20:18.122700+00:00",
    }


@pytest.fixture
def paquete_2() -> dict:
    """Foto del puerto. El propio buque objetivo aparece en 'en_camino'."""
    return {
        "puerto": "BARCELONA",
        "estados": {
            "num_buques_atracados": [
                {"mmsi": 990985720, "imo": 9811907, "eslora": 247,
                 "latitud": 41.312166, "longitud": 2.209423, "tipo_buque": 70},
            ],
            "num_buques_fondeados": [
                {"mmsi": 990186040, "imo": 9588615, "eslora": 229,
                 "latitud": 41.312166, "longitud": 2.209423, "tipo_buque": 70},
            ],
            "num_buques_en_camino": [
                {"mmsi": 990645671, "imo": 9471630, "eslora": 254,
                 "latitud": 42.638543, "longitud": 7.160132, "tipo_buque": 79},
                {"mmsi": 990110810, "imo": 9913676, "eslora": 270,
                 "latitud": 36.878105, "longitud": -1.639414, "tipo_buque": 70},
            ],
        },
    }


@pytest.fixture
def alerta_valida(paquete_1, paquete_2) -> dict:
    """El cuerpo completo tal y como llega al webhook."""
    return {"paquete_1": paquete_1, "paquete_2": paquete_2}


@pytest.fixture
def estado_oraculo(paquete_1, paquete_2) -> dict:
    """
    Estado del grafo tal y como queda JUSTO ANTES de publicar, con todos
    los nodos ya ejecutados.

    Se construye a mano en vez de invocar el grafo a propósito: así el
    test del contrato de salida comprueba SOLO la traducción a
    `oracle_recommendation_v1`, sin depender de la ruta, la meteo ni el
    LLM. Un fallo aquí señala el contrato, no el cálculo.
    """
    momento = datetime(2026, 8, 16, 17, 20, 18, tzinfo=timezone.utc)

    cii_inicial = CIIResult(
        cii=2.0471, metodo="eexi", v_diseno_kn=14.81, v_actual_kn=11.7,
        distancia_nm=325.86, dwt_estimado=48000.0, dwt_real_t=None,
        co2_estimado_kg=None,
        detalles={"tipo_normalizado": "ro_ro", "vessel_name": "MINOAN PIONEER"},
    )
    cii_jit = CIIResult(
        cii=0.5241, metodo="eexi", v_diseno_kn=14.81, v_actual_kn=5.92,
        distancia_nm=325.86, dwt_estimado=48000.0, dwt_real_t=None,
        co2_estimado_kg=None,
        detalles={"tipo_normalizado": "ro_ro", "vessel_name": "MINOAN PIONEER"},
    )
    velocidad_jit = VelocidadJIT(
        v_motor_kn=5.92, tiempo_transito_estimado_h=59.64, tiempo_objetivo_h=75.3,
        perdida_media_pct=7.4, iteraciones=18, convergio=True,
        nota=None, excede_v_diseno=False,
    )

    informe = {
        "correlation_id": paquete_1["correlation_id"],
        "buque": {"mmsi": paquete_1["mmsi"], "imo": paquete_1["imo"],
                  "puerto_destino": "BARCELONA"},
        "ruta": {"distancia_nm": 325.9},
        "cola_puerto": {"tiempo_espera_estimado_h": 75.3, "posicion_cola": 3,
                        "segmento_atraque": "large"},
        "velocidad": {"actual_kn": 11.7, "diseno_kn": 14.81,
                      "jit_recomendada_kn": 5.92, "tiempo_transito_estimado_h": 59.64,
                      "perdida_kwon_media_pct": 7.4, "convergio": True,
                      "excede_v_diseno": False, "nota": None},
        "cii": {"inicial": 2.0471, "jit": 0.5241, "metodo": "eexi", "ahorro_pct": 74.4},
        "eta": {"inicial_sin_cola": "2026-08-17T13:23:17+00:00",
                "recomendada_jit": "2026-08-19T04:58:42+00:00", "diferencia_h": 39.6},
    }

    return {
        "paquete_1": paquete_1,
        "paquete_2": paquete_2,
        "vessel_lat": paquete_1["lat_buque"],
        "vessel_lon": paquete_1["lon_buque"],
        "port": Port(locode="BARCELONA", name="BARCELONA", lat=41.338, lon=2.1675),
        "speed_knot": 11.7,
        "event_timestamp": momento,
        "departure_time": momento,
        "route": Route(distance_nm=325.86, duration_hours=27.85,
                       waypoints=[(7.129181, 42.629653), (2.1675, 41.338)]),
        "distance_nm": 325.86,
        "weather": [
            {"lat": 42.629653, "lon": 7.129181, "eta": momento,
             "wave_height": 0.58, "wave_direction": 248.0, "wave_period": 3.0},
            {"lat": 41.338, "lon": 2.1675, "eta": momento,
             "wave_height": 0.12, "wave_direction": 148.0, "wave_period": 3.9},
        ],
        "wind": [
            {"wind_speed_kn": 13.2, "wind_direction": 240.0, "wind_gusts_kn": 15.6},
            {"wind_speed_kn": 1.2, "wind_direction": 108.0, "wind_gusts_kn": 3.1},
        ],
        "cii_inicial": cii_inicial,
        "cii_jit": cii_jit,
        "db_record": None,
        "estimacion_jit": informe["cola_puerto"],
        "estimaciones_puerto": [
            {"mmsi": "990186040", "tiempo_espera_estimado_h": 31.8},
            {"mmsi": "990645671", "tiempo_espera_estimado_h": 75.3},
            {"mmsi": "990110810", "tiempo_espera_estimado_h": 102.1},
        ],
        "tiempo_espera_h": 75.3,
        "velocidad_jit": velocidad_jit,
        "informe": informe,
        "historial": [],
        "resumen": {"texto": "Atraque libre en 75.3 h. Velocidad recomendada: 5.92 kn.",
                    "prompt": "...", "alerta_cii": False, "llm_degradado": False},
    }
