#!/usr/bin/env python3
"""Publish a stock Town01 obstacle stream and verify Apollo 10 Prediction output."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
import time
import re

from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import (
    PerceptionObstacle,
    PerceptionObstacles,
)
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles

from cage_ad.adapters.apollo_d0.prediction_semantic_slot import (
    contains_forbidden_visible_term,
    evaluate_prediction_smoke,
    prediction_message_to_slot,
)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--rate-hz", type=float, default=20.0)
    parser.add_argument("--stack-log", type=Path, required=True)
    args = parser.parse_args()
    if args.duration <= 0 or args.rate_hz <= 0:
        raise ValueError("duration and rate must be positive")

    target_id = 1001
    lock = threading.RLock()
    slots: list[dict] = []
    output_timestamps: list[float] = []
    input_timestamps: list[float] = []
    target_source_timestamps: list[float] = []
    observed_ids: list[int] = []
    target_output_count = 0
    target_trajectory_count = 0
    target_frames_with_trajectory = 0
    probabilities_in_range = True

    cyber.init("cage_pr826_stock_prediction_smoke")
    node = cyber.Node("cage_pr826_stock_prediction_smoke")
    clock_writer = node.create_writer("/clock", Clock, 10)
    perception_writer = node.create_writer(
        "/apollo/perception/obstacles", PerceptionObstacles, 10
    )
    localization_writer = node.create_writer(
        "/apollo/localization/pose", LocalizationEstimate, 10
    )

    def on_prediction(message: PredictionObstacles) -> None:
        nonlocal target_output_count, target_trajectory_count, target_frames_with_trajectory, probabilities_in_range
        slot = prediction_message_to_slot(message, target_obstacle_id=target_id)
        with lock:
            output_timestamps.append(slot["timestamp_sec"])
            for actor in slot["actors"]:
                observed_ids.append(actor["obstacle_id"])
                if actor["is_target"]:
                    target_output_count += 1
                    target_trajectory_count += len(actor["trajectories"])
                    target_frames_with_trajectory += int(bool(actor["trajectories"]))
                    target_source_timestamps.append(actor["source_timestamp_sec"])
                for trajectory in actor["trajectories"]:
                    probability = trajectory["probability"]
                    probabilities_in_range = probabilities_in_range and 0.0 <= probability <= 1.0
            if len(slots) < 3:
                slots.append(slot)

    reader = node.create_reader("/apollo/prediction", PredictionObstacles, on_prediction)
    interval = 1.0 / args.rate_hz
    started = time.monotonic()
    next_tick = started
    sequence = 0
    sim_origin = 1000.0
    while time.monotonic() - started < args.duration:
        now = time.monotonic()
        if now < next_tick:
            time.sleep(min(next_tick - now, 0.01))
            continue
        elapsed = now - started
        timestamp = sim_origin + elapsed
        input_timestamps.append(timestamp)

        clock = Clock()
        clock.clock = int(timestamp * 1_000_000_000)
        clock_writer.write(clock)

        localization = LocalizationEstimate()
        localization.header.timestamp_sec = timestamp
        localization.header.module_name = "stock_prediction_smoke_adapter"
        localization.header.sequence_num = sequence
        localization.pose.position.x = 202.550003
        localization.pose.position.y = -59.330017
        localization.pose.position.z = 0.0
        localization.pose.heading = 0.0
        localization.pose.linear_velocity.x = 0.0
        localization.pose.linear_velocity.y = 0.0
        localization.pose.linear_velocity.z = 1e-9
        localization_writer.write(localization)

        perception = PerceptionObstacles()
        perception.header.timestamp_sec = timestamp
        perception.header.module_name = "stock_prediction_smoke_adapter"
        perception.header.sequence_num = sequence
        obstacle = perception.perception_obstacle.add()
        obstacle.id = target_id
        obstacle.position.x = 230.0 + 2.0 * elapsed
        obstacle.position.y = -59.33001
        obstacle.position.z = 0.0
        obstacle.theta = 0.0
        obstacle.velocity.x = 2.0
        obstacle.velocity.y = 0.0
        # Apollo's Point3D proto defaults an absent z to NaN. Use an explicit,
        # finite near-zero value that survives cross-language serialization.
        obstacle.velocity.z = 1e-9
        obstacle.length = 4.7
        obstacle.width = 2.0
        obstacle.height = 1.6
        obstacle.type = PerceptionObstacle.VEHICLE
        obstacle.timestamp = timestamp
        obstacle.tracking_time = elapsed
        obstacle.confidence = 1.0
        for delta_x, delta_y in ((2.35, 1.0), (2.35, -1.0), (-2.35, -1.0), (-2.35, 1.0)):
            corner = obstacle.polygon_point.add()
            corner.x = obstacle.position.x + delta_x
            corner.y = obstacle.position.y + delta_y
            corner.z = obstacle.position.z
        perception_writer.write(perception)
        sequence += 1
        next_tick += interval

    time.sleep(1.0)
    stack_text = args.stack_log.read_text(errors="replace") if args.stack_log.exists() else ""
    critical_patterns = re.compile(
        r"cannot receive any localization|no polygon points in feature|found nan velocity",
        re.IGNORECASE,
    )
    critical_input_error_count = len(critical_patterns.findall(stack_text))
    with lock:
        monotonic = all(
            right >= left for left, right in zip(output_timestamps, output_timestamps[1:])
        )
        source_monotonic = all(
            right >= left
            for left, right in zip(target_source_timestamps, target_source_timestamps[1:])
        )
        source_matches_input = all(
            any(abs(source - candidate) <= 1e-6 for candidate in input_timestamps)
            for source in target_source_timestamps
        )
        evaluation = evaluate_prediction_smoke(
            input_count=sequence,
            output_count=len(output_timestamps),
            target_output_count=target_output_count,
            target_trajectory_count=target_trajectory_count,
            target_frames_with_trajectory=target_frames_with_trajectory,
            timestamps_monotonic=monotonic,
            source_timestamps_monotonic=source_monotonic,
            source_timestamps_match_input=source_matches_input,
            probabilities_in_range=probabilities_in_range,
            observed_ids=observed_ids,
            critical_input_error_count=critical_input_error_count,
        )
        result = {
            "schema_version": 1,
            "run_kind": "stock_prediction_bringup",
            "native_input_channel": "/apollo/perception/obstacles",
            "native_output_channel": "/apollo/prediction",
            "target_obstacle_id": target_id,
            "duration_sec": args.duration,
            "rate_hz": args.rate_hz,
            "input_count": sequence,
            "output_count": len(output_timestamps),
            "target_output_count": target_output_count,
            "target_trajectory_count": target_trajectory_count,
            "target_frames_with_trajectory": target_frames_with_trajectory,
            "output_coverage": len(output_timestamps) / sequence if sequence else 0.0,
            "target_trajectory_frame_coverage": (
                target_frames_with_trajectory / target_output_count
                if target_output_count
                else 0.0
            ),
            "critical_input_error_count": critical_input_error_count,
            "observed_ids": sorted(set(observed_ids)),
            "sample_slots": slots,
            **evaluation,
        }
        result["visible_leakage_scan_passed"] = not contains_forbidden_visible_term(result)
        result["passed"] = result["passed"] and result["visible_leakage_scan_passed"]
    atomic_json(args.output, result)
    del reader
    cyber.shutdown()
    print(json.dumps({key: result[key] for key in ("passed", "input_count", "output_count", "target_trajectory_count")}, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
