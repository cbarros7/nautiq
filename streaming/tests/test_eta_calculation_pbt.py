import math

import pytest
from hypothesis import given, settings, strategies as st

from streaming.tests.conftest import (
    calculate_eta_dynamic_hours,
    MIN_ETA_SPEED_KNOTS,
)


@given(
    dist=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    speed=st.one_of(
        st.just(0.0),
        st.floats(min_value=-1e6, max_value=0.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.0, max_value=MIN_ETA_SPEED_KNOTS, allow_nan=False, allow_infinity=False),
    ),
)
@settings(max_examples=200)
def test_eta_dynamic_speed_filter_invariant(dist, speed):
    assert speed <= MIN_ETA_SPEED_KNOTS
    result = calculate_eta_dynamic_hours(dist, speed)
    assert result is None


@given(
    dist=st.floats(min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False),
    v1=st.floats(min_value=MIN_ETA_SPEED_KNOTS + 1e-3, max_value=1e3, allow_nan=False, allow_infinity=False),
    v2=st.floats(min_value=MIN_ETA_SPEED_KNOTS + 1e-3, max_value=1e3, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_eta_dynamic_monotonicity_speed(dist, v1, v2):
    if v1 >= v2:
        v1, v2 = v2, v1
    if v1 == v2:
        return
    eta1 = calculate_eta_dynamic_hours(dist, v1)
    eta2 = calculate_eta_dynamic_hours(dist, v2)
    assert eta1 is not None and eta2 is not None
    assert eta2 < eta1


@given(
    d1=st.floats(min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False),
    d2=st.floats(min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False),
    speed=st.floats(min_value=MIN_ETA_SPEED_KNOTS + 1e-3, max_value=1e3, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_eta_dynamic_monotonicity_distance(d1, d2, speed):
    if d1 >= d2:
        d1, d2 = d2, d1
    if d1 == d2:
        return
    eta1 = calculate_eta_dynamic_hours(d1, speed)
    eta2 = calculate_eta_dynamic_hours(d2, speed)
    assert eta1 is not None and eta2 is not None
    assert eta1 < eta2


@given(
    dist=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    speed=st.floats(min_value=MIN_ETA_SPEED_KNOTS + 1e-3, max_value=1e3, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_eta_dynamic_non_negative_finite(dist, speed):
    result = calculate_eta_dynamic_hours(dist, speed)
    assert result is not None
    assert isinstance(result, float)
    assert math.isfinite(result)
    assert result >= 0.0
