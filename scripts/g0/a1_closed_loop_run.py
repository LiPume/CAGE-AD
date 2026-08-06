#!/usr/bin/env python3
"""Run and evaluate one deterministic Apollo-CARLA A1 closed-loop trial."""

import argparse
import json
import math
import os
import statistics
import time
from pathlib import Path

import carla
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import (
    PerceptionObstacles,
)
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import (
    PredictionObstacles,
)
from modules.common_msgs.routing_msgs.routing_pb2 import (
    RoutingRequest,
    RoutingResponse,
)


START = (202.550003, -59.330017)
DESTINATION = (288.237488, -59.330009)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=45.0)
    args = parser.parse_args()

    cyber.init("a1_closed_loop_" + args.run_id)
    node = cyber.Node("a1_closed_loop_" + args.run_id)
    sent_at = [None]
    route = {"count": 0, "success": False, "latency_sec": None, "roads": 0}
    counters = {
        "planning": 0,
        "planning_valid": 0,
        "control": 0,
        "control_throttle_positive": 0,
        "control_brake_positive": 0,
        "perception": 0,
        "prediction": 0,
    }

    def on_route(message):
        route["count"] += 1
        route["success"] = message.status.error_code == 0
        route["roads"] = len(message.road)
        route["response_module"] = message.header.module_name
        route["request_module"] = message.routing_request.header.module_name
        if sent_at[0] is not None and route["latency_sec"] is None:
            route["latency_sec"] = time.monotonic() - sent_at[0]

    def on_planning(message):
        if sent_at[0] is None:
            return
        counters["planning"] += 1
        if len(message.trajectory_point) > 0 and message.total_path_length > 1.0:
            counters["planning_valid"] += 1

    def on_control(message):
        if sent_at[0] is None:
            return
        counters["control"] += 1
        counters["control_throttle_positive"] += message.throttle > 0.0
        counters["control_brake_positive"] += message.brake > 0.0

    def on_perception(_message):
        if sent_at[0] is not None:
            counters["perception"] += 1

    def on_prediction(_message):
        if sent_at[0] is not None:
            counters["prediction"] += 1

    readers = [
        node.create_reader("/apollo/routing_response", RoutingResponse, on_route),
        node.create_reader("/apollo/planning", ADCTrajectory, on_planning),
        node.create_reader("/apollo/control", ControlCommand, on_control),
        node.create_reader(
            "/apollo/perception/obstacles", PerceptionObstacles, on_perception
        ),
        node.create_reader("/apollo/prediction", PredictionObstacles, on_prediction),
    ]
    writer = node.create_writer("/apollo/routing_request", RoutingRequest, 10)

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    snapshot = world.wait_for_tick(5.0)
    ego = [
        actor
        for actor in world.get_actors().filter("vehicle.*")
        if actor.attributes.get("role_name") == "ego_vehicle"
    ]
    if len(ego) != 1:
        raise RuntimeError(f"expected one ego vehicle, found {len(ego)}")
    ego = ego[0]

    time.sleep(2.0)
    request = RoutingRequest()
    request.header.timestamp_sec = time.time()
    request.header.module_name = "a1_" + args.run_id
    request.header.sequence_num = int(args.run_id)
    request.is_start_pose_set = True
    for x, y in (START, DESTINATION):
        waypoint = request.waypoint.add()
        waypoint.pose.x = x
        waypoint.pose.y = y
        waypoint.heading = 0.0
    sent_at[0] = time.monotonic()
    writer.write(request)

    initial = ego.get_transform()
    wall_start = time.monotonic()
    sim_start = snapshot.timestamp.elapsed_seconds
    positions = []
    speeds = []
    frame_ids = []
    while time.monotonic() - wall_start < args.duration:
        snapshot = world.wait_for_tick(2.0)
        transform = ego.get_transform()
        velocity = ego.get_velocity()
        positions.append((transform.location.x, transform.location.y))
        speeds.append(math.hypot(velocity.x, velocity.y))
        frame_ids.append(snapshot.frame)

    final = ego.get_transform()
    wall_duration = time.monotonic() - wall_start
    sim_duration = snapshot.timestamp.elapsed_seconds - sim_start
    frame_gaps = [b - a for a, b in zip(frame_ids, frame_ids[1:])]
    planning_ratio = (
        counters["planning_valid"] / counters["planning"]
        if counters["planning"]
        else 0.0
    )
    displacement = math.hypot(
        final.location.x - initial.location.x,
        final.location.y - initial.location.y,
    )
    result = {
        "schema_version": 1,
        "run_id": args.run_id,
        "result": "PENDING",
        "map": world.get_map().name,
        "fixed_delta_seconds": world.get_settings().fixed_delta_seconds,
        "wall_duration_sec": wall_duration,
        "sim_duration_sec": sim_duration,
        "sim_wall_ratio": sim_duration / wall_duration,
        "route": route,
        "messages": counters,
        "planning_valid_ratio": planning_ratio,
        "initial_carla": {
            "x": initial.location.x,
            "y": initial.location.y,
            "yaw_deg": initial.rotation.yaw,
        },
        "final_carla": {
            "x": final.location.x,
            "y": final.location.y,
            "yaw_deg": final.rotation.yaw,
        },
        "displacement_m": displacement,
        "forward_progress_m": final.location.x - initial.location.x,
        "max_lateral_error_from_start_m": max(
            abs(y - initial.location.y) for _, y in positions
        ),
        "speed_mps": {
            "max": max(speeds),
            "mean": statistics.fmean(speeds),
            "final": speeds[-1],
        },
        "frames": {
            "count": len(frame_ids),
            "first": frame_ids[0],
            "last": frame_ids[-1],
            "non_unit_gaps": sum(gap != 1 for gap in frame_gaps),
        },
        "oracle_inputs_to_adapter": False,
        "criteria": {
            "route_success": route["success"] and route["roads"] > 0,
            "planning_valid": counters["planning_valid"] >= 20
            and planning_ratio >= 0.80,
            "control_reached_carla": counters["control_throttle_positive"] > 0,
            "motion": displacement >= 5.0 and max(speeds) >= 0.5,
            "lane_stability": max(abs(y - initial.location.y) for _, y in positions)
            < 2.0,
            "timing": 0.8 <= sim_duration / wall_duration <= 1.2
            and sum(gap != 1 for gap in frame_gaps) == 0,
            "semantic_heartbeat": counters["perception"] >= 20
            and counters["prediction"] >= 20,
        },
    }
    result["result"] = (
        "PASS" if all(result["criteria"].values()) else "FAIL"
    )
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True), flush=True)
    del readers
    os._exit(0 if result["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
