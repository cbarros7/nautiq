import json
import math

import pytest
from hypothesis import given, settings, strategies as st

from streaming.tests.conftest import (
    assemble_alert_payload,
    st_mmsi,
    st_latitude,
    st_longitude,
    st_speed,
)

st_imo = st.integers(min_value=1000000, max_value=9999999)
st_correlation_id = st.text(min_size=1, max_size=64, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-")
st_puerto = st.sampled_from(["VALENCIA", "ALGECIRAS", "BARCELONA", "BILBAO"])
st_estado = st.integers(min_value=0, max_value=15)
st_tipo_buque = st.integers(min_value=70, max_value=79)
st_eslora = st.floats(min_value=10.0, max_value=400.0, allow_nan=False, allow_infinity=False)
st_manga = st.floats(min_value=3.0, max_value=65.0, allow_nan=False, allow_infinity=False)
st_calado = st.floats(min_value=1.0, max_value=25.0, allow_nan=False, allow_infinity=False)
st_eta_dynamic = st.floats(min_value=0.1, max_value=200.0, allow_nan=False, allow_infinity=False)
st_eta_static = st.text(min_size=4, max_size=16, alphabet="0123456789- :")
st_direccion = st.floats(min_value=0.0, max_value=360.0, allow_nan=False, allow_infinity=False)

st_buque_inventario = st.fixed_dictionaries(
    {
        "mmsi": st_mmsi,
        "eslora": st_eslora,
        "tipo_buque": st_tipo_buque,
    }
)
st_lista_buques = st.lists(st_buque_inventario, min_size=0, max_size=10)


def _build_inputs():
    return st.fixed_dictionaries(
        {
            "mmsi": st_mmsi,
            "correlation_id": st_correlation_id,
            "imo": st_imo,
            "puerto": st_puerto,
            "estado": st_estado,
            "lon_buque": st_longitude,
            "lat_buque": st_latitude,
            "lon_port": st_longitude,
            "lat_port": st_latitude,
            "direccion": st_direccion,
            "velocidad_buque": st_speed,
            "eslora": st_eslora,
            "manga": st_manga,
            "calado_de_diseno": st_calado,
            "tipo_buque": st_tipo_buque,
            "eta_dynamic": st_eta_dynamic,
            "eta_static": st_eta_static,
            "num_buques_atracados": st_lista_buques,
            "num_buques_fondeados": st_lista_buques,
            "num_buques_en_camino": st_lista_buques,
        }
    )


@given(_build_inputs())
@settings(max_examples=100, deadline=None)
def test_alert_payload_json_syntactic_validity(inputs):
    payload = assemble_alert_payload(**inputs)
    serialized = json.dumps(payload)
    deserialized = json.loads(serialized)
    assert isinstance(deserialized, dict)


@given(_build_inputs())
@settings(max_examples=100, deadline=None)
def test_alert_payload_root_keys_contract(inputs):
    payload = assemble_alert_payload(**inputs)
    assert set(payload.keys()) == {"paquete_1", "paquete_2"}


@given(_build_inputs())
@settings(max_examples=100, deadline=None)
def test_alert_payload_paquete_1_required_keys(inputs):
    payload = assemble_alert_payload(**inputs)
    expected = {
        "mmsi",
        "correlation_id",
        "imo",
        "puerto",
        "estado",
        "lon_buque",
        "lat_buque",
        "lon_port",
        "lat_port",
        "direccion",
        "velocidad_buque",
        "eslora",
        "manga",
        "calado_de_diseno",
        "tipo_buque",
        "ETA_dynamic",
        "ETA",
        "ETA_static",
    }
    assert set(payload["paquete_1"].keys()) == expected


@given(_build_inputs())
@settings(max_examples=100, deadline=None)
def test_alert_payload_paquete_2_inventory_arrays(inputs):
    payload = assemble_alert_payload(**inputs)
    p2 = payload["paquete_2"]
    assert "puerto" in p2
    assert "estados" in p2
    estados = p2["estados"]
    assert isinstance(estados["num_buques_atracados"], list)
    assert isinstance(estados["num_buques_fondeados"], list)
    assert isinstance(estados["num_buques_en_camino"], list)


@given(_build_inputs())
@settings(max_examples=100, deadline=None)
def test_alert_payload_numeric_types_consistency(inputs):
    payload = assemble_alert_payload(**inputs)
    p1 = payload["paquete_1"]

    assert isinstance(p1["mmsi"], int)
    assert isinstance(p1["imo"], int)
    assert isinstance(p1["estado"], int)
    assert isinstance(p1["tipo_buque"], int)

    for key in ("lon_buque", "lat_buque", "velocidad_buque", "ETA_dynamic"):
        value = p1[key]
        assert isinstance(value, float)
        assert math.isfinite(value)
