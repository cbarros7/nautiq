import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from streaming.tests.conftest import (
    classify_port_vessel_status,
    spherical_law_of_cosines_nm,
    st_latitude,
    st_longitude,
    st_speed,
    st_nav_status,
)

VALID_STATUSES = {"ATRACADO", "FONDEADO", "EN_CAMINO"}


@st.composite
def kinematic_states(draw):
    lat = draw(st_latitude)
    lon = draw(st_longitude)
    speed = draw(st_speed)
    nav_status = draw(st_nav_status)
    port_lat = draw(st_latitude)
    port_lon = draw(st_longitude)
    port_radius_nm = draw(
        st.floats(min_value=0.5, max_value=50.0, allow_nan=False, allow_infinity=False)
    )
    max_eta_hours = draw(
        st.floats(min_value=1.0, max_value=200.0, allow_nan=False, allow_infinity=False)
    )
    return {
        "lat": lat,
        "lon": lon,
        "speed": speed,
        "nav_status": nav_status,
        "port_lat": port_lat,
        "port_lon": port_lon,
        "port_radius_nm": port_radius_nm,
        "max_eta_hours": max_eta_hours,
    }


def _call(state):
    return classify_port_vessel_status(
        lat=state["lat"],
        lon=state["lon"],
        speed=state["speed"],
        nav_status=state["nav_status"],
        port_lat=state["port_lat"],
        port_lon=state["port_lon"],
        port_radius_nm=state["port_radius_nm"],
        max_eta_hours=state["max_eta_hours"],
    )


def _distance(state):
    return spherical_law_of_cosines_nm(
        state["lat"], state["lon"], state["port_lat"], state["port_lon"]
    )


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(state=kinematic_states())
def test_port_inventory_operational_disjunction(state):
    result = _call(state)
    assert result is None or result in VALID_STATUSES
    if result is not None:
        assert isinstance(result, str)
        assert result in VALID_STATUSES
        assert sum(1 for s in VALID_STATUSES if s == result) == 1


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(state=kinematic_states())
def test_port_inventory_geofence_constraint(state):
    result = _call(state)
    dist = _distance(state)
    if result in ("ATRACADO", "FONDEADO"):
        assert dist <= state["port_radius_nm"] + 1e-6
    elif result == "EN_CAMINO":
        assert dist > state["port_radius_nm"]
        assert state["speed"] > 0.5
        eta = dist / state["speed"]
        assert eta <= state["max_eta_hours"]


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(state=kinematic_states())
def test_port_inventory_nav_status_contract(state):
    result = _call(state)
    if result == "ATRACADO":
        assert state["nav_status"] == 5
    elif result == "FONDEADO":
        assert state["nav_status"] == 1


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(state=kinematic_states())
def test_port_inventory_outside_horizon_discarded(state):
    dist = _distance(state)
    if dist > state["port_radius_nm"] and state["speed"] > 0.5:
        eta = dist / state["speed"]
        if eta > state["max_eta_hours"]:
            result = _call(state)
            assert result is None
