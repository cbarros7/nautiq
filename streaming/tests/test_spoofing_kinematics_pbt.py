import math
import pytest
from hypothesis import given, settings, strategies as st, assume

from streaming.tests.conftest import (
    is_kinematic_spoofing,
    calculate_implied_speed_knots,
    SPOOFING_THRESHOLD_KNOTS,
)


@given(
    dist_nm=st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
    delta_hours=st.floats(min_value=1e-9, max_value=1e6, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500, deadline=None)
def test_spoofing_disjoint_and_exhaustive_partitioning(dist_nm, delta_hours):
    result = is_kinematic_spoofing(dist_nm, delta_hours)
    assert isinstance(result, bool)

    speed = calculate_implied_speed_knots(dist_nm, delta_hours)
    expected = speed > SPOOFING_THRESHOLD_KNOTS
    assert result is expected

    result_again = is_kinematic_spoofing(dist_nm, delta_hours)
    assert result_again is result


@given(
    dist_nm=st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
    delta_hours=st.one_of(
        st.none(),
        st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
    ),
)
@settings(max_examples=300, deadline=None)
def test_spoofing_first_report_tolerance(dist_nm, delta_hours):
    assert is_kinematic_spoofing(dist_nm, delta_hours) is False


@given(
    dist_nm=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    delta_hours=st.floats(min_value=1e-6, max_value=1e4, allow_nan=False, allow_infinity=False),
    k=st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500, deadline=None)
def test_spoofing_speed_scaling_invariance(dist_nm, delta_hours, k):
    scaled_dist = dist_nm * k
    scaled_delta = delta_hours * k

    assume(math.isfinite(scaled_dist))
    assume(math.isfinite(scaled_delta))
    assume(scaled_delta > 0.0)

    base = is_kinematic_spoofing(dist_nm, delta_hours)
    scaled = is_kinematic_spoofing(scaled_dist, scaled_delta)
    assert base is scaled


def test_spoofing_boundary_values():
    assert is_kinematic_spoofing(50.0, 1.0) is False
    assert is_kinematic_spoofing(50.0001, 1.0) is True
    assert is_kinematic_spoofing(49.9999, 1.0) is False
    assert is_kinematic_spoofing(50.0 + 1e-9, 1.0) is True
