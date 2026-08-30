#!/usr/bin/env python3
"""Measure no-NPC Apollo-to-CARLA execution without producing dataset samples."""

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

import carla
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest, RoutingResponse


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


class ApolloState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.route_count = 0
        self.route_accepted = False
        self.planning_count = 0
        self.valid_planning_count = 0
        self.chassis_count = 0
        self.control_count = 0
        self.localization_count = 0
        self.planning = None
        self.chassis = None
        self.control = None
        self.localization = None

    def on_route(self, message: RoutingResponse) -> None:
        with self.lock:
            self.route_count += 1
            self.route_accepted = self.route_accepted or (
                message.status.error_code == 0 and len(message.road) > 0
            )

    def on_planning(self, message: ADCTrajectory) -> None:
        points = [point for point in message.trajectory_point if 0.0 <= point.relative_time <= 3.0]
        target = min(points, key=lambda point: abs(point.relative_time - 1.0)) if points else None
        valid = bool(points) and message.total_path_length > 1.0 and not message.estop.is_estop
        with self.lock:
            self.planning_count += 1
            self.valid_planning_count += int(valid)
            self.planning = {
                "header_time_s": message.header.timestamp_sec,
                "header_sequence_num": message.header.sequence_num,
                "valid": valid,
                "point_count_first_3s": len(points),
                "target_speed_1s_mps": None if target is None else target.v,
                "target_acceleration_1s_mps2": None if target is None else target.a,
                "estop": bool(message.estop.is_estop),
                "gear": int(message.gear),
                "replan_reason": message.replan_reason,
                "is_replan": bool(message.is_replan),
                "trajectory_type": int(message.trajectory_type),
            }

    def on_chassis(self, message: Chassis) -> None:
        with self.lock:
            self.chassis_count += 1
            self.chassis = {
                "header_time_s": message.header.timestamp_sec,
                "speed_mps": message.speed_mps,
                "gear_location": int(message.gear_location),
                "throttle_percentage": message.throttle_percentage,
                "brake_percentage": message.brake_percentage,
            }

    def on_control(self, message: ControlCommand) -> None:
        debug = message.debug.simple_lon_debug
        with self.lock:
            self.control_count += 1
            self.control = {
                "header_time_s": message.header.timestamp_sec,
                "header_sequence_num": message.header.sequence_num,
                "speed_mps": message.speed,
                "acceleration_mps2": message.acceleration,
                "gear_location": int(message.gear_location),
                "throttle_percentage": message.throttle,
                "brake_percentage": message.brake,
                "simple_lon_debug": {
                    key: getattr(debug, key)
                    for key in (
                        "speed_reference",
                        "speed_error",
                        "preview_speed_reference",
                        "preview_speed_error",
                        "preview_acceleration_reference",
                        "acceleration_cmd_closeloop",
                        "acceleration_cmd",
                        "acceleration_lookup",
                        "speed_lookup",
                        "calibration_value",
                        "throttle_cmd",
                        "brake_cmd",
                        "is_full_stop",
                        "is_full_stop_soft",
                        "path_remain",
                        "current_speed",
                        "acceleration_reference",
                        "current_acceleration",
                        "acceleration_error",
                        "current_steer_interval",
                        "is_wait_steer",
                        "is_stop_reason_by_destination",
                        "is_stop_reason_by_prdestrian",
                    )
                },
            }

    def on_localization(self, message: LocalizationEstimate) -> None:
        pose = message.pose
        with self.lock:
            self.localization_count += 1
            self.localization = {
                "header_time_s": message.header.timestamp_sec,
                "header_sequence_num": message.header.sequence_num,
                "linear_velocity": {
                    axis: getattr(pose.linear_velocity, axis) for axis in ("x", "y", "z")
                },
                "linear_acceleration": {
                    axis: getattr(pose.linear_acceleration, axis) for axis in ("x", "y", "z")
                },
                "linear_acceleration_vrf": {
                    axis: getattr(pose.linear_acceleration_vrf, axis) for axis in ("x", "y", "z")
                },
                "heading_rad": pose.heading,
            }

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "route_count": self.route_count,
                "route_accepted": self.route_accepted,
                "planning_count": self.planning_count,
                "valid_planning_count": self.valid_planning_count,
                "chassis_count": self.chassis_count,
                "control_count": self.control_count,
                "localization_count": self.localization_count,
                "planning": None if self.planning is None else dict(self.planning),
                "chassis": None if self.chassis is None else dict(self.chassis),
                "control_guarded": None if self.control is None else dict(self.control),
                "localization": None if self.localization is None else dict(self.localization),
            }


def _vehicle_physics(vehicle: carla.Vehicle) -> dict:
    physics = vehicle.get_physics_control()
    return {
        "type_id": vehicle.type_id,
        "attributes": dict(vehicle.attributes),
        "mass_kg": physics.mass,
        "drag_coefficient": physics.drag_coefficient,
        "max_rpm": physics.max_rpm,
        "moi": physics.moi,
        "damping_rate_full_throttle": physics.damping_rate_full_throttle,
        "damping_rate_zero_throttle_clutch_engaged": physics.damping_rate_zero_throttle_clutch_engaged,
        "damping_rate_zero_throttle_clutch_disengaged": physics.damping_rate_zero_throttle_clutch_disengaged,
        "use_gear_autobox": physics.use_gear_autobox,
        "gear_switch_time_s": physics.gear_switch_time,
        "clutch_strength": physics.clutch_strength,
        "final_ratio": physics.final_ratio,
        "torque_curve": [{"rpm": point.x, "torque_nm": point.y} for point in physics.torque_curve],
        "forward_gears": [
            {
                "ratio": gear.ratio,
                "down_ratio": gear.down_ratio,
                "up_ratio": gear.up_ratio,
            }
            for gear in physics.forward_gears
        ],
        "wheels": [
            {
                "tire_friction": wheel.tire_friction,
                "damping_rate": wheel.damping_rate,
                "max_steer_angle": wheel.max_steer_angle,
                "radius_cm": wheel.radius,
                "max_brake_torque": wheel.max_brake_torque,
                "max_handbrake_torque": wheel.max_handbrake_torque,
            }
            for wheel in physics.wheels
        ],
    }


def _gear_mismatch(row: dict) -> bool:
    control = row["apollo"]["control_guarded"]
    chassis = row["apollo"]["chassis"]
    return bool(control and chassis and control["gear_location"] == 1 and chassis["gear_location"] != 1)


def _expected_chassis_gear(row: dict) -> int:
    carla_state = row["carla"]
    if carla_state["hand_brake"]:
        return 3
    if carla_state["reverse"] or carla_state["actual_gear"] < 0:
        return 2
    if carla_state["actual_gear"] == 0:
        return 0
    return 1


def _actual_gear_feedback_mismatch(row: dict) -> bool:
    chassis = row["apollo"]["chassis"]
    return bool(chassis and chassis["gear_location"] != _expected_chassis_gear(row))


def _tracking_window(rows: list[dict]) -> dict:
    window_frames = 100
    candidates = []
    for start in range(0, max(0, len(rows) - window_frames + 1)):
        window = rows[start : start + window_frames]
        targets = [
            row["apollo"]["planning"]["target_speed_1s_mps"]
            for row in window
            if row["apollo"]["planning"] is not None
            and row["apollo"]["planning"]["target_speed_1s_mps"] is not None
        ]
        if len(targets) < 95 or median(targets) < 1.0:
            continue
        actual = [row["carla"]["speed_mps"] for row in window]
        ratio = median(actual) / median(targets)
        candidates.append(
            {
                "start_s": window[0]["sim_time_s"],
                "end_s": window[-1]["sim_time_s"],
                "target_median_mps": median(targets),
                "actual_median_mps": median(actual),
                "actual_to_target_ratio": ratio,
                "passed": ratio >= 0.70,
            }
        )
    if not candidates:
        return {"available": False, "passed": False, "reason": "no continuous 5 s target >= 1.0 m/s window"}
    return max(candidates, key=lambda item: item["actual_to_target_ratio"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-s", type=float, default=20.0)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if not args.run_id.startswith("NO_NPC_") or args.duration_s != 20.0:
        raise ValueError("only the frozen 20 s NO_NPC execution smoke is allowed")

    cyber.init("cage_d0_execution_smoke_" + args.run_id)
    node = cyber.Node("cage_d0_execution_smoke_" + args.run_id)
    state = ApolloState()
    readers = [
        node.create_reader("/apollo/routing_response", RoutingResponse, state.on_route),
        node.create_reader("/apollo/planning", ADCTrajectory, state.on_planning),
        node.create_reader("/apollo/canbus/chassis", Chassis, state.on_chassis),
        node.create_reader("/apollo/control_guarded", ControlCommand, state.on_control),
        node.create_reader("/apollo/localization/pose", LocalizationEstimate, state.on_localization),
    ]
    route_writer = node.create_writer("/apollo/routing_request", RoutingRequest, 10)

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10)
    world = client.get_world()
    if not world.get_map().name.endswith("/Town01"):
        raise RuntimeError("execution smoke requires Town01")
    world.wait_for_tick(5)
    deadline = time.monotonic() + 15.0
    ego = None
    while time.monotonic() < deadline and ego is None:
        vehicles = world.get_actors().filter("vehicle.*")
        egos = [actor for actor in vehicles if actor.attributes.get("role_name") == "ego_vehicle"]
        others = [actor for actor in vehicles if actor.attributes.get("role_name") != "ego_vehicle"]
        if len(egos) == 1 and not others:
            ego = egos[0]
            break
        world.wait_for_tick(1)
    if ego is None:
        raise RuntimeError("execution smoke requires exactly one ego and zero NPC vehicles")
    vehicle_physics = _vehicle_physics(ego)

    request = RoutingRequest()
    request.header.module_name = "cage_d0_execution_smoke"
    request.is_start_pose_set = True
    for x, y in ((202.550003, -59.330017), (288.237488, -59.330009)):
        waypoint = request.waypoint.add()
        waypoint.pose.x = x
        waypoint.pose.y = y
        waypoint.heading = 0.0
    deadline = time.monotonic() + 10.0
    next_publish = 0.0
    while time.monotonic() < deadline and not state.snapshot()["route_accepted"]:
        now = time.monotonic()
        if now >= next_publish:
            request.header.timestamp_sec = time.time()
            request.header.sequence_num += 1
            route_writer.write(request)
            next_publish = now + 0.5
        world.wait_for_tick(2)
    if not state.snapshot()["route_accepted"]:
        raise RuntimeError("execution smoke routing response was not accepted")

    first_transform = ego.get_transform()
    snapshot = world.get_snapshot()
    started_sim_s = snapshot.timestamp.elapsed_seconds
    rows = []
    frames = []
    temporary = args.trace.with_suffix(args.trace.suffix + f".tmp.{os.getpid()}")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w") as stream:
        while snapshot.timestamp.elapsed_seconds - started_sim_s < args.duration_s:
            snapshot = world.wait_for_tick(5)
            vehicles = world.get_actors().filter("vehicle.*")
            egos = [actor for actor in vehicles if actor.attributes.get("role_name") == "ego_vehicle"]
            others = [actor for actor in vehicles if actor.attributes.get("role_name") != "ego_vehicle"]
            if len(egos) != 1 or others:
                raise RuntimeError(f"actor identity changed ego={len(egos)} npc={len(others)}")
            ego = egos[0]
            transform = ego.get_transform()
            velocity = ego.get_velocity()
            acceleration = ego.get_acceleration()
            control = ego.get_control()
            forward = transform.get_forward_vector()
            longitudinal_speed = velocity.x * forward.x + velocity.y * forward.y
            longitudinal_acceleration = acceleration.x * forward.x + acceleration.y * forward.y
            apollo = state.snapshot()
            planning = apollo["planning"]
            planning_available = bool(planning and planning["valid"])
            planning_clock_match = bool(
                planning
                and abs(snapshot.timestamp.elapsed_seconds - planning["header_time_s"]) <= 0.25
            )
            row = {
                "frame": snapshot.frame,
                "sim_time_s": snapshot.timestamp.elapsed_seconds - started_sim_s,
                "carla": {
                    "x": transform.location.x,
                    "y": transform.location.y,
                    "speed_mps": math.hypot(velocity.x, velocity.y),
                    "longitudinal_speed_mps": longitudinal_speed,
                    "acceleration": {
                        "x": acceleration.x,
                        "y": acceleration.y,
                        "z": acceleration.z,
                        "magnitude_mps2": math.sqrt(
                            acceleration.x ** 2 + acceleration.y ** 2 + acceleration.z ** 2
                        ),
                        "longitudinal_mps2": longitudinal_acceleration,
                    },
                    "throttle": control.throttle,
                    "brake": control.brake,
                    "steer": control.steer,
                    "reverse": control.reverse,
                    "hand_brake": control.hand_brake,
                    "actual_gear": control.gear,
                    "actual_manual_gear_shift": control.manual_gear_shift,
                },
                "apollo": apollo,
                "valid_planning_available": planning_available,
                "planning_header_matches_carla_clock": planning_clock_match,
            }
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            rows.append(row)
            frames.append(snapshot.frame)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, args.trace)

    last_transform = ego.get_transform()
    progress = math.dist(
        (first_transform.location.x, first_transform.location.y),
        (last_transform.location.x, last_transform.location.y),
    )
    summary = {
        "schema_version": 1,
        "label": "RUNTIME_REPAIR_SMOKE_NOT_DATASET",
        "run_id": args.run_id,
        "duration_requested_s": args.duration_s,
        "trace_frames": len(rows),
        "sim_duration_s": rows[-1]["sim_time_s"] - rows[0]["sim_time_s"],
        "non_unit_frame_gaps": sum(right - left != 1 for left, right in zip(frames, frames[1:])),
        "npc_vehicle_count": 0,
        "route": {key: state.snapshot()[key] for key in ("route_count", "route_accepted")},
        "message_counts": {key: state.snapshot()[key] for key in ("planning_count", "valid_planning_count", "chassis_count", "control_count", "localization_count")},
        "vehicle_physics": vehicle_physics,
        "valid_trajectory_frame_coverage": sum(row["valid_planning_available"] for row in rows) / len(rows),
        "planning_header_carla_clock_match_fraction": sum(
            row["planning_header_matches_carla_clock"] for row in rows
        )
        / len(rows),
        "drive_gear_mismatch_frames": sum(_gear_mismatch(row) for row in rows),
        "actual_gear_feedback_mismatch_frames": sum(
            _actual_gear_feedback_mismatch(row) for row in rows
        ),
        "carla_actual_gear_zero_frames": sum(
            row["carla"]["actual_gear"] == 0 for row in rows
        ),
        "carla_actual_first_gear_one_time_s": next(
            (
                row["sim_time_s"]
                for row in rows
                if row["carla"]["actual_gear"] == 1
            ),
            None,
        ),
        "apollo_drive_but_carla_not_gear_one_frames": sum(
            bool(
                row["apollo"]["chassis"]
                and row["apollo"]["chassis"]["gear_location"] == 1
                and row["carla"]["actual_gear"] != 1
            )
            for row in rows
        ),
        "control_topic": "/apollo/control_guarded",
        "progress_m": progress,
        "speed_median_mps": median(row["carla"]["speed_mps"] for row in rows),
        "speed_max_mps": max(row["carla"]["speed_mps"] for row in rows),
        "throttle_active_fraction": sum(row["carla"]["throttle"] > 0.05 for row in rows) / len(rows),
        "brake_active_fraction": sum(row["carla"]["brake"] > 0.05 for row in rows) / len(rows),
        "tracking_window": _tracking_window(rows),
    }
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
