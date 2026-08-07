#!/usr/bin/env python3
"""Isolated, private, diagnostic-only replay runtime for TTC-null root cause analysis."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from statistics import median
import threading
import time
import traceback
from typing import Any, Mapping

import carla
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest, RoutingResponse

from cage_ad.diagnostics.ttc_null import (
    DiagnosticOBB,
    DiagnosticTraceRow,
    classify_root_cause,
    relative_state_in_ego_frame,
    sampled_prediction_geometry,
    sat_separation_m,
    world_obb_from_carla_state,
)
from cage_ad.protocol_v1.evaluator import OrientedBox, oriented_box_ttc
from cage_ad.protocol_v1.loader import PROTOCOL_VERSION, ProtocolValidationError, load_protocol
from cage_ad.protocol_v1.scenario import scenario_candidate_by_id


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _actor_state(actor) -> dict[str, Any]:
    transform = actor.get_transform()
    velocity = actor.get_velocity()
    acceleration = actor.get_acceleration()
    box = actor.bounding_box
    state = {
        "actor_id": int(actor.id),
        "role_name": actor.attributes.get("role_name", ""),
        "type_id": actor.type_id,
        "location": {"x": transform.location.x, "y": transform.location.y, "z": transform.location.z},
        "yaw_deg": transform.rotation.yaw,
        "velocity": {"x": velocity.x, "y": velocity.y, "z": velocity.z},
        "acceleration": {"x": acceleration.x, "y": acceleration.y, "z": acceleration.z},
        "bounding_box": {
            "location": {"x": box.location.x, "y": box.location.y, "z": box.location.z},
            "yaw_deg": box.rotation.yaw,
            "extent": {"x": box.extent.x, "y": box.extent.y, "z": box.extent.z},
        },
    }
    if state["role_name"] == "ego_vehicle":
        control = actor.get_control()
        state["carla_control"] = {
            "throttle": control.throttle,
            "brake": control.brake,
            "steer": control.steer,
            "reverse": control.reverse,
            "hand_brake": control.hand_brake,
        }
    return state


def _production_box(state: Mapping[str, Any]) -> OrientedBox:
    independent = world_obb_from_carla_state(state)
    return OrientedBox(
        independent.x,
        independent.y,
        independent.heading_rad,
        independent.length_m,
        independent.width_m,
        independent.velocity_x_mps,
        independent.velocity_y_mps,
        independent.object_id,
    )


def _prediction_geometry(
    left: DiagnosticOBB,
    right: DiagnosticOBB,
    *,
    horizon_s: float = 10.0,
    step_s: float = 0.01,
) -> tuple[float | None, float, float]:
    ttc, approach = sampled_prediction_geometry(
        left, right, horizon_s=horizon_s, step_s=step_s
    )
    return ttc, approach.separation_m, approach.time_s


def _missing(value: Any, reason: str) -> tuple[Any, str | None]:
    return (value, None) if value is not None else (None, reason)


def _waypoint(world_map, location) -> dict[str, Any]:
    waypoint = world_map.get_waypoint(location, project_to_road=False)
    if waypoint is None:
        return {
            "road_id": None,
            "road_id_missing_reason": "CARLA map returned no waypoint",
            "section_id": None,
            "section_id_missing_reason": "CARLA map returned no waypoint",
            "lane_id": None,
            "lane_id_missing_reason": "CARLA map returned no waypoint",
            "lane_type": None,
            "lane_type_missing_reason": "CARLA map returned no waypoint",
        }
    return {
        "road_id": waypoint.road_id,
        "section_id": waypoint.section_id,
        "lane_id": waypoint.lane_id,
        "lane_type": str(waypoint.lane_type),
    }


class ApolloSamples:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.localization: dict[str, Any] | None = None
        self.chassis: dict[str, Any] | None = None
        self.planning: dict[str, Any] | None = None
        self.control: dict[str, Any] | None = None
        self.route_count = 0
        self.route_accepted = False

    def on_localization(self, message: LocalizationEstimate) -> None:
        pose = message.pose
        with self.lock:
            self.localization = {
                "position": {"x": pose.position.x, "y": pose.position.y, "z": pose.position.z},
                "heading": pose.heading,
                "linear_velocity": {"x": pose.linear_velocity.x, "y": pose.linear_velocity.y, "z": pose.linear_velocity.z},
                "speed_mps": math.hypot(pose.linear_velocity.x, pose.linear_velocity.y),
            }

    def on_chassis(self, message: Chassis) -> None:
        with self.lock:
            self.chassis = {
                "speed_mps": message.speed_mps,
                "gear_location": int(message.gear_location),
                "driving_mode": int(message.driving_mode),
                "throttle_percentage": message.throttle_percentage,
                "brake_percentage": message.brake_percentage,
                "steering_percentage": message.steering_percentage,
            }

    def on_planning(self, message: ADCTrajectory) -> None:
        points = [
            {
                "relative_time": point.relative_time,
                "x": point.path_point.x,
                "y": point.path_point.y,
                "heading": point.path_point.theta,
                "v": point.v,
                "a": point.a,
            }
            for point in message.trajectory_point
            if 0.0 <= point.relative_time <= 3.0
        ]
        target = min(points, key=lambda item: abs(item["relative_time"] - 1.0)) if points else None
        sampled_points = points[::5]
        if points and (not sampled_points or sampled_points[-1] is not points[-1]):
            sampled_points.append(points[-1])
        decision_text = str(message.decision)[:2000]
        with self.lock:
            self.planning = {
                "points_first_3s": sampled_points,
                "points_first_3s_total": len(points),
                "points_first_3s_sampling": "every_fifth_plus_last",
                "_full_points_first_3s": points,
                "target_speed_1s_mps": None if target is None else target["v"],
                "target_acceleration_1s_mps2": None if target is None else target["a"],
                "decision_text": decision_text,
                "decision_mentions_obstacle_1001": "1001" in decision_text,
                "estop": bool(message.estop.is_estop),
                "replan_reason": message.replan_reason,
                "gear": int(message.gear),
            }

    def on_control(self, message: ControlCommand) -> None:
        with self.lock:
            self.control = {
                "throttle": message.throttle,
                "brake": message.brake,
                "steering_target": message.steering_target,
                "gear_location": int(message.gear_location),
                "speed": message.speed,
                "acceleration": message.acceleration,
            }

    def on_route(self, message: RoutingResponse) -> None:
        with self.lock:
            self.route_count += 1
            self.route_accepted = self.route_accepted or (
                message.status.error_code == 0 and len(message.road) > 0
            )

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "localization": None if self.localization is None else dict(self.localization),
                "chassis": None if self.chassis is None else dict(self.chassis),
                "planning": None if self.planning is None else dict(self.planning),
                "control_guarded": None if self.control is None else dict(self.control),
                "route_count": self.route_count,
                "route_accepted": self.route_accepted,
            }


def _apollo_trace(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("localization", "chassis", "planning", "control_guarded"):
        value, reason = _missing(snapshot.get(name), f"no {name} message observed yet")
        if name == "planning" and value is not None:
            value = {key: item for key, item in value.items() if not key.startswith("_")}
        result[name] = value
        if reason:
            result[f"{name}_missing_reason"] = reason
    result["bridge_subscribed_control_topic"] = "/apollo/control_guarded"
    return result


def _planned_path_geometry(
    planning: Mapping[str, Any] | None,
    actor: DiagnosticOBB,
    candidate,
    elapsed_s: float,
    forward: tuple[float, float],
    right: tuple[float, float],
) -> tuple[float | None, float | None]:
    if planning is None or not planning.get("points_first_3s"):
        return None, None
    minimum = math.inf
    minimum_time = None
    for point in planning.get("_full_points_first_3s", planning["points_first_3s"]):
        horizon = max(0.0, float(point["relative_time"]))
        longitudinal, lateral = candidate.displacement(elapsed_s, horizon)
        predicted_actor = DiagnosticOBB(
            actor.x + forward[0] * longitudinal + right[0] * lateral,
            actor.y + forward[1] * longitudinal + right[1] * lateral,
            actor.heading_rad,
            actor.length_m,
            actor.width_m,
        )
        planned_ego = DiagnosticOBB(
            float(point["x"]),
            -float(point["y"]),
            -float(point["heading"]),
            4.7,
            2.0,
        )
        separation = sat_separation_m(planned_ego, predicted_actor)
        if separation < minimum:
            minimum = separation
            minimum_time = horizon
    return minimum, minimum_time


def _median_or_none(values: list[float]) -> float | None:
    return None if not values else median(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config.get("diagnostic_only_not_dataset") is not True or int(config.get("seed", -1)) != 1101:
        raise ProtocolValidationError("runtime requires DIAGNOSTIC_ONLY_NOT_DATASET seed 1101 config")
    bundle = load_protocol(args.repo_root, validate_json_schema=False)
    if config.get("protocol_bundle_sha256") != bundle.bundle_sha256:
        raise ProtocolValidationError("diagnostic protocol bundle hash mismatch")
    candidate = scenario_candidate_by_id(bundle, config["scenario_id"], config["candidate_id"])
    duration = float(config["duration_s"])
    common = bundle.scenarios["common"]
    start_xy = tuple(map(float, common["route_start_apollo_xy"]))
    destination_xy = tuple(map(float, common["route_end_apollo_xy"]))

    cyber.init("cage_d0_ttc_diagnostic_" + config["run_id"])
    node = cyber.Node("cage_d0_ttc_diagnostic_" + config["run_id"])
    apollo = ApolloSamples()
    readers = [
        node.create_reader("/apollo/localization/pose", LocalizationEstimate, apollo.on_localization),
        node.create_reader("/apollo/canbus/chassis", Chassis, apollo.on_chassis),
        node.create_reader("/apollo/planning", ADCTrajectory, apollo.on_planning),
        node.create_reader("/apollo/control_guarded", ControlCommand, apollo.on_control),
        node.create_reader("/apollo/routing_response", RoutingResponse, apollo.on_route),
    ]
    route_writer = node.create_writer("/apollo/routing_request", RoutingRequest, 10)
    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10)
    world = client.get_world()
    world_map = world.get_map()
    world.wait_for_tick(5)
    deadline = time.monotonic() + 15.0
    ego = interaction = None
    while time.monotonic() < deadline and (ego is None or interaction is None):
        vehicles = world.get_actors().filter("vehicle.*")
        egos = [item for item in vehicles if item.attributes.get("role_name") == "ego_vehicle"]
        actors = [item for item in vehicles if item.attributes.get("role_name") == "cage_interaction_actor"]
        ego = egos[0] if len(egos) == 1 else None
        interaction = actors[0] if len(actors) == 1 else None
        if ego is None or interaction is None:
            world.wait_for_tick(1)
    if ego is None or interaction is None:
        raise RuntimeError("diagnostic requires exactly one ego and interaction actor before route")
    spawn_ego = ego.get_transform()
    spawn_actor = interaction.get_transform()
    forward_vector = spawn_ego.get_forward_vector()
    right_vector = spawn_ego.get_right_vector()
    forward = (forward_vector.x, forward_vector.y)
    right = (right_vector.x, right_vector.y)
    longitudinal_offset, lateral_offset = candidate.spawn_offsets_m
    expected_x = spawn_ego.location.x + forward[0] * longitudinal_offset + right[0] * lateral_offset
    expected_y = spawn_ego.location.y + forward[1] * longitudinal_offset + right[1] * lateral_offset
    spawn_error = math.dist((expected_x, expected_y), (spawn_actor.location.x, spawn_actor.location.y))
    yaw_error = abs((spawn_actor.rotation.yaw - spawn_ego.rotation.yaw + 180.0) % 360.0 - 180.0)

    request = RoutingRequest()
    request.header.module_name = "cage_d0_ttc_diagnostic"
    request.is_start_pose_set = True
    for x, y in (start_xy, destination_xy):
        waypoint = request.waypoint.add()
        waypoint.pose.x = x
        waypoint.pose.y = y
        waypoint.heading = 0.0
    deadline = time.monotonic() + 10.0
    next_publish = 0.0
    while time.monotonic() < deadline and not apollo.snapshot()["route_accepted"]:
        now = time.monotonic()
        if now >= next_publish:
            request.header.timestamp_sec = time.time()
            request.header.sequence_num += 1
            route_writer.write(request)
            next_publish = now + 0.5
        world.wait_for_tick(2)
    if not apollo.snapshot()["route_accepted"]:
        raise RuntimeError("diagnostic routing response was not accepted")

    snapshot = world.get_snapshot()
    route_epoch_sim = snapshot.timestamp.elapsed_seconds
    wall_started = time.monotonic()
    frames: list[int] = []
    rows: list[dict[str, Any]] = []
    velocity_errors: list[float] = []
    observed_conflict_start = None
    ego_first_0_5 = None
    ego_first_2_0 = None
    actor_cross = None
    actor_stop = None
    minimum_separation_time = None
    minimum_separation = math.inf
    trace_temp = args.trace.with_suffix(args.trace.suffix + f".tmp.{os.getpid()}")
    trace_temp.parent.mkdir(parents=True, exist_ok=True)
    with trace_temp.open("w") as stream:
        while snapshot.timestamp.elapsed_seconds - route_epoch_sim < duration:
            snapshot = world.wait_for_tick(5)
            elapsed = snapshot.timestamp.elapsed_seconds - route_epoch_sim
            vehicles = world.get_actors().filter("vehicle.*")
            egos = [item for item in vehicles if item.attributes.get("role_name") == "ego_vehicle"]
            actors = [item for item in vehicles if item.attributes.get("role_name") == "cage_interaction_actor"]
            if len(egos) != 1 or len(actors) != 1:
                raise RuntimeError(f"actor identity count changed ego={len(egos)} interaction={len(actors)}")
            ego, interaction = egos[0], actors[0]
            ego_state, actor_state = _actor_state(ego), _actor_state(interaction)
            ego_box = world_obb_from_carla_state(ego_state)
            actor_box = world_obb_from_carla_state(actor_state)
            production = oriented_box_ttc(_production_box(ego_state), _production_box(actor_state))
            independent, predicted_minimum, closest_time = _prediction_geometry(ego_box, actor_box)
            current_separation = sat_separation_m(ego_box, actor_box)
            relative = relative_state_in_ego_frame(ego_box, actor_box)
            center_distance = math.dist((ego_box.x, ego_box.y), (actor_box.x, actor_box.y))
            relative["center_distance_m"] = center_distance
            intended_longitudinal, intended_lateral = candidate.velocity(elapsed)
            intended_world = (
                forward[0] * intended_longitudinal + right[0] * intended_lateral,
                forward[1] * intended_longitudinal + right[1] * intended_lateral,
            )
            actual_velocity = actor_state["velocity"]
            velocity_errors.append(math.hypot(actual_velocity["x"] - intended_world[0], actual_velocity["y"] - intended_world[1]))
            actual_longitudinal = actual_velocity["x"] * forward[0] + actual_velocity["y"] * forward[1]
            actual_lateral = actual_velocity["x"] * right[0] + actual_velocity["y"] * right[1]
            if observed_conflict_start is None:
                if candidate.semantic_family == "lead_vehicle_deceleration" and elapsed >= candidate.conflict_onset_s and actual_longitudinal < float(candidate.values["lead_speed_mps"]) - 0.5:
                    observed_conflict_start = elapsed
                if candidate.semantic_family != "lead_vehicle_deceleration" and abs(actual_lateral) > 0.10:
                    observed_conflict_start = elapsed
            speed = math.hypot(ego_state["velocity"]["x"], ego_state["velocity"]["y"])
            if ego_first_0_5 is None and speed > 0.5:
                ego_first_0_5 = elapsed
            if ego_first_2_0 is None and speed > 2.0:
                ego_first_2_0 = elapsed
            actor_dx = actor_box.x - spawn_ego.location.x
            actor_dy = actor_box.y - spawn_ego.location.y
            actor_lateral_from_spawn_ego = actor_dx * right[0] + actor_dy * right[1]
            if actor_cross is None and candidate.semantic_family != "lead_vehicle_deceleration" and actor_lateral_from_spawn_ego >= 0.0:
                actor_cross = elapsed
            if actor_stop is None and candidate.semantic_family == "lead_vehicle_deceleration" and elapsed >= candidate.conflict_onset_s and math.hypot(actual_velocity["x"], actual_velocity["y"]) < 0.30:
                actor_stop = elapsed
            if current_separation < minimum_separation:
                minimum_separation = current_separation
                minimum_separation_time = elapsed
            apollo_snapshot = apollo.snapshot()
            planning = apollo_snapshot.get("planning")
            planned_minimum, planned_time = _planned_path_geometry(planning, actor_box, candidate, elapsed, forward, right)
            geometry = {
                "production_ttc_s": production,
                "independent_ttc_s": independent,
                "predicted_min_obb_separation_m": predicted_minimum,
                "closest_approach_time_s": closest_time,
                "current_obb_separation_m": current_separation,
                "planned_path_min_separation_m": planned_minimum,
                "planned_path_conflict_time_s": planned_time,
            }
            for key in ("production_ttc_s", "independent_ttc_s"):
                if geometry[key] is None:
                    geometry[f"{key}_missing_reason"] = "no predicted OBB overlap within 10 seconds"
            if planned_minimum is None:
                geometry["planned_path_min_separation_m_missing_reason"] = "no planning trajectory points in first 3 seconds"
                geometry["planned_path_conflict_time_s_missing_reason"] = "no planning trajectory points in first 3 seconds"
            road = {
                "ego": _waypoint(world_map, ego.get_location()),
                "interaction_actor": _waypoint(world_map, interaction.get_location()),
                "ego_traffic_light_state": str(ego.get_traffic_light_state()),
                "ego_is_at_traffic_light": ego.is_at_traffic_light(),
            }
            row = {
                "frame": snapshot.frame,
                "sim_time_s": elapsed,
                "wall_time_s": time.monotonic() - wall_started,
                "route_epoch_elapsed_s": elapsed,
                "ego": ego_state,
                "interaction_actor": actor_state,
                "actor_program": {
                    "state": "pre_epoch_frozen" if elapsed < 0.0 else "active",
                    "intended_longitudinal_velocity_mps": intended_longitudinal,
                    "intended_lateral_velocity_mps": intended_lateral,
                    "intended_world_velocity_x_mps": intended_world[0],
                    "intended_world_velocity_y_mps": intended_world[1],
                    "actual_longitudinal_velocity_mps": actual_longitudinal,
                    "actual_lateral_velocity_mps": actual_lateral,
                    "spawn_basis_forward": list(forward),
                    "spawn_basis_right": list(right),
                },
                "relative": relative,
                "geometry": geometry,
                "apollo": _apollo_trace(apollo_snapshot),
                "road": road,
            }
            DiagnosticTraceRow.from_dict(row)
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            rows.append(row)
            frames.append(snapshot.frame)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(trace_temp, 0o600)
    os.replace(trace_temp, args.trace)

    gaps = sum(right_frame - left_frame != 1 for left_frame, right_frame in zip(frames, frames[1:]))
    ego_speeds = [math.hypot(row["ego"]["velocity"]["x"], row["ego"]["velocity"]["y"]) for row in rows]
    planning_targets = [row["apollo"]["planning"]["target_speed_1s_mps"] for row in rows if row["apollo"].get("planning") and row["apollo"]["planning"].get("target_speed_1s_mps") is not None and row["sim_time_s"] <= 10.0]
    controls = [row["apollo"]["control_guarded"] for row in rows if row["apollo"].get("control_guarded")]
    production_finite = sum(row["geometry"]["production_ttc_s"] is not None for row in rows)
    independent_finite = sum(row["geometry"]["independent_ttc_s"] is not None for row in rows)
    mismatch_flags = [row["geometry"]["production_ttc_s"] is None and row["geometry"]["independent_ttc_s"] is not None for row in rows]
    stable_mismatch = max((sum(mismatch_flags[index:index + 3]) for index in range(max(1, len(rows) - 2))), default=0) >= 3
    planned_values = [row["geometry"]["planned_path_min_separation_m"] for row in rows if row["geometry"]["planned_path_min_separation_m"] is not None]
    planning_stop = any(row["apollo"].get("planning") and ((row["apollo"]["planning"].get("target_speed_1s_mps") is not None and row["apollo"]["planning"]["target_speed_1s_mps"] < 0.30) or row["apollo"]["planning"].get("decision_mentions_obstacle_1001")) for row in rows)
    control_brake = [float(item["brake"]) for item in controls]
    control_throttle = [float(item["throttle"]) for item in controls]
    safety_stop = planning_stop or sum(value > 10.0 for value in control_brake) >= 40
    ego_execution_bug = False
    for index in range(0, max(0, len(rows) - 99)):
        window = rows[index:index + 100]
        targets = [item["apollo"]["planning"]["target_speed_1s_mps"] for item in window if item["apollo"].get("planning") and item["apollo"]["planning"].get("target_speed_1s_mps") is not None]
        commands = [item["apollo"]["control_guarded"] for item in window if item["apollo"].get("control_guarded")]
        actual = [math.hypot(item["ego"]["velocity"]["x"], item["ego"]["velocity"]["y"]) for item in window]
        if targets and commands and median(targets) >= 1.0 and median(item["brake"] for item in commands) < 5.0 and median(item["throttle"] for item in commands) > 10.0 and median(actual) < 0.30:
            ego_execution_bug = True
            break
    reached_two = ego_first_2_0 if ego_first_2_0 is not None else math.inf
    actor_completed_before_two = (actor_stop is not None and actor_stop < reached_two) or (actor_cross is not None and actor_cross < reached_two)
    trigger_too_early = candidate.conflict_onset_s < reached_two and actor_completed_before_two
    cut_no_terminal = candidate.semantic_family != "lead_vehicle_deceleration" and actor_cross is not None and any(abs(row["actor_program"]["actual_lateral_velocity_mps"]) > 0.30 and row["sim_time_s"] >= actor_cross + 1.0 for row in rows)
    planned_min = min(planned_values) if planned_values else None
    admission_mismatch = production_finite == 0 and planned_min is not None and planned_min < 1.0 and safety_stop
    first_finite_elapsed = next((row["sim_time_s"] for row in rows if row["geometry"]["production_ttc_s"] is not None), None)
    summary = {
        "schema_version": 1,
        "label": "DIAGNOSTIC_ONLY_NOT_DATASET",
        "run_id": config["run_id"],
        "scenario_id": config["scenario_id"],
        "candidate_id": config["candidate_id"],
        "seed": config["seed"],
        "duration_requested_s": duration,
        "unique_ego_actor_ids": sorted({row["ego"]["actor_id"] for row in rows}),
        "unique_interaction_actor_ids": sorted({row["interaction_actor"]["actor_id"] for row in rows}),
        "trace_frames": len(rows),
        "sim_duration_s": rows[-1]["sim_time_s"] - rows[0]["sim_time_s"],
        "non_unit_frame_gaps": gaps,
        "ego_progress_m": math.dist((rows[0]["ego"]["location"]["x"], rows[0]["ego"]["location"]["y"]), (rows[-1]["ego"]["location"]["x"], rows[-1]["ego"]["location"]["y"])),
        "ego_speed_median_mps": median(ego_speeds),
        "ego_speed_max_mps": max(ego_speeds),
        "planning_target_speed_median_first_10s": _median_or_none(planning_targets),
        "control_throttle_fraction": None if not control_throttle else sum(value > 10.0 for value in control_throttle) / len(control_throttle),
        "control_brake_fraction": None if not control_brake else sum(value > 10.0 for value in control_brake) / len(control_brake),
        "actor_spawn_offset_error_m": spawn_error,
        "actor_yaw_error_deg": yaw_error,
        "actor_velocity_rmse_mps": math.sqrt(sum(value * value for value in velocity_errors) / len(velocity_errors)),
        "actor_conflict_timing_error_s": None if observed_conflict_start is None else observed_conflict_start - candidate.conflict_onset_s,
        "min_center_distance_m": min(row["relative"]["center_distance_m"] for row in rows),
        "min_obb_separation_m": minimum_separation,
        "positive_closing_duration_s": sum(0.05 for row in rows if row["relative"]["closing_mps"] > 0.0),
        "production_finite_ttc_ticks": production_finite,
        "independent_finite_ttc_ticks": independent_finite,
        "finite_null_disagreement_ticks": sum(mismatch_flags),
        "stable_finite_null_disagreement_ticks": 3 if stable_mismatch else 0,
        "planned_path_conflict": planned_min is not None and planned_min < 1.0,
        "planned_path_min_separation_m": planned_min,
        "planned_path_conflict_time_s": next((row["sim_time_s"] + row["geometry"]["planned_path_conflict_time_s"] for row in rows if row["geometry"]["planned_path_min_separation_m"] == planned_min), None),
        "events": {
            "route_epoch_s": route_epoch_sim,
            "ego_first_speed_above_0_5_mps_s": ego_first_0_5,
            "ego_first_speed_above_2_0_mps_s": ego_first_2_0,
            "actor_conflict_program_start_s": candidate.conflict_onset_s,
            "actor_crosses_ego_lane_center_s": actor_cross,
            "actor_stops_s": actor_stop,
            "minimum_geometric_separation_s": minimum_separation_time,
        },
        "ego_execution_bug": ego_execution_bug,
        "control_topic_or_gear_mismatch": False,
        "apollo_active_safety_stop": safety_stop,
        "trigger_too_early": trigger_too_early,
        "cut_in_has_no_terminal_condition": cut_no_terminal,
        "planned_path_admission_mismatch": admission_mismatch,
        "window_design_failure": duration == 60.0 and first_finite_elapsed is not None and first_finite_elapsed > 32.0,
        "first_production_finite_ttc_elapsed_s": first_finite_elapsed,
    }
    if summary["actor_conflict_timing_error_s"] is None:
        summary["actor_conflict_timing_error_s_missing_reason"] = "actual actor program transition was not detected"
    for key in ("planning_target_speed_median_first_10s", "control_throttle_fraction", "control_brake_fraction", "planned_path_min_separation_m", "planned_path_conflict_time_s"):
        if summary[key] is None:
            summary[f"{key}_missing_reason"] = "required Apollo message or trajectory value was not observed"
    summary["root_cause_classification"] = classify_root_cause(summary).value
    _atomic_json(args.summary, summary)
    del readers
    print(json.dumps(summary, sort_keys=True), flush=True)
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        os._exit(2)
