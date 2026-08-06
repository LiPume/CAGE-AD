"""Pure semantic transformations shared by runtime injection and CPU tests."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum


class ScenarioKind(str, Enum):
    LEAD_DECELERATION = "lead_vehicle_deceleration"
    CUT_IN_CROSSING = "cut_in_or_crossing_actor"


class FaultMechanism(str, Enum):
    FORECAST_STALE = "forecast_stale_or_delayed"
    FORECAST_HEADING_BIAS = "forecast_heading_or_maneuver_bias"
    PLAN_CONSTRAINT_OMITTED = "planning_constraint_omitted"
    PLAN_UNSAFE_SPEED_BIAS = "planning_unsafe_cost_or_speed_bias"
    CONTROL_TRANSPORT_DELAY = "control_command_transport_delay"
    CONTROL_GAIN_BIAS = "control_gain_saturation_tracking_bias"


DOMAIN_BY_MECHANISM = {
    FaultMechanism.FORECAST_STALE: "interaction_forecasting",
    FaultMechanism.FORECAST_HEADING_BIAS: "interaction_forecasting",
    FaultMechanism.PLAN_CONSTRAINT_OMITTED: "motion_planning",
    FaultMechanism.PLAN_UNSAFE_SPEED_BIAS: "motion_planning",
    FaultMechanism.CONTROL_TRANSPORT_DELAY: "tracking_execution",
    FaultMechanism.CONTROL_GAIN_BIAS: "tracking_execution",
}


@dataclass(frozen=True)
class MotionPoint:
    t: float
    x: float
    y: float
    heading: float
    speed: float
    acceleration: float = 0.0


@dataclass(frozen=True)
class ControlTarget:
    t: float
    throttle_pct: float
    brake_pct: float
    steering_pct: float


def forecast_fault(points: list[MotionPoint], mechanism: FaultMechanism) -> list[MotionPoint]:
    if mechanism == FaultMechanism.FORECAST_STALE:
        if not points:
            return []
        anchor = points[0]
        return [replace(point, x=anchor.x, y=anchor.y, speed=0.0) for point in points]
    if mechanism == FaultMechanism.FORECAST_HEADING_BIAS:
        bias = math.radians(75)
        if not points:
            return []
        origin = points[0]
        transformed = []
        for point in points:
            distance = max(0.0, point.t - origin.t) * point.speed
            transformed.append(
                replace(
                    point,
                    x=origin.x + distance * math.cos(origin.heading + bias),
                    y=origin.y + distance * math.sin(origin.heading + bias),
                    heading=origin.heading + bias,
                )
            )
        return transformed
    raise ValueError("mechanism is not a forecasting fault")


def constant_velocity_probe(points: list[MotionPoint]) -> list[MotionPoint]:
    if not points:
        return []
    anchor = points[0]
    return [
        replace(
            point,
            x=anchor.x + (point.t - anchor.t) * anchor.speed * math.cos(anchor.heading),
            y=anchor.y + (point.t - anchor.t) * anchor.speed * math.sin(anchor.heading),
            heading=anchor.heading,
            speed=anchor.speed,
            acceleration=0.0,
        )
        for point in points
    ]


def planning_fault(points: list[MotionPoint], mechanism: FaultMechanism) -> list[MotionPoint]:
    if mechanism == FaultMechanism.PLAN_CONSTRAINT_OMITTED:
        return [replace(point, speed=max(point.speed, 10.0), acceleration=max(point.acceleration, 1.5)) for point in points]
    if mechanism == FaultMechanism.PLAN_UNSAFE_SPEED_BIAS:
        return [
            replace(point, speed=min(18.0, point.speed * 3.0 + 3.0), acceleration=point.acceleration + 1.5)
            for point in points
        ]
    raise ValueError("mechanism is not a planning fault")


def safety_envelope_probe(points: list[MotionPoint]) -> list[MotionPoint]:
    """Non-GT probe: monotonically decelerate the existing path to zero."""
    if not points:
        return []
    start_t = points[0].t
    start_speed = points[0].speed
    horizon = 2.5
    result = []
    for point in points:
        elapsed = max(0.0, point.t - start_t)
        speed = max(0.0, start_speed * (1.0 - elapsed / horizon))
        result.append(replace(point, speed=speed, acceleration=-start_speed / horizon))
    return result


def control_fault(target: ControlTarget, mechanism: FaultMechanism) -> ControlTarget:
    if mechanism == FaultMechanism.CONTROL_GAIN_BIAS:
        return replace(
            target,
            throttle_pct=min(100.0, target.throttle_pct * 2.5 + 20.0),
            brake_pct=0.0,
            steering_pct=max(-35.0, min(35.0, target.steering_pct * 0.6)),
        )
    raise ValueError("transport delay is implemented by the runtime queue")


def bounded_brake_probe(t: float) -> ControlTarget:
    return ControlTarget(t=t, throttle_pct=0.0, brake_pct=60.0, steering_pct=0.0)
