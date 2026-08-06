#!/usr/bin/env python3
"""Evaluator-side closed-loop driver for one linked nominal/fault/probe run."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import time

import carla
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest, RoutingResponse


START = (202.550003, -59.330017)
DESTINATION = (288.237488, -59.330009)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration", type=float, default=22.0)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()

    cyber.init("cage_d0_run_" + args.run_id)
    node = cyber.Node("cage_d0_run_" + args.run_id)
    route = {"count": 0, "success": False, "roads": 0}
    messages = {
        "planning": 0,
        "planning_valid": 0,
        "control_guarded": 0,
        "positive_throttle": 0,
    }

    def on_route(message: RoutingResponse) -> None:
        route["count"] += 1
        route["success"] = message.status.error_code == 0
        route["roads"] = len(message.road)

    def on_planning(message: ADCTrajectory) -> None:
        messages["planning"] += 1
        if len(message.trajectory_point) > 0 and message.total_path_length > 1.0:
            messages["planning_valid"] += 1

    def on_control(message: ControlCommand) -> None:
        messages["control_guarded"] += 1
        messages["positive_throttle"] += message.throttle > 0.0

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
    deadline = time.monotonic() + 10
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
        raise RuntimeError("D0 ego or interaction actor is missing")

    collisions: list[dict] = []
    blueprint = world.get_blueprint_library().find("sensor.other.collision")
    sensor = world.spawn_actor(blueprint, carla.Transform(), attach_to=ego)
    sensor.listen(
        lambda event: collisions.append(
            {
                "frame": event.frame,
                "other_type": event.other_actor.type_id,
                "impulse": math.sqrt(
                    event.normal_impulse.x**2
                    + event.normal_impulse.y**2
                    + event.normal_impulse.z**2
                ),
            }
        )
    )

    time.sleep(2)
    request = RoutingRequest()
    request.header.timestamp_sec = time.time()
    request.header.module_name = "cage_d0_runner"
    request.header.sequence_num = 1
    request.is_start_pose_set = True
    for x, y in (START, DESTINATION):
        waypoint = request.waypoint.add()
        waypoint.pose.x = x
        waypoint.pose.y = y
        waypoint.heading = 0
    writer.write(request)

    initial = ego.get_transform()
    samples = []
    frames = []
    started = time.monotonic()
    snapshot = world.get_snapshot()
    sim_started = snapshot.timestamp.elapsed_seconds
    while time.monotonic() - started < args.duration:
        snapshot = world.wait_for_tick(2)
        ego_location = ego.get_location()
        actor_location = interaction.get_location()
        ego_velocity = ego.get_velocity()
        actor_velocity = interaction.get_velocity()
        separation = ego_location.distance(actor_location)
        relative_x = actor_location.x - ego_location.x
        closing_speed = ego_velocity.x - actor_velocity.x
        ttc = relative_x / closing_speed if relative_x > 0 and closing_speed > 0.05 else None
        samples.append(
            {
                "t": round(time.monotonic() - started, 3),
                "ego_speed_mps": round(math.hypot(ego_velocity.x, ego_velocity.y), 6),
                "actor_speed_mps": round(math.hypot(actor_velocity.x, actor_velocity.y), 6),
                "separation_m": round(separation, 6),
                "ttc_s": None if ttc is None else round(ttc, 6),
            }
        )
        frames.append(snapshot.frame)
    final = ego.get_transform()
    sensor.stop()
    sensor.destroy()
    frame_gaps = [right - left for left, right in zip(frames, frames[1:])]
    criteria = {
        "route_success": route["success"] and route["roads"] > 0,
        "planning_valid": messages["planning_valid"] >= 20,
        "control_reached_bridge": messages["control_guarded"] >= 20,
        "motion": max(item["ego_speed_mps"] for item in samples) >= 0.5
        and final.location.x - initial.location.x >= 5.0,
        "timing": sum(gap != 1 for gap in frame_gaps) == 0,
    }
    runtime_criteria = {
        key: criteria[key]
        for key in ("route_success", "planning_valid", "control_reached_bridge", "timing")
    }
    metrics = {
        "schema_version": 1,
        "run_id": args.run_id,
        "route": route,
        "messages": messages,
        "criteria": criteria,
        "runtime_criteria": runtime_criteria,
        "result": "PASS" if all(runtime_criteria.values()) else "FAIL",
        "collision_count": len(collisions),
        "collisions": collisions,
        "minimum_separation_m": min(item["separation_m"] for item in samples),
        "minimum_positive_ttc_s": min(
            (item["ttc_s"] for item in samples if item["ttc_s"] is not None), default=None
        ),
        "maximum_ego_speed_mps": max(item["ego_speed_mps"] for item in samples),
        "final_ego_speed_mps": samples[-1]["ego_speed_mps"],
        "forward_progress_m": final.location.x - initial.location.x,
        "wall_seconds": time.monotonic() - started,
        "simulation_seconds": snapshot.timestamp.elapsed_seconds - sim_started,
        "frames": len(frames),
        "non_unit_frame_gaps": sum(gap != 1 for gap in frame_gaps),
        "samples": samples,
    }
    atomic_json(args.private_output, metrics)
    del readers
    os._exit(0 if metrics["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
