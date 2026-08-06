#!/usr/bin/env python3
"""Execute one A2 fault -> O1 query -> I2 intervention chain."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import threading
import time

import carla
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest, RoutingResponse


START = (202.550003, -59.330017)
DESTINATION = (288.237488, -59.330009)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_time(samples: list[dict], field: str, threshold: float, after=0.0):
    for sample in samples:
        if sample["t"] >= after and float(sample[field]) >= threshold:
            return float(sample["t"])
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--visible-dir", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--diagnosis-python", type=Path, required=True)
    parser.add_argument("--diagnosis-script", type=Path, required=True)
    parser.add_argument("--query-after", type=float, default=15.0)
    parser.add_argument("--post-action", type=float, default=8.0)
    args = parser.parse_args()
    args.visible_dir.mkdir(parents=True, exist_ok=True)
    query_path = args.visible_dir / "o1_tracking_window.json"
    action_path = args.visible_dir / "i2_action.json"

    cyber.init("a2_chain_" + args.run_id)
    node = cyber.Node("a2_chain_" + args.run_id)
    lock = threading.Lock()
    started_at = [None]
    action_at = [None]
    desired: list[dict] = []
    response: list[dict] = []
    planning = {"count": 0, "valid": 0}
    route = {"count": 0, "success": False, "roads": 0}
    frames: list[int] = []

    def relative_time() -> float:
        return 0.0 if started_at[0] is None else time.monotonic() - started_at[0]

    def on_control(message: ControlCommand) -> None:
        if started_at[0] is None:
            return
        with lock:
            desired.append(
                {
                    "t": round(relative_time(), 6),
                    "throttle_pct": round(message.throttle, 6),
                    "brake_pct": round(message.brake, 6),
                    "steering_pct": round(message.steering_target, 6),
                }
            )

    def on_chassis(message: Chassis) -> None:
        if started_at[0] is None:
            return
        with lock:
            response.append(
                {
                    "t": round(relative_time(), 6),
                    "speed_mps": round(message.speed_mps, 6),
                    "throttle_pct": round(message.throttle_percentage, 6),
                    "brake_pct": round(message.brake_percentage, 6),
                    "steering_pct": round(message.steering_percentage, 6),
                }
            )

    def on_planning(message: ADCTrajectory) -> None:
        if started_at[0] is None:
            return
        planning["count"] += 1
        planning["valid"] += len(message.trajectory_point) > 0 and message.total_path_length > 1.0

    def on_route(message: RoutingResponse) -> None:
        route["count"] += 1
        route["success"] = message.status.error_code == 0
        route["roads"] = len(message.road)

    readers = [
        node.create_reader("/apollo/control", ControlCommand, on_control),
        node.create_reader("/apollo/canbus/chassis", Chassis, on_chassis),
        node.create_reader("/apollo/planning", ADCTrajectory, on_planning),
        node.create_reader("/apollo/routing_response", RoutingResponse, on_route),
    ]
    route_writer = node.create_writer("/apollo/routing_request", RoutingRequest, 10)
    probe_writer = node.create_writer(
        "/apollo/guardian/control_probe", ControlCommand, 10
    )

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    snapshot = world.wait_for_tick(5.0)
    ego_candidates = [
        actor
        for actor in world.get_actors().filter("vehicle.*")
        if actor.attributes.get("role_name") == "ego_vehicle"
    ]
    if len(ego_candidates) != 1:
        raise RuntimeError(f"expected one ego vehicle, found {len(ego_candidates)}")
    ego = ego_candidates[0]
    time.sleep(2.0)
    request = RoutingRequest()
    request.header.timestamp_sec = time.time()
    request.header.module_name = "a2_" + args.run_id
    request.header.sequence_num = int(args.run_id)
    request.is_start_pose_set = True
    for x, y in (START, DESTINATION):
        waypoint = request.waypoint.add()
        waypoint.pose.x = x
        waypoint.pose.y = y
        waypoint.heading = 0.0
    initial = ego.get_transform()
    started_at[0] = time.monotonic()
    sim_start = snapshot.timestamp.elapsed_seconds
    tick_callback_id = world.on_tick(lambda tick: frames.append(tick.frame))
    route_writer.write(request)

    speeds = []
    while relative_time() < args.query_after:
        snapshot = world.wait_for_tick(2.0)
        velocity = ego.get_velocity()
        speeds.append(math.hypot(velocity.x, velocity.y))

    with lock:
        query = {
            "schema_version": "semantic_window_v0",
            "scenario_id": "g0a2_" + args.run_id.zfill(6),
            "stack": "apollo_10",
            "semantic_slot": "tracking_execution",
            "required_regime": "L1",
            "window": {"start_seconds": 0.0, "end_seconds": relative_time()},
            "provenance": "apollo_semantic_adapter",
            "native_topics_disclosed": False,
            "oracle_fields_present": False,
            "control_target": list(desired),
            "vehicle_response": list(response),
        }
    atomic_json(query_path, query)
    os.chown(query_path, 1001, 1001)
    os.chmod(query_path, 0o440)
    diagnosis_started = time.monotonic()
    completed = subprocess.run(
        [
            "setpriv",
            "--reuid=1001",
            "--regid=1001",
            "--clear-groups",
            str(args.diagnosis_python),
            str(args.diagnosis_script),
            "--input",
            str(query_path),
            "--output",
            str(action_path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    diagnosis_runtime = time.monotonic() - diagnosis_started
    if completed.returncode != 0:
        raise RuntimeError(
            f"isolated diagnosis failed rc={completed.returncode}: {completed.stderr}"
        )
    action = json.loads(action_path.read_text())
    replacement = action["replacement"]
    if replacement.get("uses_ground_truth") is not False:
        raise RuntimeError("intervention is not declared non-GT")
    if action.get("semantic_slot") != "control_target":
        raise RuntimeError("unexpected intervention semantic slot")

    probe = ControlCommand()
    probe.header.timestamp_sec = time.time()
    probe.header.module_name = "guardian_semantic_probe"
    probe.throttle = float(replacement["throttle_pct"])
    probe.brake = float(replacement["brake_pct"])
    probe.steering_target = float(replacement["steering_pct"])
    action_at[0] = relative_time()
    probe_writer.write(probe)

    end_time = action_at[0] + args.post_action
    while relative_time() < end_time:
        snapshot = world.wait_for_tick(2.0)
        velocity = ego.get_velocity()
        speeds.append(math.hypot(velocity.x, velocity.y))

    with lock:
        desired_copy = list(desired)
        response_copy = list(response)
    desired_onset = first_time(query["control_target"], "throttle_pct", 1.0)
    applied_onset = first_time(query["vehicle_response"], "throttle_pct", 1.0)
    observed_lag = (
        None
        if desired_onset is None or applied_onset is None
        else applied_onset - desired_onset
    )
    brake_applied = first_time(
        response_copy, "brake_pct", 50.0, after=action_at[0]
    )
    intervention_latency = (
        None if brake_applied is None else brake_applied - action_at[0]
    )
    final = ego.get_transform()
    wall_duration = relative_time()
    sim_duration = snapshot.timestamp.elapsed_seconds - sim_start
    frame_gaps = [b - a for a, b in zip(frames, frames[1:])]
    criteria = {
        "route_success": route["success"] and route["roads"] > 0,
        "planning_live": planning["valid"] >= 20,
        "fault_effect_observed": observed_lag is not None and observed_lag >= 1.5,
        "l1_query_succeeded": action["diagnosis"]["prediction_set"]
        == ["tracking_and_execution"],
        "non_gt_intervention": replacement["uses_ground_truth"] is False,
        "intervention_effect_observed": intervention_latency is not None
        and intervention_latency <= 0.5,
        "closed_loop_motion": max(speeds, default=0.0) >= 0.3,
        "timing": 0.8 <= sim_duration / wall_duration <= 1.2
        and sum(gap != 1 for gap in frame_gaps) == 0,
    }
    result = {
        "schema_version": "a2_run_result_v0",
        "run_id": args.run_id,
        "scenario_id": query["scenario_id"],
        "result": "PASS" if all(criteria.values()) else "FAIL",
        "criteria": criteria,
        "route": route,
        "planning": planning,
        "observed": {
            "desired_throttle_onset_seconds": desired_onset,
            "applied_throttle_onset_seconds": applied_onset,
            "control_target_response_lag_seconds": observed_lag,
            "intervention_issued_seconds": action_at[0],
            "probe_brake_applied_seconds": brake_applied,
            "intervention_apply_latency_seconds": intervention_latency,
            "max_speed_mps": max(speeds, default=0.0),
            "mean_speed_mps": statistics.fmean(speeds) if speeds else 0.0,
            "forward_progress_m": final.location.x - initial.location.x,
        },
        "timing": {
            "wall_seconds": wall_duration,
            "simulation_seconds": sim_duration,
            "sim_wall_ratio": sim_duration / wall_duration,
            "frames": len(frames),
            "non_unit_frame_gaps": sum(gap != 1 for gap in frame_gaps),
        },
        "verified_observation": {
            "action_id": "query_tracking_execution_window_001",
            "stack": "apollo_10",
            "semantic_slot": "tracking_execution",
            "evidence_id": action["evidence"][0]["evidence_id"],
            "provenance": "apollo_semantic_adapter",
            "tool_success": True,
            "side_effects": [],
            "measured_cost": {
                **action["measured_query_cost"],
                "runtime_seconds_parent": diagnosis_runtime,
            },
            "payload_ref": query_path.name,
            "payload_sha256": digest(query_path),
        },
        "verified_intervention": {
            "action_id": action["action_id"],
            "semantic_slot": "control_target",
            "tool_success": intervention_latency is not None,
            "uses_ground_truth": False,
            "side_effects": [
                "temporarily replaces downstream control targets",
                "clears queued stale control targets",
                "commands a two-second braking pulse",
            ],
            "measured_cost": {
                "access_level": "L1+R2",
                "bytes": action_path.stat().st_size,
                "runtime_seconds": replacement["duration_seconds"],
                "interventions": 1,
                "human_minutes": 0,
                "risk": 2,
            },
            "payload_ref": action_path.name,
            "payload_sha256": digest(action_path),
        },
        "oracle_visible_to_diagnosis": False,
    }
    atomic_json(args.result, result)
    print(json.dumps(result, sort_keys=True), flush=True)
    world.remove_on_tick(tick_callback_id)
    del readers
    os._exit(0 if result["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
