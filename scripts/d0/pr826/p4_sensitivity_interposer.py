#!/usr/bin/env python3
"""Private non-admission Prediction-to-Planning semantic sensitivity interposer."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import threading

from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingResponse


SEMANTICS = {"S0_STRAIGHT", "S1_LEFT_MERGE_OCCUPANCY", "S2_NO_TRAJECTORY"}


def sha256_message(message) -> str:
    return hashlib.sha256(message.SerializeToString()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def target_obstacles(message: PredictionObstacles, target_id: int):
    return [
        obstacle
        for obstacle in message.prediction_obstacle
        if obstacle.HasField("perception_obstacle")
        and obstacle.perception_obstacle.id == target_id
    ]


def preservation_snapshot(message: PredictionObstacles, target_id: int) -> dict:
    targets = target_obstacles(message, target_id)
    non_targets = [
        sha256_message(obstacle)
        for obstacle in message.prediction_obstacle
        if not obstacle.HasField("perception_obstacle")
        or obstacle.perception_obstacle.id != target_id
    ]
    target_rows = []
    for target in targets:
        target_rows.append(
            {
                "perception_sha256": sha256_message(target.perception_obstacle),
                "timestamp": target.timestamp if target.HasField("timestamp") else None,
                "predicted_period": (
                    target.predicted_period if target.HasField("predicted_period") else None
                ),
                "is_static": target.is_static,
                "trajectory_count": len(target.trajectory),
                "probabilities": [trajectory.probability for trajectory in target.trajectory],
                "points": [
                    [
                        [point.relative_time, point.v, point.a]
                        for point in trajectory.trajectory_point
                    ]
                    for trajectory in target.trajectory
                ],
            }
        )
    return {
        "header_sha256": sha256_message(message.header),
        "obstacle_count": len(message.prediction_obstacle),
        "non_target_sha256": non_targets,
        "targets": target_rows,
    }


def transform_left_merge(
    message: PredictionObstacles,
    target_id: int,
    lateral_offset_m: float,
    relative_start_s: float,
    relative_end_s: float,
) -> dict:
    if not 0.0 <= relative_start_s < relative_end_s:
        raise ValueError("invalid relative merge window")
    targets = target_obstacles(message, target_id)
    if len(targets) != 1:
        raise ValueError(f"expected exactly one target {target_id}, observed {len(targets)}")
    target = targets[0]
    if not target.trajectory:
        raise ValueError("S1 target has no trajectory")
    endpoint_deltas = []
    transformed_points = 0
    for trajectory in target.trajectory:
        if len(trajectory.trajectory_point) < 2:
            raise ValueError("S1 trajectory has fewer than two points")
        original_xy = [
            (point.path_point.x, point.path_point.y)
            for point in trajectory.trajectory_point
        ]
        for point in trajectory.trajectory_point:
            fraction = smoothstep(
                (point.relative_time - relative_start_s)
                / (relative_end_s - relative_start_s)
            )
            offset = lateral_offset_m * fraction
            theta = point.path_point.theta
            point.path_point.x -= math.sin(theta) * offset
            point.path_point.y += math.cos(theta) * offset
            transformed_points += 1
        points = trajectory.trajectory_point
        for index, point in enumerate(points):
            if index + 1 < len(points):
                dx = points[index + 1].path_point.x - point.path_point.x
                dy = points[index + 1].path_point.y - point.path_point.y
            else:
                dx = point.path_point.x - points[index - 1].path_point.x
                dy = point.path_point.y - points[index - 1].path_point.y
            if math.hypot(dx, dy) > 1e-9:
                point.path_point.theta = math.atan2(dy, dx)
        endpoint_deltas.append(
            math.hypot(
                points[-1].path_point.x - original_xy[-1][0],
                points[-1].path_point.y - original_xy[-1][1],
            )
        )
    return {
        "trajectory_count": len(target.trajectory),
        "transformed_points": transformed_points,
        "endpoint_delta_m_min": min(endpoint_deltas),
        "endpoint_delta_m_max": max(endpoint_deltas),
    }


def clear_target_trajectories(message: PredictionObstacles, target_id: int) -> dict:
    targets = target_obstacles(message, target_id)
    if len(targets) != 1:
        raise ValueError(f"expected exactly one target {target_id}, observed {len(targets)}")
    removed = len(targets[0].trajectory)
    del targets[0].trajectory[:]
    return {"removed_trajectories": removed}


class SensitivityInterposer:
    def __init__(self, config: dict, telemetry_path: Path, stats_path: Path) -> None:
        semantic = config.get("semantic")
        if semantic not in SEMANTICS:
            raise ValueError(f"unsupported sensitivity semantic: {semantic}")
        if config.get("classification") != "NON_ADMISSION_CAUSAL_SENSITIVITY_PROBE":
            raise ValueError("missing non-admission classification")
        self.config = config
        self.semantic = semantic
        self.target_id = int(config["target_obstacle_id"])
        self.active_window = tuple(map(float, config["active_elapsed_s"]))
        if not 0.0 <= self.active_window[0] < self.active_window[1]:
            raise ValueError("invalid active window")
        self.telemetry_path = telemetry_path
        self.stats_path = stats_path
        self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        self.telemetry = self.telemetry_path.open("a", encoding="utf-8")
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.sim_time = None
        self.route_epoch = None
        self.exception = None
        self.counters = {
            "raw_messages": 0,
            "output_messages": 0,
            "active_messages": 0,
            "active_target_messages": 0,
            "transformed_messages": 0,
            "identity_mismatches": 0,
            "preservation_mismatches": 0,
            "missing_target_messages": 0,
        }
        self.endpoint_delta_min = math.inf
        self.endpoint_delta_max = -math.inf
        cyber.init("cage_pr826_p4_sensitivity_interposer")
        self.node = cyber.Node("cage_pr826_p4_sensitivity_interposer")
        self.writer = self.node.create_writer(
            "/apollo/prediction", PredictionObstacles, 10
        )
        self.readers = [
            self.node.create_reader("/clock", Clock, self.on_clock),
            self.node.create_reader(
                "/apollo/routing_response", RoutingResponse, self.on_route
            ),
            self.node.create_reader(
                "/apollo/prediction_raw", PredictionObstacles, self.on_prediction
            ),
        ]
        self.write_stats()

    @property
    def elapsed(self):
        if self.sim_time is None or self.route_epoch is None:
            return None
        return self.sim_time - self.route_epoch

    def is_active(self) -> bool:
        elapsed = self.elapsed
        return (
            elapsed is not None
            and self.active_window[0] <= elapsed <= self.active_window[1]
        )

    def on_clock(self, message: Clock) -> None:
        with self.lock:
            self.sim_time = message.clock / 1_000_000_000.0

    def on_route(self, message: RoutingResponse) -> None:
        with self.lock:
            if (
                self.route_epoch is None
                and self.sim_time is not None
                and message.status.error_code == 0
                and len(message.road) > 0
            ):
                self.route_epoch = self.sim_time

    def append_telemetry(self, row: dict) -> None:
        self.telemetry.write(json.dumps(row, sort_keys=True) + "\n")
        if self.counters["raw_messages"] % 20 == 0:
            self.telemetry.flush()

    def on_prediction(self, message: PredictionObstacles) -> None:
        with self.lock:
            try:
                self.counters["raw_messages"] += 1
                before_sha = sha256_message(message)
                active = self.is_active()
                target_count = len(target_obstacles(message, self.target_id))
                if active:
                    self.counters["active_messages"] += 1
                    if target_count == 1:
                        self.counters["active_target_messages"] += 1
                    else:
                        self.counters["missing_target_messages"] += 1

                output = message
                transform = None
                preservation_ok = True
                if active and self.semantic != "S0_STRAIGHT" and target_count == 1:
                    output = PredictionObstacles()
                    output.CopyFrom(message)
                    before = preservation_snapshot(message, self.target_id)
                    if self.semantic == "S1_LEFT_MERGE_OCCUPANCY":
                        transform = transform_left_merge(
                            output,
                            self.target_id,
                            float(self.config["lateral_offset_m"]),
                            float(self.config["relative_start_s"]),
                            float(self.config["relative_end_s"]),
                        )
                        self.endpoint_delta_min = min(
                            self.endpoint_delta_min, transform["endpoint_delta_m_min"]
                        )
                        self.endpoint_delta_max = max(
                            self.endpoint_delta_max, transform["endpoint_delta_m_max"]
                        )
                        after = preservation_snapshot(output, self.target_id)
                        preservation_ok = before == after
                    else:
                        transform = clear_target_trajectories(output, self.target_id)
                        after = preservation_snapshot(output, self.target_id)
                        before["targets"][0]["trajectory_count"] = 0
                        before["targets"][0]["probabilities"] = []
                        before["targets"][0]["points"] = []
                        preservation_ok = before == after
                    self.counters["transformed_messages"] += 1
                    if not preservation_ok:
                        self.counters["preservation_mismatches"] += 1

                after_sha = sha256_message(output)
                if self.semantic == "S0_STRAIGHT" and before_sha != after_sha:
                    self.counters["identity_mismatches"] += 1
                self.writer.write(output)
                self.counters["output_messages"] += 1
                if active:
                    self.append_telemetry(
                        {
                            "elapsed_s": self.elapsed,
                            "semantic": self.semantic,
                            "target_count": target_count,
                            "input_sha256": before_sha,
                            "output_sha256": after_sha,
                            "preservation_ok": preservation_ok,
                            "transform": transform,
                        }
                    )
                if self.counters["raw_messages"] % 20 == 0:
                    self.write_stats()
            except Exception as exc:
                self.exception = f"{type(exc).__name__}: {exc}"
                self.write_stats()
                self.stopping.set()

    def write_stats(self) -> None:
        atomic_json(
            self.stats_path,
            {
                "schema_version": 1,
                "classification": "NON_ADMISSION_CAUSAL_SENSITIVITY_PROBE",
                "semantic": self.semantic,
                "exception": self.exception,
                **self.counters,
                "endpoint_delta_m_min": (
                    None if math.isinf(self.endpoint_delta_min) else self.endpoint_delta_min
                ),
                "endpoint_delta_m_max": (
                    None if math.isinf(self.endpoint_delta_max) else self.endpoint_delta_max
                ),
            },
        )

    def close(self) -> None:
        with self.lock:
            self.telemetry.flush()
            os.fsync(self.telemetry.fileno())
            self.telemetry.close()
            self.write_stats()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    args = parser.parse_args()
    runtime = SensitivityInterposer(
        json.loads(args.config.read_text()), args.telemetry, args.stats
    )

    def stop(_signum, _frame):
        runtime.stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(
        "p4_sensitivity_interposer=READY admission_evidence=false",
        flush=True,
    )
    while not runtime.stopping.wait(0.2):
        pass
    runtime.close()
    os._exit(0 if runtime.exception is None else 2)


if __name__ == "__main__":
    main()
