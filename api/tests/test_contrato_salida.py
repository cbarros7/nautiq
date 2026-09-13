"""
Frontera de SALIDA: la forma del evento `oracle_recommendation_v1`.

Este contrato es el acuerdo con el equipo de frontal y con la capa
analítica: el mismo payload va al `jsonb` de Supabase y al blob de ADLS.
Romperlo no da error en ninguna de las dos escrituras —jsonb acepta
cualquier JSON— así que un campo renombrado o desaparecido solo se
detecta cuando el frontal deja de pintar algo. Estos tests son la red
que falta.

Se prueba `construir_evento_contrato` directamente sobre un estado ya
calculado (ver conftest), no invocando el grafo: así un fallo señala la
traducción al contrato y no el cálculo.
"""

from __future__ import annotations

import json

import pytest

from app.agents.math_oracle import construir_evento_contrato


@pytest.fixture
def evento(estado_oraculo) -> dict:
    return construir_evento_contrato(estado_oraculo, "01M0EVENTO", "01M0SESION")


# ── Estructura ────────────────────────────────────────────────────────

def test_bloques_de_primer_nivel(evento):
    esperados = {
        "event_id", "session_id", "emitted_at", "schema_version",
        "vessel", "port", "context_vessels", "route", "route_weather",
        "queue", "recommendation",
    }
    assert esperados <= set(evento)


def test_identificadores_y_version(evento):
    assert evento["event_id"] == "01M0EVENTO"
    assert evento["session_id"] == "01M0SESION"
    assert evento["schema_version"] == 1


def test_el_evento_es_serializable_a_json(evento):
    """
    Va a un `jsonb` y a un blob: cualquier objeto no serializable
    (datetime, dataclass) reventaría en la escritura, no aquí.
    """
    texto = json.dumps(evento, ensure_ascii=False)
    assert json.loads(texto)["event_id"] == "01M0EVENTO"


# ── Buque y puerto ────────────────────────────────────────────────────

def test_datos_del_buque(evento, paquete_1):
    v = evento["vessel"]
    assert v["mmsi"] == paquete_1["mmsi"]
    assert v["imo"] == paquete_1["imo"]
    assert v["name"] == "MINOAN PIONEER"      # resuelto contra thetis_mrv
    assert v["speed_kn"] == 11.7
    assert v["eta_ais_raw"] == paquete_1["ETA_static"]
    assert v["is_container"] is False          # tipo_normalizado = ro_ro


def test_conteos_del_puerto(evento):
    p = evento["port"]
    assert (p["berthed_count"], p["anchored_count"], p["inbound_count"]) == (1, 1, 2)
    assert p["locode"] is None    # sin tabla nombre->locode conectada


# ── Cola: la justificación de la recomendación ────────────────────────

def test_queue_expone_la_justificacion(evento):
    """
    Sin estos tres campos el frontal no puede explicar POR QUÉ frenar.
    """
    q = evento["queue"]
    assert q["estimated_wait_hours"] == 75.3
    assert q["queue_position"] == 3
    assert q["berth_segment"] == "large"


def test_context_vessels_marca_el_objetivo(evento):
    """
    `es_objetivo` se resuelve comparando mmsi directamente, para que
    funcione también en la lista de atracados.
    """
    todos = (evento["context_vessels"]["berthed"]
             + evento["context_vessels"]["anchored"]
             + evento["context_vessels"]["inbound"])
    objetivos = [v for v in todos if v["es_objetivo"]]

    assert len(objetivos) == 1
    assert str(objetivos[0]["mmsi"]) == "990645671"


def test_context_vessels_usa_estimated_wait_hours(evento):
    """
    El nombre del campo es deliberado: es un valor MODELADO por
    jit_calculus, no una espera observada. Llamarlo `wait_hours`
    invitaría a leerlo como dato medido.
    """
    fondeado = evento["context_vessels"]["anchored"][0]
    assert "estimated_wait_hours" in fondeado
    assert fondeado["estimated_wait_hours"] == 31.8


# ── Recomendación ─────────────────────────────────────────────────────

def test_velocidades_y_delta(evento):
    r = evento["recommendation"]
    assert r["recommended_speed_kn"] == 5.92
    assert r["design_speed_kn"] == 14.81
    assert r["estimated_transit_hours"] == 59.64
    assert r["speed_delta_kn"] == pytest.approx(5.92 - 11.7, abs=0.01)


def test_senales_nativas_del_calculo(evento):
    """
    Se exponen `convergio`, `excede_v_diseno` y `nota` en vez de un
    `status`/`confidence` inventados: son las señales que el cálculo
    produce de verdad.
    """
    r = evento["recommendation"]
    assert r["convergio"] is True
    assert r["excede_v_diseno"] is False
    assert "nota" in r
    assert r["weather_speed_loss_pct"] == 7.4


def test_cii_y_ahorro(evento):
    cii = evento["recommendation"]["cii"]
    assert (cii["inicial"], cii["jit"], cii["metodo"]) == (2.0471, 0.5241, "eexi")
    assert cii["ahorro_pct"] == 74.4


def test_fuel_saved_es_null_sin_dwt_real(evento):
    """
    Solo se rellena con DWT REAL de thetis_mrv. Con el DWT estimado
    geométricamente la cifra tendría la misma incertidumbre que el
    método de respaldo, y una cifra de toneladas invita a creérsela.
    """
    assert evento["recommendation"]["fuel_saved_t"] is None


def test_fuel_saved_null_aunque_haya_co2_si_el_dwt_es_estimado(estado_oraculo):
    """
    Aísla la condición del DWT REAL.

    El test anterior no bastaba: con `co2_estimado_kg=None` la guarda
    cortaba por ahí, así que sustituir `dwt_real_t` por `dwt_estimado`
    en el código seguía dando null y el test pasaba igual. Aquí se
    aporta CO₂ en ambos escenarios y solo DWT estimado, de modo que lo
    único que puede dejar el campo a null es la comprobación que
    importa.
    """
    estado_oraculo["cii_inicial"].dwt_real_t = None
    estado_oraculo["cii_inicial"].dwt_estimado = 48000.0
    estado_oraculo["cii_inicial"].co2_estimado_kg = 900_000.0
    estado_oraculo["cii_jit"].co2_estimado_kg = 300_000.0

    evento = construir_evento_contrato(estado_oraculo, "01M0X", "01M0Y")
    assert evento["recommendation"]["fuel_saved_t"] is None


def test_fuel_saved_se_calcula_con_dwt_real(estado_oraculo):
    """Con DWT real de thetis_mrv sí debe salir un número."""
    estado_oraculo["cii_inicial"].dwt_real_t = 50000.0
    estado_oraculo["cii_inicial"].co2_estimado_kg = 900_000.0
    estado_oraculo["cii_jit"].co2_estimado_kg = 300_000.0

    evento = construir_evento_contrato(estado_oraculo, "01M0X", "01M0Y")
    assert evento["recommendation"]["fuel_saved_t"] > 0


@pytest.mark.parametrize("degradado", [True, False])
def test_rationale_degradado_refleja_el_resumen(estado_oraculo, degradado):
    """
    Avisa de que el texto viene de plantilla porque el LLM falló. El
    cálculo sigue siendo válido; lo que cambia es la redacción, y el
    consumidor debe poder distinguirlo.
    """
    estado_oraculo["resumen"]["llm_degradado"] = degradado
    evento = construir_evento_contrato(estado_oraculo, "01M0X", "01M0Y")

    assert evento["recommendation"]["rationale_degradado"] is degradado
    assert evento["recommendation"]["rationale"]  # el texto nunca va vacío


# ── Ruta y meteo ──────────────────────────────────────────────────────

def test_route_weather_empareja_olas_y_viento(evento):
    """
    Son dos APIs distintas de Open-Meteo; el contrato las entrega ya
    combinadas por waypoint.
    """
    assert len(evento["route_weather"]) == 2
    primero = evento["route_weather"][0]
    for campo in ("lat", "lon", "eta", "wave_height", "wind_speed_kn", "wind_gusts_kn"):
        assert campo in primero
    assert isinstance(primero["eta"], str)  # ISO, no datetime


def test_ruta_lleva_distancia_y_waypoints(evento):
    assert evento["route"]["distance_nm"] == 325.86
    assert len(evento["route"]["waypoints"]) == 2
