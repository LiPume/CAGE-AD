"""Deterministic, oracle-free semantic probes specified by protocol v1."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

from .loader import ProtocolBundle, ProtocolValidationError
from .transformers import ActuatorCommand, TrajectoryPoint


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _angle_delta(right: float, left: float) -> float:
    return math.atan2(math.sin(right - left), math.cos(right - left))


@dataclass(frozen=True)
class ActorHistorySample:
    timestamp: float
    x: float
    y: float
    speed: float
    heading: float


@dataclass(frozen=True)
class ForecastProbeResult:
    selected_model: str
    rolling_ade: dict[str, float]
    trajectory: tuple[TrajectoryPoint, ...]
    history_end_timestamp: float


@dataclass(frozen=True)
class ForecastProbeConfig:
    history_window_s: float
    minimum_history_samples: int
    horizon_s: float
    step_s: float
    speed_bounds: tuple[float, float]
    acceleration_bounds: tuple[float, float]
    yaw_rate_bounds: tuple[float, float]


@dataclass(frozen=True)
class PlanningProbeConfig:
    horizon_s: float
    step_s: float
    safety_buffer_m: float
    maximum_deceleration_mps2: float
    maximum_jerk_mps3: float
    minimum_speed_mps: float


@dataclass(frozen=True)
class ControlProbeConfig:
    wheelbase_m: float
    lookahead_floor_m: float
    lookahead_speed_factor: float
    maximum_steering_angle_deg: float
    kp: float
    ki: float
    kd: float
    integral_bounds: tuple[float, float]
    output_bounds: tuple[float, float]


@dataclass(frozen=True)
class ProbeSuiteConfig:
    forecasting: ForecastProbeConfig
    planning: PlanningProbeConfig
    control: ControlProbeConfig


def _parse_lookahead(value: str) -> tuple[float, float]:
    prefix = "max_"
    marker = "_or_"
    suffix = "_times_speed_mps"
    if not value.startswith(prefix) or marker not in value or not value.endswith(suffix):
        raise ProtocolValidationError("unsupported pure-pursuit lookahead expression")
    body = value[len(prefix) : -len(suffix)]
    floor_text, factor_text = body.split(marker, 1)
    return float(floor_text.replace("_", ".")), float(factor_text.replace("_", "."))


def probe_suite_config(bundle: ProtocolBundle) -> ProbeSuiteConfig:
    probes = bundle.probes["probes"]
    forecast = probes["probe_forecasting"]
    planning = probes["probe_planning"]
    control = probes["probe_control"]
    lookahead_floor, lookahead_factor = _parse_lookahead(
        control["lateral_controller"]["lookahead_m"]
    )
    return ProbeSuiteConfig(
        forecasting=ForecastProbeConfig(
            history_window_s=float(forecast["history_window_s"]),
            minimum_history_samples=int(forecast["minimum_history_samples"]),
            horizon_s=float(forecast["horizon_s"]),
            step_s=float(forecast["step_s"]),
            speed_bounds=tuple(map(float, forecast["bounds"]["speed_mps"])),
            acceleration_bounds=tuple(map(float, forecast["bounds"]["acceleration_mps2"])),
            yaw_rate_bounds=tuple(map(float, forecast["bounds"]["yaw_rate_radps"])),
        ),
        planning=PlanningProbeConfig(
            horizon_s=float(planning["horizon_s"]),
            step_s=float(planning["step_s"]),
            safety_buffer_m=float(planning["safety_buffer_m"]),
            maximum_deceleration_mps2=float(planning["limits"]["maximum_deceleration_mps2"]),
            maximum_jerk_mps3=float(planning["limits"]["maximum_jerk_mps3"]),
            minimum_speed_mps=float(planning["limits"]["minimum_speed_mps"]),
        ),
        control=ControlProbeConfig(
            wheelbase_m=float(control["lateral_controller"]["wheelbase_m"]),
            lookahead_floor_m=lookahead_floor,
            lookahead_speed_factor=lookahead_factor,
            maximum_steering_angle_deg=float(
                control["lateral_controller"]["maximum_steering_angle_deg"]
            ),
            kp=float(control["longitudinal_controller"]["kp"]),
            ki=float(control["longitudinal_controller"]["ki"]),
            kd=float(control["longitudinal_controller"]["kd"]),
            integral_bounds=tuple(map(float, control["longitudinal_controller"]["integral_clamp"])),
            output_bounds=tuple(map(float, control["longitudinal_controller"]["output_clamp"])),
        ),
    )


def _motion_estimate(history: Sequence[ActorHistorySample], config: ForecastProbeConfig) -> tuple[float, float]:
    if len(history) < 2:
        return 0.0, 0.0
    left, right = history[-2], history[-1]
    dt = right.timestamp - left.timestamp
    if dt <= 0.0:
        raise ProtocolValidationError("actor history timestamps are not strict")
    acceleration = _clamp(
        (right.speed - left.speed) / dt,
        *config.acceleration_bounds,
    )
    yaw_rate = _clamp(_angle_delta(right.heading, left.heading) / dt, *config.yaw_rate_bounds)
    return acceleration, yaw_rate


def _predict_position(
    sample: ActorHistorySample,
    dt: float,
    model: str,
    acceleration: float,
    yaw_rate: float,
    config: ForecastProbeConfig,
) -> tuple[float, float, float, float]:
    speed = _clamp(sample.speed + acceleration * dt, *config.speed_bounds)
    if model == "constant_acceleration":
        distance = max(0.0, sample.speed * dt + 0.5 * acceleration * dt * dt)
        return (
            sample.x + distance * math.cos(sample.heading),
            sample.y + distance * math.sin(sample.heading),
            sample.heading,
            speed,
        )
    if model != "constant_turn_rate_and_velocity":
        raise ProtocolValidationError(f"unsupported forecast model: {model}")
    speed = _clamp(sample.speed, *config.speed_bounds)
    heading = sample.heading + yaw_rate * dt
    if abs(yaw_rate) < 1e-9:
        return (
            sample.x + speed * dt * math.cos(sample.heading),
            sample.y + speed * dt * math.sin(sample.heading),
            sample.heading,
            speed,
        )
    return (
        sample.x + speed / yaw_rate * (math.sin(heading) - math.sin(sample.heading)),
        sample.y - speed / yaw_rate * (math.cos(heading) - math.cos(sample.heading)),
        heading,
        speed,
    )


def _rolling_ade(history: Sequence[ActorHistorySample], model: str, config: ForecastProbeConfig) -> float:
    errors: list[float] = []
    for index in range(2, len(history)):
        prefix = history[:index]
        acceleration, yaw_rate = _motion_estimate(prefix, config)
        dt = history[index].timestamp - prefix[-1].timestamp
        x, y, _, _ = _predict_position(
            prefix[-1], dt, model, acceleration, yaw_rate, config
        )
        errors.append(math.hypot(x - history[index].x, y - history[index].y))
    return sum(errors) / len(errors) if errors else math.inf


def run_forecasting_probe(
    history: Sequence[ActorHistorySample], config: ForecastProbeConfig
) -> ForecastProbeResult:
    if len(history) < config.minimum_history_samples:
        raise ProtocolValidationError("insufficient legal actor history for forecasting probe")
    if any(right.timestamp <= left.timestamp for left, right in zip(history, history[1:])):
        raise ProtocolValidationError("actor history timestamps are not strict")
    end = history[-1].timestamp
    legal = tuple(sample for sample in history if sample.timestamp >= end - config.history_window_s)
    if len(legal) < config.minimum_history_samples:
        raise ProtocolValidationError("insufficient samples inside legal history window")
    models = ("constant_acceleration", "constant_turn_rate_and_velocity")
    errors = {model: _rolling_ade(legal, model, config) for model in models}
    selected = min(models, key=lambda model: (errors[model], models.index(model)))
    acceleration, yaw_rate = _motion_estimate(legal, config)
    current = legal[-1]
    count = int(round(config.horizon_s / config.step_s))
    raw: list[tuple[float, float, float, float]] = []
    for index in range(count + 1):
        relative_time = index * config.step_s
        x, y, heading, speed = _predict_position(
            current, relative_time, selected, acceleration, yaw_rate, config
        )
        raw.append((x, y, heading, speed))
    trajectory: list[TrajectoryPoint] = []
    path_s = 0.0
    for index, (x, y, heading, speed) in enumerate(raw):
        if index:
            previous = raw[index - 1]
            path_s += math.hypot(x - previous[0], y - previous[1])
        if index + 1 < len(raw):
            next_x, next_y = raw[index + 1][0], raw[index + 1][1]
            if abs(next_x - x) + abs(next_y - y) > 1e-12:
                heading = math.atan2(next_y - y, next_x - x)
        trajectory.append(
            TrajectoryPoint(index * config.step_s, x, y, path_s, heading, speed, acceleration)
        )
    return ForecastProbeResult(selected, errors, tuple(trajectory), end)


def _interpolate_path(points: Sequence[TrajectoryPoint], target_s: float) -> tuple[float, float, float, float]:
    if not points:
        raise ProtocolValidationError("planning probe requires a legal path")
    if target_s <= points[0].s:
        point = points[0]
        return point.x, point.y, point.heading, point.curvature
    for left, right in zip(points, points[1:]):
        if target_s <= right.s:
            span = right.s - left.s
            ratio = 0.0 if span <= 1e-12 else (target_s - left.s) / span
            heading = left.heading + ratio * _angle_delta(right.heading, left.heading)
            return (
                left.x + ratio * (right.x - left.x),
                left.y + ratio * (right.y - left.y),
                heading,
                left.curvature + ratio * (right.curvature - left.curvature),
            )
    final = points[-1]
    return final.x, final.y, final.heading, final.curvature


def _earliest_conflict_s(
    path: Sequence[TrajectoryPoint], obstacle: Sequence[TrajectoryPoint], safety_buffer_m: float
) -> float | None:
    conflicts = [
        path_point.s
        for path_point in path
        if any(
            abs(path_point.relative_time - obstacle_point.relative_time) <= 0.11
            and math.hypot(path_point.x - obstacle_point.x, path_point.y - obstacle_point.y)
            <= safety_buffer_m
            for obstacle_point in obstacle
        )
    ]
    return min(conflicts) if conflicts else None


def run_planning_probe(
    nominal_path: Sequence[TrajectoryPoint],
    obstacle_forecast: Sequence[TrajectoryPoint],
    current_speed_mps: float,
    current_acceleration_mps2: float,
    config: PlanningProbeConfig,
) -> tuple[TrajectoryPoint, ...]:
    if len(nominal_path) < 2:
        raise ProtocolValidationError("planning probe requires at least two path points")
    if any(right.s < left.s for left, right in zip(nominal_path, nominal_path[1:])):
        raise ProtocolValidationError("nominal planning path s is not monotone")
    if current_speed_mps < 0.0:
        raise ProtocolValidationError("current speed is negative")
    conflict_s = _earliest_conflict_s(nominal_path, obstacle_forecast, config.safety_buffer_m)
    stop_s = None if conflict_s is None else max(nominal_path[0].s, conflict_s - config.safety_buffer_m)
    dt = config.step_s
    count = int(round(config.horizon_s / dt))
    speed = current_speed_mps
    acceleration = min(0.0, current_acceleration_mps2)
    path_s = nominal_path[0].s
    output: list[TrajectoryPoint] = []
    for index in range(count + 1):
        x, y, heading, curvature = _interpolate_path(nominal_path, path_s)
        output.append(TrajectoryPoint(index * dt, x, y, path_s, heading, speed, acceleration, curvature))
        if index == count:
            break
        remaining = math.inf if stop_s is None else max(0.0, stop_s - path_s)
        desired_acceleration = 0.0
        if stop_s is not None:
            desired_acceleration = -config.maximum_deceleration_mps2 if remaining <= 1e-9 else max(
                -config.maximum_deceleration_mps2,
                -(speed * speed) / (2.0 * remaining),
            )
        acceleration_step = config.maximum_jerk_mps3 * dt
        next_acceleration = acceleration + _clamp(
            desired_acceleration - acceleration, -acceleration_step, acceleration_step
        )
        next_acceleration = _clamp(
            next_acceleration, -config.maximum_deceleration_mps2, 0.0
        )
        if acceleration < 0.0 and speed / -acceleration <= dt:
            time_to_stop = speed / -acceleration
            next_speed = config.minimum_speed_mps
            next_s = path_s + max(0.0, speed * time_to_stop + 0.5 * acceleration * time_to_stop**2)
        else:
            next_speed = max(config.minimum_speed_mps, speed + acceleration * dt)
            next_s = path_s + max(0.0, (speed + next_speed) * 0.5 * dt)
        path_s, speed, acceleration = next_s, next_speed, next_acceleration
    return tuple(output)


@dataclass
class ControlProbe:
    config: ControlProbeConfig
    integral_error: float = 0.0
    previous_error: float | None = None

    def reset(self) -> None:
        self.integral_error = 0.0
        self.previous_error = None

    def command(
        self,
        *,
        timestamp: float,
        ego_x: float,
        ego_y: float,
        ego_heading: float,
        current_speed_mps: float,
        target_plan: Sequence[TrajectoryPoint],
        dt: float,
        gear: int,
    ) -> ActuatorCommand:
        if dt <= 0.0 or current_speed_mps < 0.0 or not target_plan:
            raise ProtocolValidationError("invalid control probe input")
        lookahead = max(
            self.config.lookahead_floor_m,
            self.config.lookahead_speed_factor * current_speed_mps,
        )
        target = min(
            target_plan,
            key=lambda point: abs(math.hypot(point.x - ego_x, point.y - ego_y) - lookahead),
        )
        alpha = _angle_delta(math.atan2(target.y - ego_y, target.x - ego_x), ego_heading)
        steering_radians = math.atan2(
            2.0 * self.config.wheelbase_m * math.sin(alpha), lookahead
        )
        steering_degrees = _clamp(
            math.degrees(steering_radians),
            -self.config.maximum_steering_angle_deg,
            self.config.maximum_steering_angle_deg,
        )
        target_speed = target.v
        error = target_speed - current_speed_mps
        self.integral_error = _clamp(
            self.integral_error + error * dt, *self.config.integral_bounds
        )
        derivative = 0.0 if self.previous_error is None else (error - self.previous_error) / dt
        self.previous_error = error
        output = _clamp(
            self.config.kp * error
            + self.config.ki * self.integral_error
            + self.config.kd * derivative,
            *self.config.output_bounds,
        )
        return ActuatorCommand(
            timestamp=timestamp,
            throttle=max(0.0, output),
            brake=max(0.0, -output),
            steering_target=steering_degrees,
            gear=gear,
        )
