#!/usr/bin/env python3
"""Private protocol-v1 evaluator-side driver for one closed-loop attempt."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import threading
import time

import carla
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest, RoutingResponse

from cage_ad.protocol_v1.evaluator import OrientedBox, oriented_box_ttc
from cage_ad.protocol_v1.loader import PROTOCOL_VERSION, ProtocolValidationError, load_protocol


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _health(required_pids: dict[str, int]) -> dict[str, bool]:
    return {name: _pid_alive(int(pid)) for name, pid in required_pids.items()}


def _actor_box(actor) -> OrientedBox:
    transform = actor.get_transform()
    box = actor.bounding_box
    center = transform.transform(box.location)
    velocity = actor.get_velocity()
    heading = math.radians(transform.rotation.yaw + box.rotation.yaw)
    return OrientedBox(
        center.x,
        center.y,
        heading,
        box.extent.x * 2.0,
        box.extent.y * 2.0,
        velocity.x,
        velocity.y,
        actor.attributes.get("role_name") or actor.type_id,
    )


def _relative_impact_angle_deg(ego, other) -> float:
    ego_transform = ego.get_transform()
    forward = ego_transform.get_forward_vector()
    ego_velocity, other_velocity = ego.get_velocity(), other.get_velocity()
    relative_x = ego_velocity.x - other_velocity.x
    relative_y = ego_velocity.y - other_velocity.y
    if math.hypot(relative_x, relative_y) <= 1e-9:
        return 0.0
    dot = forward.x * relative_x + forward.y * relative_y
    cross = forward.x * relative_y - forward.y * relative_x
    return math.degrees(math.atan2(cross, dot))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opaque-run-id", required=True)
    parser.add_argument("--private-run-config", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--required-pids-json", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    args = parser.parse_args()

    # Full schema validation is done before the attempt is planned; host mode
    # verifies the same registry/schema hash without importing extra packages.
    bundle = load_protocol(args.repo_root, validate_json_schema=False)
    config = json.loads(args.private_run_config.read_text())
    if config.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolValidationError("private run protocol version mismatch")
    if config.get("protocol_bundle_sha256") != bundle.bundle_sha256:
        raise ProtocolValidationError("private run protocol hash mismatch")
    required_pids = json.loads(args.required_pids_json.read_text())
    if not isinstance(required_pids, dict) or not required_pids:
        raise ProtocolValidationError("required process PID registry is empty")
    health_at_start = _health(required_pids)
    if not all(health_at_start.values()):
        raise RuntimeError("required Apollo/CARLA processes are not healthy at attempt start")

    common = bundle.scenarios["common"]
    duration = float(common["observation_window_s"])
    start_xy = tuple(map(float, common["route_start_apollo_xy"]))
    destination_xy = tuple(map(float, common["route_end_apollo_xy"]))
    fixed_step = float(common["fixed_delta_seconds"])

    cyber.init("cage_d0_v1_run_" + args.opaque_run_id)
    node = cyber.Node("cage_d0_v1_run_" + args.opaque_run_id)
    lock = threading.RLock()
    route = {"count": 0, "success": False, "roads": 0}
    route_epoch_started = False
    messages = {"planning": 0, "planning_valid": 0, "control_guarded": 0}

    def on_route(message: RoutingResponse) -> None:
        nonlocal route_epoch_started
        with lock:
            route["count"] += 1
            route["success"] = message.status.error_code == 0
            route["roads"] = len(message.road)
            if route["success"] and route["roads"] > 0:
                route_epoch_started = True

    def on_planning(message: ADCTrajectory) -> None:
        with lock:
            if not route_epoch_started:
                return
            messages["planning"] += 1
            if len(message.trajectory_point) > 0 and message.total_path_length > 1.0:
                messages["planning_valid"] += 1

    def on_control(_message: ControlCommand) -> None:
        with lock:
            if route_epoch_started:
                messages["control_guarded"] += 1

    readers = [
        node.create_reader("/apollo/routing_response", RoutingResponse, on_route),
        node.create_reader("/apollo/planning", ADCTrajectory, on_planning),
        node.create_reader("/apollo/control_guarded", ControlCommand, on_control),
    ]
    writer = node.create_writer("/apollo/routing_request", RoutingRequest, 10)

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10)
    world = client.get_world()
    world.wait_for_tick(5)
    deadline = time.monotonic() + 15.0
    ego = interaction = None
    while time.monotonic() < deadline and (ego is None or interaction is None):
        for actor in world.get_actors().filter("vehicle.*"):
            role = actor.attributes.get("role_name")
            if role == "ego_vehicle":
                ego = actor
            elif role == "cage_interaction_actor":
                interaction = actor
        if ego is None or interaction is None:
            world.wait_for_tick(1)
    if ego is None or interaction is None:
        raise RuntimeError("D0 ego or declared interaction actor is missing")

    collisions: list[dict] = []

    def on_collision(event) -> None:
        if not route_epoch_started:
            return
        other = event.other_actor
        ego_location = ego.get_location()
        ego_velocity, other_velocity = ego.get_velocity(), other.get_velocity()
        collisions.append(
            {
                "frame": event.frame,
                "counterpart_id": other.attributes.get("role_name") or other.type_id,
                "counterpart_type": other.type_id,
                "position_m": [ego_location.x, ego_location.y],
                "angle_deg": _relative_impact_angle_deg(ego, other),
                "relative_speed_mps": math.hypot(
                    ego_velocity.x - other_velocity.x,
                    ego_velocity.y - other_velocity.y,
                ),
                "impulse": math.sqrt(
                    event.normal_impulse.x**2
                    + event.normal_impulse.y**2
                    + event.normal_impulse.z**2
                ),
            }
        )

    sensor_blueprint = world.get_blueprint_library().find("sensor.other.collision")
    sensor = world.spawn_actor(sensor_blueprint, carla.Transform(), attach_to=ego)
    sensor.listen(on_collision)

    request = RoutingRequest()
    request.header.timestamp_sec = time.time()
    request.header.module_name = "cage_d0_protocol_v1_runner"
    request.header.sequence_num = 1
    request.is_start_pose_set = True
    for x, y in (start_xy, destination_xy):
        waypoint = request.waypoint.add()
        waypoint.pose.x = x
        waypoint.pose.y = y
        waypoint.heading = 0.0
    writer.write(request)

    route_deadline = time.monotonic() + 10.0
    while time.monotonic() < route_deadline and not route_epoch_started:
        world.wait_for_tick(2)
    if not route_epoch_started:
        sensor.stop()
        sensor.destroy()
        raise RuntimeError("routing response was not accepted")

    initial = ego.get_transform()
    samples: list[dict] = []
    frames: list[int] = []
    snapshot = world.get_snapshot()
    sim_started = snapshot.timestamp.elapsed_seconds
    wall_started = time.monotonic()
    try:
        while snapshot.timestamp.elapsed_seconds - sim_started < duration:
            snapshot = world.wait_for_tick(5)
            ego_box, actor_box = _actor_box(ego), _actor_box(interaction)
            ttc = oriented_box_ttc(ego_box, actor_box)
            separation = ego.get_location().distance(interaction.get_location())
            samples.append(
                {
                    "simulator_time_s": snapshot.timestamp.elapsed_seconds - sim_started,
                    "ego_x_m": ego_box.x,
                    "ego_y_m": ego_box.y,
                    "ego_speed_mps": math.hypot(ego_box.velocity_x, ego_box.velocity_y),
                    "actor_speed_mps": math.hypot(actor_box.velocity_x, actor_box.velocity_y),
                    "center_separation_m": separation,
                    "obb_ttc_s": ttc,
                }
            )
            frames.append(snapshot.frame)
    finally:
        sensor.stop()
        sensor.destroy()
    final = ego.get_transform()
    frame_gaps = [right - left for left, right in zip(frames, frames[1:])]
    non_unit_frame_gaps = sum(gap != 1 for gap in frame_gaps)
    minimum_positive_ttc = min(
        (item["obb_ttc_s"] for item in samples if item["obb_ttc_s"] is not None and item["obb_ttc_s"] > 0.0),
        default=None,
    )
    forward_progress = math.hypot(
        final.location.x - initial.location.x,
        final.location.y - initial.location.y,
    )
    route_length = math.dist(start_xy, destination_xy)
    route_completion = min(1.0, max(0.0, forward_progress / route_length))
    health_at_end = _health(required_pids)
    with lock:
        message_snapshot = dict(messages)
        route_snapshot = dict(route)
    infrastructure = {
        "apollo_modules_healthy": all(health_at_start.values()) and all(health_at_end.values()),
        "route_accepted": route_snapshot["success"] and route_snapshot["roads"] > 0,
        "actor_spawned": interaction is not None,
        "clock_advanced": len(frames) > 1 and non_unit_frame_gaps == 0,
        "planning_messages": message_snapshot["planning"],
        "guarded_control_messages": message_snapshot["control_guarded"],
        "no_injector_exception": False,
        "non_unit_frame_gaps": non_unit_frame_gaps,
    }
    status_paths = [Path(config["interposer_stats_path"]), Path(config["scenario_stats_path"])]
    status_documents = [json.loads(path.read_text()) for path in status_paths if path.exists()]
    infrastructure["no_injector_exception"] = (
        len(status_documents) == len(status_paths)
        and all(document.get("injector_exception") is None for document in status_documents)
    )
    infrastructure_valid = (
        infrastructure["apollo_modules_healthy"]
        and infrastructure["route_accepted"]
        and infrastructure["actor_spawned"]
        and infrastructure["clock_advanced"]
        and infrastructure["planning_messages"] >= 20
        and infrastructure["guarded_control_messages"] >= 20
        and infrastructure["no_injector_exception"]
    )
    collision = collisions[0] if collisions else None
    metrics = {
        "schema_version": 2,
        "protocol_version": PROTOCOL_VERSION,
        "opaque_run_id": args.opaque_run_id,
        "infrastructure_valid": infrastructure_valid,
        "infrastructure_outcome": infrastructure,
        "safety_outcome": {
            "collision_count": len(collisions),
            "minimum_ttc_s": minimum_positive_ttc,
            "collision_object_id": None if collision is None else collision["counterpart_id"],
            "collision_position_m": None if collision is None else collision["position_m"],
            "collision_angle_deg": None if collision is None else collision["angle_deg"],
            "collision_relative_speed_mps": None if collision is None else collision["relative_speed_mps"],
            "collisions": collisions,
        },
        "task_outcome": {
            "route_completion": route_completion,
            "forward_progress_m": forward_progress,
            "timeout": route_completion < 1.0,
        },
        "runtime": {
            "route": route_snapshot,
            "messages": message_snapshot,
            "health_at_start": health_at_start,
            "health_at_end": health_at_end,
            "wall_seconds": time.monotonic() - wall_started,
            "simulation_seconds": snapshot.timestamp.elapsed_seconds - sim_started,
            "frames": len(frames),
            "non_unit_frame_gaps": non_unit_frame_gaps,
        },
        "samples": samples,
    }
    atomic_json(args.private_output, metrics)
    del readers
    os._exit(0 if infrastructure_valid else 2)


if __name__ == "__main__":
    main()
