#!/usr/bin/env python3
"""Private semantic-boundary injector and non-GT probe executor for D0 smoke."""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
import os
from pathlib import Path
import signal
import threading

from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest

from cage_ad.adapters.apollo_d0.semantics import (
    ControlTarget,
    FaultMechanism,
    MotionPoint,
    bounded_brake_probe,
    constant_velocity_probe,
    control_fault,
    forecast_fault,
    planning_fault,
    safety_envelope_probe,
)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def prediction_points(message: PredictionObstacles) -> list[MotionPoint]:
    if not message.prediction_obstacle or not message.prediction_obstacle[0].trajectory:
        return []
    trajectory = message.prediction_obstacle[0].trajectory[0]
    return [
        MotionPoint(
            t=point.relative_time,
            x=point.path_point.x,
            y=point.path_point.y,
            heading=point.path_point.theta,
            speed=point.v,
            acceleration=point.a,
        )
        for point in trajectory.trajectory_point
    ]


def set_prediction_points(message: PredictionObstacles, points: list[MotionPoint]) -> None:
    if not message.prediction_obstacle:
        return
    predicted = message.prediction_obstacle[0]
    if not predicted.trajectory:
        predicted.trajectory.add().probability = 1.0
    trajectory = predicted.trajectory[0]
    del trajectory.trajectory_point[:]
    for source in points:
        point = trajectory.trajectory_point.add()
        point.relative_time = source.t
        point.path_point.x = source.x
        point.path_point.y = source.y
        point.path_point.theta = source.heading
        point.path_point.s = max(0.0, math.hypot(source.x - points[0].x, source.y - points[0].y))
        point.v = source.speed
        point.a = source.acceleration


def planning_points(message: ADCTrajectory) -> list[MotionPoint]:
    return [
        MotionPoint(
            t=point.relative_time,
            x=point.path_point.x,
            y=point.path_point.y,
            heading=point.path_point.theta,
            speed=point.v,
            acceleration=point.a,
        )
        for point in message.trajectory_point
    ]


def set_planning_points(message: ADCTrajectory, points: list[MotionPoint]) -> None:
    for target, source in zip(message.trajectory_point, points):
        target.v = source.speed
        target.a = source.acceleration


class BoundaryInterposer:
    def __init__(self, config: dict, capture_path: Path, private_stats: Path) -> None:
        self.config = config
        mechanism = config.get("fault_mechanism")
        self.mechanism = None if mechanism is None else FaultMechanism(mechanism)
        self.probe_domain = config.get("probe_domain")
        self.capture_path = capture_path
        self.private_stats = private_stats
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.sim_time = None
        self.started_sim = None
        self.diagnostic_started_sim = None
        self.delayed_controls = deque()
        self.counters = {
            "prediction_in": 0,
            "prediction_out": 0,
            "planning_in": 0,
            "planning_out": 0,
            "control_in": 0,
            "control_out": 0,
            "fault_applications": 0,
            "probe_applications": 0,
            "delayed_releases": 0,
        }
        self.capture = {
            "schema_version": 1,
            "native_topics_disclosed": False,
            "oracle_fields_present": False,
            "forecast_samples": [],
            "plan_samples": [],
            "control_samples": [],
        }

        cyber.init("cage_d0_boundary_interposer")
        self.node = cyber.Node("cage_d0_boundary_interposer")
        self.prediction_writer = self.node.create_writer("/apollo/prediction", PredictionObstacles, 10)
        self.planning_writer = self.node.create_writer("/apollo/planning", ADCTrajectory, 10)
        self.control_writer = self.node.create_writer("/apollo/control_guarded", ControlCommand, 10)
        self.readers = [
            self.node.create_reader("/clock", Clock, self.on_clock),
            self.node.create_reader("/apollo/routing_request", RoutingRequest, self.on_route),
            self.node.create_reader("/apollo/prediction_raw", PredictionObstacles, self.on_prediction),
            self.node.create_reader("/apollo/planning_raw", ADCTrajectory, self.on_planning),
            self.node.create_reader("/apollo/control", ControlCommand, self.on_control),
        ]

    def on_route(self, _message: RoutingRequest) -> None:
        with self.lock:
            if self.diagnostic_started_sim is None and self.sim_time is not None:
                self.diagnostic_started_sim = self.sim_time

    @property
    def elapsed(self) -> float:
        if self.sim_time is None or self.diagnostic_started_sim is None:
            return 0.0
        return self.sim_time - self.diagnostic_started_sim

    def probe_active(self, domain: str) -> bool:
        start = float(self.config.get("probe_start_s", 8.0))
        duration = float(self.config.get("probe_duration_s", 3.0))
        return self.probe_domain == domain and start <= self.elapsed <= start + duration

    def on_clock(self, message: Clock) -> None:
        with self.lock:
            self.sim_time = message.clock / 1_000_000_000.0
            if self.started_sim is None:
                self.started_sim = self.sim_time
            while self.delayed_controls and self.delayed_controls[0][0] <= self.sim_time:
                _, target = self.delayed_controls.popleft()
                self.control_writer.write(target)
                self.counters["control_out"] += 1
                self.counters["delayed_releases"] += 1

    def on_prediction(self, message: PredictionObstacles) -> None:
        with self.lock:
            self.counters["prediction_in"] += 1
            output = PredictionObstacles()
            output.CopyFrom(message)
            before = prediction_points(message)
            after = before
            if self.mechanism in {
                FaultMechanism.FORECAST_STALE,
                FaultMechanism.FORECAST_HEADING_BIAS,
            }:
                after = forecast_fault(before, self.mechanism)
                self.counters["fault_applications"] += 1
            if self.probe_active("interaction_forecasting"):
                after = constant_velocity_probe(before)
                self.counters["probe_applications"] += 1
            set_prediction_points(output, after)
            self.prediction_writer.write(output)
            self.counters["prediction_out"] += 1
            if self.counters["prediction_in"] % 5 == 0 and before and after:
                self.capture["forecast_samples"].append(
                    {
                        "t": round(self.elapsed, 3),
                        "horizon_end_displacement_m": round(
                            math.hypot(after[-1].x - before[-1].x, after[-1].y - before[-1].y), 6
                        ),
                        "predicted_speed_end_mps": round(after[-1].speed, 6),
                    }
                )

    def on_planning(self, message: ADCTrajectory) -> None:
        with self.lock:
            self.counters["planning_in"] += 1
            output = ADCTrajectory()
            output.CopyFrom(message)
            before = planning_points(message)
            after = before
            if self.mechanism in {
                FaultMechanism.PLAN_CONSTRAINT_OMITTED,
                FaultMechanism.PLAN_UNSAFE_SPEED_BIAS,
            }:
                after = planning_fault(before, self.mechanism)
                self.counters["fault_applications"] += 1
            if self.probe_active("motion_planning"):
                after = safety_envelope_probe(before)
                self.counters["probe_applications"] += 1
            set_planning_points(output, after)
            self.planning_writer.write(output)
            self.counters["planning_out"] += 1
            if self.counters["planning_in"] % 5 == 0 and after:
                self.capture["plan_samples"].append(
                    {
                        "t": round(self.elapsed, 3),
                        "point_count": len(after),
                        "max_speed_mps": round(max(point.speed for point in after), 6),
                        "min_speed_mps": round(min(point.speed for point in after), 6),
                    }
                )

    def on_control(self, message: ControlCommand) -> None:
        with self.lock:
            self.counters["control_in"] += 1
            target = ControlTarget(
                t=self.elapsed,
                throttle_pct=message.throttle,
                brake_pct=message.brake,
                steering_pct=message.steering_target,
            )
            output = ControlCommand()
            output.CopyFrom(message)
            if self.probe_active("tracking_execution"):
                target = bounded_brake_probe(self.elapsed)
                output.throttle = target.throttle_pct
                output.brake = target.brake_pct
                output.steering_target = target.steering_pct
                self.counters["probe_applications"] += 1
            elif self.mechanism == FaultMechanism.CONTROL_GAIN_BIAS:
                target = control_fault(target, self.mechanism)
                output.throttle = target.throttle_pct
                output.brake = target.brake_pct
                output.steering_target = target.steering_pct
                self.counters["fault_applications"] += 1
            if self.mechanism == FaultMechanism.CONTROL_TRANSPORT_DELAY and not self.probe_active(
                "tracking_execution"
            ):
                release = (self.sim_time or 0.0) + float(self.config.get("control_delay_s", 1.5))
                self.delayed_controls.append((release, output))
                self.counters["fault_applications"] += 1
            else:
                if self.probe_active("tracking_execution"):
                    self.delayed_controls.clear()
                self.control_writer.write(output)
                self.counters["control_out"] += 1
            if self.counters["control_in"] % 5 == 0:
                self.capture["control_samples"].append(
                    {
                        "t": round(self.elapsed, 3),
                        "throttle_pct": round(target.throttle_pct, 6),
                        "brake_pct": round(target.brake_pct, 6),
                        "steering_pct": round(target.steering_pct, 6),
                        "queued_targets": len(self.delayed_controls),
                    }
                )

    def close(self) -> None:
        # Stop callback dispatch before taking the callback lock; otherwise a
        # live /clock stream can prevent graceful process termination.
        cyber.shutdown()
        with self.lock:
            atomic_json(self.capture_path, self.capture)
            atomic_json(
                self.private_stats,
                {
                    "schema_version": 1,
                    **self.counters,
                    "queued_at_shutdown": len(self.delayed_controls),
                },
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-config", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--private-stats", type=Path, required=True)
    args = parser.parse_args()
    runtime = BoundaryInterposer(json.loads(args.private_config.read_text()), args.capture, args.private_stats)

    def stop(_signum, _frame):
        runtime.stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("d0_interposer=READY private_config_loaded=true diagnosis_access=false", flush=True)
    while not runtime.stopping.wait(0.2):
        pass
    runtime.close()


if __name__ == "__main__":
    main()
