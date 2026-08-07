"""TTC-null 的独立几何复核、trace 校验与预注册根因分类。

本模块故意不导入正式 evaluator，避免独立计算器与生产实现共享错误。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence


class DiagnosticValidationError(ValueError):
    """诊断输入不完整或不满足隔离合同。"""


@dataclass(frozen=True)
class DiagnosticOBB:
    x: float
    y: float
    heading_rad: float
    length_m: float
    width_m: float
    velocity_x_mps: float = 0.0
    velocity_y_mps: float = 0.0
    object_id: str = ""

    def __post_init__(self) -> None:
        values = (
            self.x,
            self.y,
            self.heading_rad,
            self.length_m,
            self.width_m,
            self.velocity_x_mps,
            self.velocity_y_mps,
        )
        if not all(math.isfinite(value) for value in values):
            raise DiagnosticValidationError("OBB contains a non-finite value")
        if self.length_m <= 0.0 or self.width_m <= 0.0:
            raise DiagnosticValidationError("OBB dimensions must be positive")

    def at(self, seconds: float) -> "DiagnosticOBB":
        if not math.isfinite(seconds):
            raise DiagnosticValidationError("prediction time must be finite")
        return DiagnosticOBB(
            self.x + self.velocity_x_mps * seconds,
            self.y + self.velocity_y_mps * seconds,
            self.heading_rad,
            self.length_m,
            self.width_m,
            self.velocity_x_mps,
            self.velocity_y_mps,
            self.object_id,
        )

    def corners(self) -> tuple[tuple[float, float], ...]:
        forward = (math.cos(self.heading_rad), math.sin(self.heading_rad))
        left = (-forward[1], forward[0])
        half_length = self.length_m / 2.0
        half_width = self.width_m / 2.0
        return tuple(
            (
                self.x + longitudinal * forward[0] + lateral * left[0],
                self.y + longitudinal * forward[1] + lateral * left[1],
            )
            for longitudinal, lateral in (
                (half_length, half_width),
                (half_length, -half_width),
                (-half_length, -half_width),
                (-half_length, half_width),
            )
        )


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiagnosticValidationError(f"{path} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise DiagnosticValidationError(f"{path} must be finite")
    return result


def world_obb_from_carla_state(state: Mapping[str, Any]) -> DiagnosticOBB:
    """把 CARLA actor transform 与本地 bounding box 组合为世界坐标 OBB。"""

    required = {"actor_id", "location", "yaw_deg", "velocity", "bounding_box"}
    missing = sorted(required - set(state))
    if missing:
        raise DiagnosticValidationError("CARLA state missing: " + ", ".join(missing))
    location = state["location"]
    velocity = state["velocity"]
    box = state["bounding_box"]
    if not all(isinstance(item, Mapping) for item in (location, velocity, box)):
        raise DiagnosticValidationError("location, velocity and bounding_box must be mappings")
    for key in ("location", "extent"):
        if key not in box or not isinstance(box[key], Mapping):
            raise DiagnosticValidationError(f"bounding_box.{key} is required")
    actor_yaw = math.radians(_number(state["yaw_deg"], "yaw_deg"))
    local = box["location"]
    local_x = _number(local.get("x"), "bounding_box.location.x")
    local_y = _number(local.get("y"), "bounding_box.location.y")
    cos_yaw, sin_yaw = math.cos(actor_yaw), math.sin(actor_yaw)
    center_x = _number(location.get("x"), "location.x") + cos_yaw * local_x - sin_yaw * local_y
    center_y = _number(location.get("y"), "location.y") + sin_yaw * local_x + cos_yaw * local_y
    extent = box["extent"]
    return DiagnosticOBB(
        x=center_x,
        y=center_y,
        heading_rad=actor_yaw + math.radians(_number(box.get("yaw_deg", 0.0), "bounding_box.yaw_deg")),
        length_m=2.0 * _number(extent.get("x"), "bounding_box.extent.x"),
        width_m=2.0 * _number(extent.get("y"), "bounding_box.extent.y"),
        velocity_x_mps=_number(velocity.get("x"), "velocity.x"),
        velocity_y_mps=_number(velocity.get("y"), "velocity.y"),
        object_id=str(state["actor_id"]),
    )


def _dot(point: tuple[float, float], axis: tuple[float, float]) -> float:
    return point[0] * axis[0] + point[1] * axis[1]


def _axes(box: DiagnosticOBB) -> tuple[tuple[float, float], tuple[float, float]]:
    return (
        (math.cos(box.heading_rad), math.sin(box.heading_rad)),
        (-math.sin(box.heading_rad), math.cos(box.heading_rad)),
    )


def _overlap(left: DiagnosticOBB, right: DiagnosticOBB) -> bool:
    left_points, right_points = left.corners(), right.corners()
    for axis in (*_axes(left), *_axes(right)):
        left_values = [_dot(point, axis) for point in left_points]
        right_values = [_dot(point, axis) for point in right_points]
        if max(left_values) < min(right_values) or max(right_values) < min(left_values):
            return False
    return True


def _point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-24:
        return math.dist(point, start)
    scale = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
    projection = (start[0] + scale * dx, start[1] + scale * dy)
    return math.dist(point, projection)


def sat_separation_m(left: DiagnosticOBB, right: DiagnosticOBB) -> float:
    """返回两个矩形的欧氏边界距离；相交或接触时为 0。"""

    if _overlap(left, right):
        return 0.0
    left_points, right_points = left.corners(), right.corners()
    left_edges = tuple(zip(left_points, left_points[1:] + left_points[:1]))
    right_edges = tuple(zip(right_points, right_points[1:] + right_points[:1]))
    distances = []
    for point in left_points:
        distances.extend(_point_segment_distance(point, start, end) for start, end in right_edges)
    for point in right_points:
        distances.extend(_point_segment_distance(point, start, end) for start, end in left_edges)
    return min(distances)


def fine_step_ttc(
    left: DiagnosticOBB,
    right: DiagnosticOBB,
    *,
    horizon_s: float = 10.0,
    step_s: float = 0.01,
) -> float | None:
    if horizon_s <= 0.0 or step_s <= 0.0:
        raise DiagnosticValidationError("TTC horizon and step must be positive")
    steps = int(math.floor(horizon_s / step_s + 1e-12))
    for index in range(steps + 1):
        seconds = index * step_s
        if _overlap(left.at(seconds), right.at(seconds)):
            return seconds
    return None


@dataclass(frozen=True)
class ClosestApproach:
    time_s: float
    separation_m: float


def closest_approach(
    left: DiagnosticOBB,
    right: DiagnosticOBB,
    *,
    horizon_s: float = 10.0,
    step_s: float = 0.01,
) -> ClosestApproach:
    if horizon_s <= 0.0 or step_s <= 0.0:
        raise DiagnosticValidationError("closest-approach horizon and step must be positive")
    best = ClosestApproach(0.0, sat_separation_m(left, right))
    for index in range(1, int(math.floor(horizon_s / step_s + 1e-12)) + 1):
        seconds = index * step_s
        separation = sat_separation_m(left.at(seconds), right.at(seconds))
        if separation < best.separation_m:
            best = ClosestApproach(seconds, separation)
    return best


def sampled_prediction_geometry(
    left: DiagnosticOBB,
    right: DiagnosticOBB,
    *,
    horizon_s: float = 10.0,
    step_s: float = 0.01,
) -> tuple[float | None, ClosestApproach]:
    """高效执行同一固定步长的独立 SAT/多边形距离扫描。

    该函数不调用正式 evaluator；它与 ``fine_step_ttc`` 使用相同采样定义，
    但复用固定朝向矩形的轴和角点，保证 20 Hz replay 不丢帧。实现只依赖
    Python 标准库，因为 Apollo host Python 不包含 NumPy。
    """

    if horizon_s <= 0.0 or step_s <= 0.0:
        raise DiagnosticValidationError("prediction horizon and step must be positive")
    left_axes = _axes(left)
    right_axes = _axes(right)
    axes = (*left_axes, *right_axes)
    left_radii = tuple(
        (left.length_m / 2.0) * abs(_dot(axis, left_axes[0]))
        + (left.width_m / 2.0) * abs(_dot(axis, left_axes[1]))
        for axis in axes
    )
    right_radii = tuple(
        (right.length_m / 2.0) * abs(_dot(axis, right_axes[0]))
        + (right.width_m / 2.0) * abs(_dot(axis, right_axes[1]))
        for axis in axes
    )
    start_dx, start_dy = right.x - left.x, right.y - left.y
    velocity_dx = right.velocity_x_mps - left.velocity_x_mps
    velocity_dy = right.velocity_y_mps - left.velocity_y_mps
    relative_right_corners = tuple((x - left.x, y - left.y) for x, y in right.corners())
    relative_left_corners = tuple((x - left.x, y - left.y) for x, y in left.corners())

    def translated_right(seconds: float) -> tuple[tuple[float, float], ...]:
        shift_x = velocity_dx * seconds
        shift_y = velocity_dy * seconds
        return tuple((x + shift_x, y + shift_y) for x, y in relative_right_corners)

    def squared_point_segment_distance(
        point: tuple[float, float],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        edge_x, edge_y = end[0] - start[0], end[1] - start[1]
        denominator = edge_x * edge_x + edge_y * edge_y
        scale = (
            (point[0] - start[0]) * edge_x + (point[1] - start[1]) * edge_y
        ) / denominator
        scale = max(0.0, min(1.0, scale))
        dx = point[0] - (start[0] + scale * edge_x)
        dy = point[1] - (start[1] + scale * edge_y)
        return dx * dx + dy * dy

    count = int(math.floor(horizon_s / step_s + 1e-12)) + 1
    first_overlap: float | None = None
    lower_bounds: list[tuple[float, int]] = []
    projected_start = tuple(start_dx * axis[0] + start_dy * axis[1] for axis in axes)
    projected_velocity = tuple(
        velocity_dx * axis[0] + velocity_dy * axis[1] for axis in axes
    )
    combined_radii = tuple(a + b for a, b in zip(left_radii, right_radii, strict=True))
    for index in range(count):
        seconds = index * step_s
        lower_bound = max(
            0.0,
            *(
                abs(start + rate * seconds) - radius
                for start, rate, radius in zip(
                    projected_start,
                    projected_velocity,
                    combined_radii,
                    strict=True,
                )
            ),
        )
        if lower_bound <= 1e-12 and first_overlap is None:
            first_overlap = seconds
        lower_bounds.append((lower_bound, index))

    if first_overlap is not None:
        return first_overlap, ClosestApproach(time_s=first_overlap, separation_m=0.0)

    # SAT 最大轴间隙是欧氏距离下界。按下界由小到大求精确距离；一旦
    # 下界已不可能刷新当前最小值，其余 1001 个固定采样点也不可能刷新。
    best_squared = math.inf
    best_time = 0.0
    for lower_bound, index in sorted(lower_bounds):
        if lower_bound * lower_bound >= best_squared:
            break
        seconds = index * step_s
        right_points = translated_right(seconds)
        candidate = math.inf
        for points, polygon in (
            (relative_left_corners, right_points),
            (right_points, relative_left_corners),
        ):
            for point in points:
                for edge_index in range(4):
                    candidate = min(
                        candidate,
                        squared_point_segment_distance(
                            point,
                            polygon[edge_index],
                            polygon[(edge_index + 1) % 4],
                        ),
                    )
        if candidate < best_squared:
            best_squared = candidate
            best_time = seconds

    return first_overlap, ClosestApproach(
        time_s=best_time,
        separation_m=math.sqrt(max(0.0, best_squared)),
    )


def relative_state_in_ego_frame(ego: DiagnosticOBB, actor: DiagnosticOBB) -> dict[str, float]:
    dx, dy = actor.x - ego.x, actor.y - ego.y
    forward = (math.cos(ego.heading_rad), math.sin(ego.heading_rad))
    right = (forward[1], -forward[0])
    relative_velocity = (
        actor.velocity_x_mps - ego.velocity_x_mps,
        actor.velocity_y_mps - ego.velocity_y_mps,
    )
    return {
        "forward_m": dx * forward[0] + dy * forward[1],
        "right_m": dx * right[0] + dy * right[1],
        "closing_mps": -(relative_velocity[0] * forward[0] + relative_velocity[1] * forward[1]),
    }


def classify_tick_disagreement(
    production_ttc: float | None,
    independent_ttc: float | None,
    *,
    tolerance_s: float = 0.10,
) -> str:
    if tolerance_s < 0.0:
        raise DiagnosticValidationError("TTC tolerance cannot be negative")
    if production_ttc is None and independent_ttc is None:
        return "both_null"
    if production_ttc is None:
        return "production_null_independent_finite"
    if independent_ttc is None:
        return "production_finite_independent_null"
    return "agree" if abs(float(production_ttc) - float(independent_ttc)) <= tolerance_s else "finite_value_mismatch"


TRACE_REQUIRED_KEYS = {
    "frame",
    "sim_time_s",
    "wall_time_s",
    "route_epoch_elapsed_s",
    "ego",
    "interaction_actor",
    "actor_program",
    "relative",
    "geometry",
    "apollo",
    "road",
}


@dataclass(frozen=True)
class DiagnosticTraceRow:
    frame: int
    sim_time_s: float
    wall_time_s: float
    route_epoch_elapsed_s: float
    ego: Mapping[str, Any]
    interaction_actor: Mapping[str, Any]
    actor_program: Mapping[str, Any]
    relative: Mapping[str, Any]
    geometry: Mapping[str, Any]
    apollo: Mapping[str, Any]
    road: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiagnosticTraceRow":
        missing = sorted(TRACE_REQUIRED_KEYS - set(value))
        extra = sorted(set(value) - TRACE_REQUIRED_KEYS)
        if missing or extra:
            raise DiagnosticValidationError(f"trace keys missing={missing} extra={extra}")
        frame = value["frame"]
        if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
            raise DiagnosticValidationError("trace frame must be a nonnegative integer")
        for key in ("ego", "interaction_actor", "actor_program", "relative", "geometry", "apollo", "road"):
            if not isinstance(value[key], Mapping):
                raise DiagnosticValidationError(f"trace {key} must be a mapping")
        for actor_key in ("ego", "interaction_actor"):
            for required in ("actor_id", "role_name", "type_id", "location", "yaw_deg", "velocity", "acceleration", "bounding_box"):
                if required not in value[actor_key]:
                    raise DiagnosticValidationError(f"trace {actor_key}.{required} is required")
        for key in ("production_ttc_s", "independent_ttc_s", "predicted_min_obb_separation_m", "closest_approach_time_s"):
            if key not in value["geometry"]:
                raise DiagnosticValidationError(f"trace geometry.{key} is required")
            if value["geometry"][key] is None and not value["geometry"].get(f"{key}_missing_reason"):
                raise DiagnosticValidationError(f"trace null geometry.{key} lacks missing reason")
        return cls(
            frame=frame,
            sim_time_s=_number(value["sim_time_s"], "sim_time_s"),
            wall_time_s=_number(value["wall_time_s"], "wall_time_s"),
            route_epoch_elapsed_s=_number(value["route_epoch_elapsed_s"], "route_epoch_elapsed_s"),
            ego=value["ego"],
            interaction_actor=value["interaction_actor"],
            actor_program=value["actor_program"],
            relative=value["relative"],
            geometry=value["geometry"],
            apollo=value["apollo"],
            road=value["road"],
        )


class RootCause(str, Enum):
    TTC_EVALUATOR_OR_IDENTITY_BUG = "A_TTC_EVALUATOR_OR_IDENTITY_BUG"
    EGO_EXECUTION_OR_RUNTIME_BUG = "B_EGO_EXECUTION_OR_RUNTIME_BUG"
    INTERACTION_ACTOR_EXECUTION_BUG = "C_INTERACTION_ACTOR_EXECUTION_BUG"
    PROTOCOL_SCENARIO_OR_ADMISSION_DESIGN_FAILURE = "D_PROTOCOL_SCENARIO_OR_ADMISSION_DESIGN_FAILURE"
    INSUFFICIENT_EVIDENCE = "E_INSUFFICIENT_EVIDENCE"


def summarize_trace(trace_path: Path) -> dict[str, Any]:
    rows: list[DiagnosticTraceRow] = []
    for line_number, line in enumerate(trace_path.read_text().splitlines(), 1):
        if not line.strip():
            raise DiagnosticValidationError(f"blank trace line {line_number}")
        try:
            document = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DiagnosticValidationError(f"invalid JSON at trace line {line_number}") from exc
        rows.append(DiagnosticTraceRow.from_dict(document))
    if not rows:
        raise DiagnosticValidationError("diagnostic trace is empty")
    frames = [row.frame for row in rows]
    ego_ids = {str(row.ego["actor_id"]) for row in rows}
    actor_ids = {str(row.interaction_actor["actor_id"]) for row in rows}
    ego_xy = [(_number(row.ego["location"]["x"], "ego.x"), _number(row.ego["location"]["y"], "ego.y")) for row in rows]
    ego_speeds = [math.hypot(_number(row.ego["velocity"]["x"], "ego.vx"), _number(row.ego["velocity"]["y"], "ego.vy")) for row in rows]
    center = [_number(row.relative["center_distance_m"], "relative.center_distance_m") for row in rows]
    separations = [_number(row.geometry["current_obb_separation_m"], "geometry.current_obb_separation_m") for row in rows]
    production = [row.geometry["production_ttc_s"] for row in rows]
    independent = [row.geometry["independent_ttc_s"] for row in rows]
    disagreement = [classify_tick_disagreement(left, right) for left, right in zip(production, independent)]
    return {
        "unique_ego_actor_ids": sorted(ego_ids),
        "unique_interaction_actor_ids": sorted(actor_ids),
        "trace_frames": len(rows),
        "sim_duration_s": rows[-1].sim_time_s - rows[0].sim_time_s,
        "non_unit_frame_gaps": sum(right - left != 1 for left, right in zip(frames, frames[1:])),
        "ego_progress_m": math.dist(ego_xy[0], ego_xy[-1]),
        "ego_speed_median_mps": median(ego_speeds),
        "ego_speed_max_mps": max(ego_speeds),
        "min_center_distance_m": min(center),
        "min_obb_separation_m": min(separations),
        "positive_closing_duration_s": sum(
            0.05 for row in rows if _number(row.relative["closing_mps"], "relative.closing_mps") > 0.0
        ),
        "production_finite_ttc_ticks": sum(value is not None for value in production),
        "independent_finite_ttc_ticks": sum(value is not None for value in independent),
        "finite_null_disagreement_ticks": sum(value == "production_null_independent_finite" for value in disagreement),
    }


def classify_root_cause(summary: Mapping[str, Any]) -> RootCause:
    if len(summary.get("unique_ego_actor_ids", ())) != 1 or len(summary.get("unique_interaction_actor_ids", ())) != 1:
        return RootCause.TTC_EVALUATOR_OR_IDENTITY_BUG
    if int(summary.get("stable_finite_null_disagreement_ticks", summary.get("finite_null_disagreement_ticks", 0))) >= 3:
        return RootCause.TTC_EVALUATOR_OR_IDENTITY_BUG
    if bool(summary.get("ego_execution_bug")) or bool(summary.get("control_topic_or_gear_mismatch")):
        return RootCause.EGO_EXECUTION_OR_RUNTIME_BUG
    if float(summary.get("actor_spawn_offset_error_m", 0.0)) > 0.50 or float(summary.get("actor_yaw_error_deg", 0.0)) > 2.0 or float(summary.get("actor_velocity_rmse_mps", 0.0)) > 0.50 or abs(float(summary.get("actor_conflict_timing_error_s", 0.0))) > 0.10:
        return RootCause.INTERACTION_ACTOR_EXECUTION_BUG
    if bool(summary.get("trigger_too_early")) or bool(summary.get("cut_in_has_no_terminal_condition")) or bool(summary.get("planned_path_admission_mismatch")) or bool(summary.get("window_design_failure")):
        return RootCause.PROTOCOL_SCENARIO_OR_ADMISSION_DESIGN_FAILURE
    return RootCause.INSUFFICIENT_EVIDENCE


def analytic_candidate_sanity(
    candidate: Mapping[str, Any],
    semantic_family: str,
    ego_speed_mps: float,
    *,
    duration_s: float = 60.0,
    step_s: float = 0.05,
) -> dict[str, Any]:
    """纯解析复核冻结候选；不是候选搜索器，也不写 calibration 状态。"""

    ego = DiagnosticOBB(0.0, 0.0, 0.0, 4.7, 2.0, float(ego_speed_mps), 0.0, "ego")
    first_lane_center = None
    first_finite = None
    first_in_band = None
    minimum_separation = math.inf
    actor_stop_s = None
    lateral_at_end = 0.0
    lateral_speed_at_end = 0.0
    lead_final_x = None
    lead_braking_distance = None
    samples = int(round(duration_s / step_s)) + 1
    for index in range(samples):
        seconds = index * step_s
        if semantic_family == "lead_vehicle_deceleration":
            gap = float(candidate["initial_gap_m"])
            speed = float(candidate["lead_speed_mps"])
            brake = float(candidate["brake_start_s"])
            deceleration = float(candidate["deceleration_mps2"])
            after = max(0.0, seconds - brake)
            braking_duration = speed / deceleration
            braking_elapsed = min(after, braking_duration)
            actor_x = gap + speed * min(seconds, brake) + speed * braking_elapsed - 0.5 * deceleration * braking_elapsed**2
            actor_speed = speed if seconds < brake else max(0.0, speed - deceleration * after)
            actor_y = 0.0
            lateral_speed = 0.0
            actor_stop_s = brake + braking_duration
            lead_braking_distance = speed**2 / (2.0 * deceleration)
            lead_final_x = gap + speed * brake + lead_braking_distance
        else:
            actor_x = float(candidate["longitudinal_offset_m"]) + float(candidate["longitudinal_speed_mps"]) * seconds
            cut_in = float(candidate["cut_in_start_s"])
            acceleration = float(candidate["lateral_acceleration_mps2"])
            maximum = float(candidate["maximum_lateral_speed_mps"])
            after = max(0.0, seconds - cut_in)
            ramp_duration = maximum / acceleration
            ramp_elapsed = min(after, ramp_duration)
            actor_y = float(candidate["lateral_offset_m"]) + 0.5 * acceleration * ramp_elapsed**2 + maximum * max(0.0, after - ramp_duration)
            lateral_speed = min(maximum, acceleration * after)
            if first_lane_center is None and actor_y >= 0.0:
                first_lane_center = seconds
            lateral_at_end = actor_y
            lateral_speed_at_end = lateral_speed
        actor = DiagnosticOBB(actor_x, actor_y, 0.0, 4.7, 2.0, (float(candidate.get("lead_speed_mps", candidate.get("longitudinal_speed_mps", 0.0))) if semantic_family != "lead_vehicle_deceleration" else actor_speed), lateral_speed, "actor")
        ego_tick = ego.at(seconds)
        separation = sat_separation_m(ego_tick, actor)
        minimum_separation = min(minimum_separation, separation)
        # 四个冻结 sanity 候选的 actor/ego box 航向均为 0；这里用等价的
        # 连续时间轴对齐区间求交，避免在每个 0.05 s tick 内再嵌套 201 次 SAT。
        ttc = _axis_aligned_ttc(ego_tick, actor, horizon_s=10.0)
        if ttc is not None and first_finite is None:
            first_finite = seconds
        if ttc is not None and 2.5 < ttc <= 6.0 and first_in_band is None:
            first_in_band = seconds
    return {
        "ego_speed_mps": float(ego_speed_mps),
        "minimum_separation_m": minimum_separation,
        "first_finite_ttc_at_s": first_finite,
        "first_ttc_in_band_at_s": first_in_band,
        "enters_ttc_band": first_in_band is not None,
        "actor_crosses_ego_lane_center_s": first_lane_center,
        "actor_lateral_displacement_at_32s_m": (
            None if semantic_family == "lead_vehicle_deceleration" else _cut_in_displacement(candidate, 32.0)
        ),
        "actor_lateral_velocity_at_32s_mps": (
            None if semantic_family == "lead_vehicle_deceleration" else min(float(candidate["maximum_lateral_speed_mps"]), float(candidate["lateral_acceleration_mps2"]) * max(0.0, 32.0 - float(candidate["cut_in_start_s"])))
        ),
        "actor_stops_s": actor_stop_s,
        "lead_braking_distance_m": lead_braking_distance,
        "lead_final_position_from_initial_ego_m": lead_final_x,
        "lateral_velocity_nonzero_after_lane_center": (
            False if semantic_family == "lead_vehicle_deceleration" else first_lane_center is not None and lateral_speed_at_end > 0.30
        ),
    }


def _axis_overlap_interval(
    delta: float, relative_velocity: float, half_extent_sum: float, horizon_s: float
) -> tuple[float, float] | None:
    if abs(relative_velocity) <= 1e-12:
        return (0.0, horizon_s) if abs(delta) <= half_extent_sum else None
    left = (-half_extent_sum - delta) / relative_velocity
    right = (half_extent_sum - delta) / relative_velocity
    start, end = sorted((left, right))
    start, end = max(0.0, start), min(horizon_s, end)
    return (start, end) if start <= end else None


def _axis_aligned_ttc(
    left: DiagnosticOBB, right: DiagnosticOBB, *, horizon_s: float
) -> float | None:
    x_interval = _axis_overlap_interval(
        right.x - left.x,
        right.velocity_x_mps - left.velocity_x_mps,
        (left.length_m + right.length_m) / 2.0,
        horizon_s,
    )
    y_interval = _axis_overlap_interval(
        right.y - left.y,
        right.velocity_y_mps - left.velocity_y_mps,
        (left.width_m + right.width_m) / 2.0,
        horizon_s,
    )
    if x_interval is None or y_interval is None:
        return None
    start = max(x_interval[0], y_interval[0])
    end = min(x_interval[1], y_interval[1])
    return start if start <= end else None


def _cut_in_displacement(candidate: Mapping[str, Any], seconds: float) -> float:
    after = max(0.0, seconds - float(candidate["cut_in_start_s"]))
    acceleration = float(candidate["lateral_acceleration_mps2"])
    maximum = float(candidate["maximum_lateral_speed_mps"])
    ramp = maximum / acceleration
    ramp_elapsed = min(after, ramp)
    return 0.5 * acceleration * ramp_elapsed**2 + maximum * max(0.0, after - ramp)
