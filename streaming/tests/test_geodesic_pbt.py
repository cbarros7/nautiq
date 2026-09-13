import math
import pytest
from hypothesis import given, settings, HealthCheck, assume

from streaming.tests.conftest import (
    st_latitude,
    st_longitude,
    spherical_law_of_cosines_nm,
)

EARTH_RADIUS_NM = 3440.065
MAX_DISTANCE_NM = math.pi * EARTH_RADIUS_NM


@given(st_latitude, st_longitude, st_latitude, st_longitude)
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_geodesic_distance_non_negative(lat1, lon1, lat2, lon2):
    dist = spherical_law_of_cosines_nm(lat1, lon1, lat2, lon2)
    assert not math.isnan(dist)
    assert dist >= 0.0


@given(st_latitude, st_longitude)
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_geodesic_identity_of_indiscernibles(lat, lon):
    dist = spherical_law_of_cosines_nm(lat, lon, lat, lon)
    assert not math.isnan(dist)
    assert dist < 1e-6


@given(st_latitude, st_longitude, st_latitude, st_longitude)
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_geodesic_symmetry(lat1, lon1, lat2, lon2):
    d12 = spherical_law_of_cosines_nm(lat1, lon1, lat2, lon2)
    d21 = spherical_law_of_cosines_nm(lat2, lon2, lat1, lon1)
    assert math.isclose(d12, d21, abs_tol=1e-5)


@given(
    st_latitude,
    st_longitude,
    st_latitude,
    st_longitude,
    st_latitude,
    st_longitude,
)
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_geodesic_triangle_inequality(lat1, lon1, lat2, lon2, lat3, lon3):
    d13 = spherical_law_of_cosines_nm(lat1, lon1, lat3, lon3)
    d12 = spherical_law_of_cosines_nm(lat1, lon1, lat2, lon2)
    d23 = spherical_law_of_cosines_nm(lat2, lon2, lat3, lon3)
    assert d13 <= d12 + d23 + 1e-4


@given(st_latitude, st_longitude)
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_geodesic_clamping_prevents_nan_on_floating_point_drift(lat, lon):
    # Puntos casi idénticos: cos_c puede exceder 1.0 por drift de punto flotante.
    eps = 1e-12
    dist_same = spherical_law_of_cosines_nm(lat, lon, lat, lon)
    assert not math.isnan(dist_same)

    # Clamping previene que pase de 90 o -90 al sumar eps
    test_lat = min(90.0, lat + eps)
    test_lon = min(180.0, lon + eps)
    dist_near = spherical_law_of_cosines_nm(lat, lon, test_lat, test_lon)
    assert not math.isnan(dist_near)

    # Extremos: polos y antípodas.
    dist_pole = spherical_law_of_cosines_nm(90.0, 0.0, 90.0, 180.0)
    assert not math.isnan(dist_pole)

    dist_anti = spherical_law_of_cosines_nm(0.0, 0.0, 0.0, 180.0)
    assert not math.isnan(dist_anti)

    # No debe lanzar ValueError (math domain error).
    try:
        spherical_law_of_cosines_nm(lat, lon, lat, lon)
        spherical_law_of_cosines_nm(90.0, 0.0, -90.0, 0.0)
    except ValueError as exc:
        pytest.fail(f"Math domain error inesperado: {exc}")


@given(st_latitude, st_longitude, st_latitude, st_longitude)
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_geodesic_maximum_bound(lat1, lon1, lat2, lon2):
    dist = spherical_law_of_cosines_nm(lat1, lon1, lat2, lon2)
    assert not math.isnan(dist)
    assert dist <= MAX_DISTANCE_NM + 1e-6
