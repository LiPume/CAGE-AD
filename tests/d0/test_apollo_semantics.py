from __future__ import annotations

import math

import pytest

from cage_ad.adapters.apollo_d0.semantics import (
    ControlTarget,
    FaultMechanism,
    MotionPoint,
    bounded_brake_probe,
    constant_velocity_probe,
    control_fault,
    forecast_fault,
    planning_fault,
    safety_envelope_probe,
)


@pytest.fixture
def motion() -> list[MotionPoint]:
    return [MotionPoint(t=float(i), x=float(i * 2), y=0, heading=0, speed=2) for i in range(5)]


def test_two_forecasting_faults_are_distinct_and_deterministic(motion) -> None:
    stale = forecast_fault(motion, FaultMechanism.FORECAST_STALE)
    biased = forecast_fault(motion, FaultMechanism.FORECAST_HEADING_BIAS)
    assert len({point.x for point in stale}) == 1
    assert biased[-1].y > 0
    assert biased == forecast_fault(motion, FaultMechanism.FORECAST_HEADING_BIAS)


def test_constant_velocity_probe_uses_only_first_observed_state(motion) -> None:
    perturbed = [motion[0], *[MotionPoint(**{**point.__dict__, "x": 999}) for point in motion[1:]]]
    assert constant_velocity_probe(motion) == constant_velocity_probe(perturbed)


def test_two_planning_faults_raise_speed_differently(motion) -> None:
    omitted = planning_fault(motion, FaultMechanism.PLAN_CONSTRAINT_OMITTED)
    biased = planning_fault(motion, FaultMechanism.PLAN_UNSAFE_SPEED_BIAS)
    assert all(point.speed >= 6 for point in omitted)
    assert [point.speed for point in omitted] != [point.speed for point in biased]


def test_safety_envelope_is_nonincreasing_and_stops(motion) -> None:
    probe = safety_envelope_probe(motion)
    assert all(a.speed >= b.speed for a, b in zip(probe, probe[1:]))
    assert probe[-1].speed == 0


def test_tracking_gain_fault_and_bounded_probe() -> None:
    target = ControlTarget(t=1, throttle_pct=20, brake_pct=40, steering_pct=80)
    faulty = control_fault(target, FaultMechanism.CONTROL_GAIN_BIAS)
    assert faulty.throttle_pct > target.throttle_pct
    assert faulty.brake_pct < target.brake_pct
    assert abs(faulty.steering_pct) <= 35
    probe = bounded_brake_probe(1)
    assert probe.throttle_pct == 0 and math.isclose(probe.brake_pct, 60)
