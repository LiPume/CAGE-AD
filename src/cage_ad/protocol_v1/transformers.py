"""Pure protocol-v1 fault transformers and invariant checks."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, replace
import math
from typing import Any, Deque, Generic, Iterable, TypeVar

from .loader import ProtocolValidationError


@dataclass(frozen=True)
class TrajectoryPoint:
    relative_time: float
    x: float
    y: float
    s: float
    heading: float
    v: float
    a: float
    curvature: float = 0.0


@dataclass(frozen=True)
class ActuatorCommand:
    timestamp: float
    throttle: float
    brake: float
    steering_target: float
    gear: int = 0


def window_active(sim_time: float, start_s: float, end_s: float) -> bool:
    if end_s < start_s:
        raise ProtocolValidationError("fault window end precedes start")
    return start_s <= sim_time <= end_s


def _angle_delta(right: float, left: float) -> float:
    return math.atan2(math.sin(right - left), math.cos(right - left))


def _strict_points(points: list[TrajectoryPoint]) -> None:
    if len(points) < 2:
        raise ProtocolValidationError("trajectory requires at least two points")
    if any(right.relative_time <= left.relative_time for left, right in zip(points, points[1:])):
        raise ProtocolValidationError("trajectory time is not strict")
    if any(right.s < left.s for left, right in zip(points, points[1:])):
        raise ProtocolValidationError("trajectory s is not monotone")
    if any(point.v < 0 for point in points):
        raise ProtocolValidationError("trajectory speed is negative")


def kinematic_residuals(points: list[TrajectoryPoint]) -> tuple[float, float]:
    _strict_points(points)
    position_residual = speed_residual = 0.0
    for left, right in zip(points, points[1:]):
        dt = right.relative_time - left.relative_time
        displacement = math.hypot(right.x - left.x, right.y - left.y)
        expected_displacement = max(0.0, (left.v + right.v) * 0.5 * dt)
        expected_speed = max(0.0, left.v + left.a * dt)
        position_residual = max(position_residual, abs(displacement - expected_displacement))
        speed_residual = max(speed_residual, abs(right.v - expected_speed))
    return position_residual, speed_residual


def attenuate_lateral_maneuver(points: list[TrajectoryPoint], attenuation: float) -> list[TrajectoryPoint]:
    _strict_points(points)
    if not 0.0 <= attenuation <= 1.0:
        raise ProtocolValidationError("attenuation outside [0, 1]")
    origin = points[0]
    cos_h, sin_h = math.cos(origin.heading), math.sin(origin.heading)
    transformed: list[TrajectoryPoint] = []
    for point in points:
        dx, dy = point.x - origin.x, point.y - origin.y
        longitudinal = dx * cos_h + dy * sin_h
        lateral = -dx * sin_h + dy * cos_h
        lateral *= 1.0 - attenuation
        transformed.append(
            replace(
                point,
                x=origin.x + longitudinal * cos_h - lateral * sin_h,
                y=origin.y + longitudinal * sin_h + lateral * cos_h,
            )
        )
    result: list[TrajectoryPoint] = []
    for index, point in enumerate(transformed):
        other = transformed[index + 1] if index + 1 < len(transformed) else transformed[index - 1]
        dx = other.x - point.x if index + 1 < len(transformed) else point.x - other.x
        dy = other.y - point.y if index + 1 < len(transformed) else point.y - other.y
        heading = math.atan2(dy, dx) if abs(dx) + abs(dy) > 1e-12 else point.heading
        result.append(replace(point, heading=heading))
    result[0] = replace(result[0], x=origin.x, y=origin.y)
    return result


def _path_interpolate(points: list[TrajectoryPoint], target_s: float) -> tuple[float, float, float, float]:
    if target_s <= points[0].s:
        p = points[0]
        return p.x, p.y, p.heading, p.curvature
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
    left, right = points[-2], points[-1]
    distance = target_s - right.s
    return (
        right.x + distance * math.cos(right.heading),
        right.y + distance * math.sin(right.heading),
        right.heading,
        right.curvature,
    )


def attenuate_braking_suffix(points: list[TrajectoryPoint], braking_attenuation: float) -> list[TrajectoryPoint]:
    _strict_points(points)
    if not 0.0 <= braking_attenuation <= 1.0:
        raise ProtocolValidationError("braking attenuation outside [0, 1]")
    first = points[0]
    first_acceleration = first.a * (1.0 - braking_attenuation) if first.a < 0.0 else first.a
    result = [replace(first, a=first_acceleration)]
    for index, original in enumerate(points[1:], start=1):
        previous = result[-1]
        dt = original.relative_time - previous.relative_time
        source_interval_acceleration = points[index - 1].a
        interval_acceleration = (
            source_interval_acceleration * (1.0 - braking_attenuation)
            if source_interval_acceleration < 0.0
            else source_interval_acceleration
        )
        point_acceleration = (
            original.a * (1.0 - braking_attenuation) if original.a < 0.0 else original.a
        )
        speed = max(0.0, previous.v + interval_acceleration * dt)
        s = previous.s + max(0.0, (previous.v + speed) * 0.5 * dt)
        x, y, heading, curvature = _path_interpolate(points, s)
        result.append(
            TrajectoryPoint(original.relative_time, x, y, s, heading, speed, point_acceleration, curvature)
        )
    return result


def compress_trajectory_time(points: list[TrajectoryPoint], time_scale: float) -> list[TrajectoryPoint]:
    _strict_points(points)
    if not 0.0 < time_scale <= 1.0:
        raise ProtocolValidationError("time scale outside (0, 1]")
    origin = points[0].relative_time
    return [
        replace(
            point,
            relative_time=origin + time_scale * (point.relative_time - origin),
            v=point.v / time_scale,
            a=point.a / (time_scale * time_scale),
        )
        for point in points
    ]


def scale_actuator_effectiveness(command: ActuatorCommand, effectiveness: float) -> ActuatorCommand:
    if not 0.0 <= effectiveness <= 1.0:
        raise ProtocolValidationError("effectiveness outside [0, 1]")
    return replace(
        command,
        throttle=command.throttle * effectiveness,
        brake=command.brake * effectiveness,
        steering_target=command.steering_target * effectiveness,
    )


T = TypeVar("T")


@dataclass(frozen=True)
class TimedAtomicSample(Generic[T]):
    source_time: float
    arrival_index: int
    content: T


class AtomicDelayQueue(Generic[T]):
    """Stable whole-sample FIFO used by prediction and control delay faults."""

    def __init__(self, maximum_delay_s: float):
        if maximum_delay_s <= 0:
            raise ProtocolValidationError("maximum delay must be positive")
        self.maximum_delay_s = maximum_delay_s
        self._items: Deque[TimedAtomicSample[T]] = deque()
        self._arrival_index = 0

    def buffer(self, source_time: float, content: T) -> None:
        if self._items and source_time < self._items[-1].source_time:
            raise ProtocolValidationError("delay source time moved backwards")
        self._items.append(TimedAtomicSample(source_time, self._arrival_index, deepcopy(content)))
        self._arrival_index += 1

    def select_sample(self, current_time: float, delay_s: float) -> TimedAtomicSample[T] | None:
        if not 0.0 < delay_s <= self.maximum_delay_s:
            raise ProtocolValidationError("selected delay outside declared grid maximum")
        target = current_time - delay_s
        eligible = [item for item in self._items if item.source_time <= target]
        if not eligible:
            return None
        selected = max(eligible, key=lambda item: (item.source_time, item.arrival_index))
        while self._items and self._items[0].source_time < current_time - self.maximum_delay_s - 1.0:
            self._items.popleft()
        return TimedAtomicSample(selected.source_time, selected.arrival_index, deepcopy(selected.content))

    def select_content(self, current_time: float, delay_s: float) -> T | None:
        selected = self.select_sample(current_time, delay_s)
        return None if selected is None else selected.content

    def release_due_samples(self, current_time: float, delay_s: float) -> list[TimedAtomicSample[T]]:
        if not 0.0 < delay_s <= self.maximum_delay_s:
            raise ProtocolValidationError("selected delay outside declared grid maximum")
        released: list[TimedAtomicSample[T]] = []
        while self._items and self._items[0].source_time + delay_s <= current_time:
            item = self._items.popleft()
            released.append(TimedAtomicSample(item.source_time, item.arrival_index, deepcopy(item.content)))
        return released

    def release_due(self, current_time: float, delay_s: float) -> list[T]:
        return [item.content for item in self.release_due_samples(current_time, delay_s)]

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
