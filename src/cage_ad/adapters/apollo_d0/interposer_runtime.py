#!/usr/bin/env python3
"""Protocol-v1 semantic fault interposer and deterministic probe executor."""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import threading
from typing import Sequence

from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingResponse

from cage_ad.protocol_v1.loader import PROTOCOL_VERSION, ProtocolValidationError, load_protocol
from cage_ad.protocol_v1.probes import (
    ActorHistorySample,
    ControlProbe,
    probe_suite_config,
    run_forecasting_probe,
    run_planning_probe,
)
from cage_ad.protocol_v1.scenario import scenario_candidate_by_id
from cage_ad.protocol_v1.transformers import (
    ActuatorCommand,
    AtomicDelayQueue,
    TrajectoryPoint,
    attenuate_braking_suffix,
    attenuate_lateral_maneuver,
    compress_trajectory_time,
    kinematic_residuals,
    scale_actuator_effectiveness,
    window_active,
)


PROBE_DOMAINS = {"interaction_forecasting", "motion_planning", "tracking_execution"}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _sha(message) -> str:
    return hashlib.sha256(message.SerializeToString()).hexdigest()


def _prediction_points(trajectory) -> list[TrajectoryPoint]:
    return [
        TrajectoryPoint(
            point.relative_time,
            point.path_point.x,
            point.path_point.y,
            point.path_point.s,
            point.path_point.theta,
            point.v,
            point.a,
            point.path_point.kappa,
        )
        for point in trajectory.trajectory_point
    ]


def _replace_trajectory_points(trajectory, points: Sequence[TrajectoryPoint]) -> None:
    del trajectory.trajectory_point[:]
    for source in points:
        point = trajectory.trajectory_point.add()
        point.relative_time = source.relative_time
        point.path_point.x = source.x
        point.path_point.y = source.y
        point.path_point.s = source.s
        point.path_point.theta = source.heading
        point.path_point.kappa = source.curvature
        point.v = source.v
        point.a = source.a


def _planning_points(message: ADCTrajectory) -> list[TrajectoryPoint]:
    return [
        TrajectoryPoint(
            point.relative_time,
            point.path_point.x,
            point.path_point.y,
            point.path_point.s,
            point.path_point.theta,
            point.v,
            point.a,
            point.path_point.kappa,
        )
        for point in message.trajectory_point
    ]


def _replace_planning_points(message: ADCTrajectory, points: Sequence[TrajectoryPoint]) -> None:
    del message.trajectory_point[:]
    for source in points:
        target = message.trajectory_point.add()
        target.relative_time = source.relative_time
        target.path_point.x = source.x
        target.path_point.y = source.y
        target.path_point.s = source.s
        target.path_point.theta = source.heading
        target.path_point.kappa = source.curvature
        target.v = source.v
        target.a = source.a


class BoundaryInterposer:
    def __init__(self, config: dict, capture_path: Path, private_stats: Path, repo_root: Path) -> None:
        # The conda-side planner already performed Draft 2020-12 validation.
        # Apollo host mode repeats cross-checks and requires that exact bundle SHA.
        self.bundle = load_protocol(repo_root, validate_json_schema=False)
        self._validate_config(config)
        self.config = config
        self.fault_id = config.get("fault_id")
        self.dose = config.get("dose")
        self.probe_domain = config.get("probe_domain")
        candidate = scenario_candidate_by_id(
            self.bundle, config["scenario_id"], config["candidate_id"]
        )
        self.trigger_window = candidate.trigger_window
        if tuple(map(float, config["trigger_window"])) != self.trigger_window:
            raise ProtocolValidationError("private trigger window does not match scenario candidate")
        self.probe_config = probe_suite_config(self.bundle)
        self.fixed_step = float(self.bundle.scenarios["common"]["fixed_delta_seconds"])
        self.control_probe = ControlProbe(self.probe_config.control)
        self.capture_path = capture_path
        self.private_stats = private_stats
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.sim_time: float | None = None
        self.route_epoch_sim: float | None = None
        self.prediction_delay_queue: AtomicDelayQueue[bytes] = AtomicDelayQueue(
            max(
                float(item["delay_s"])
                for item in self.bundle.faults["faults"]["forecast_stale_or_delayed"]["dose_grid"]
            )
        )
        self.control_delay_queue: AtomicDelayQueue[bytes] = AtomicDelayQueue(
            max(
                float(item["delay_s"])
                for item in self.bundle.faults["faults"]["control_command_transport_delay"]["dose_grid"]
            )
        )
        self.prediction_delay_was_active = False
        self.actor_history: deque[ActorHistorySample] = deque()
        self.latest_plan: tuple[TrajectoryPoint, ...] = ()
        self.localization: dict | None = None
        self.injector_exception: str | None = None
        self.activation_observations: list[dict] = []
        self.transform_log: list[dict] = []
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
            "delay_warmup_failures": 0,
            "post_window_controls_withheld": 0,
        }
        self.capture = {
            "schema_version": 2,
            "protocol_version": PROTOCOL_VERSION,
            "native_topics_disclosed": False,
            "oracle_fields_present": False,
            "forecast_samples": [],
            "plan_samples": [],
            "control_samples": [],
        }

        cyber.init("cage_d0_protocol_v1_interposer")
        self.node = cyber.Node("cage_d0_protocol_v1_interposer")
        self.prediction_writer = self.node.create_writer("/apollo/prediction", PredictionObstacles, 10)
        self.planning_writer = self.node.create_writer("/apollo/planning", ADCTrajectory, 10)
        self.control_writer = self.node.create_writer("/apollo/control_guarded", ControlCommand, 10)
        self.readers = [
            self.node.create_reader("/clock", Clock, self.on_clock),
            self.node.create_reader("/apollo/routing_response", RoutingResponse, self.on_route_response),
            self.node.create_reader("/apollo/prediction_raw", PredictionObstacles, self.on_prediction),
            self.node.create_reader("/apollo/planning_raw", ADCTrajectory, self.on_planning),
            self.node.create_reader("/apollo/control", ControlCommand, self.on_control),
            self.node.create_reader("/apollo/localization/pose", LocalizationEstimate, self.on_localization),
        ]
        self._write_live_status()

    def _write_live_status(self) -> None:
        atomic_json(
            self.private_stats,
            {
                "schema_version": 2,
                "protocol_version": PROTOCOL_VERSION,
                "injector_exception": self.injector_exception,
                **self.counters,
            },
        )

    def _fail(self, reason: str) -> None:
        self.injector_exception = reason
        self._write_live_status()
        self.stopping.set()

    def _validate_config(self, config: dict) -> None:
        if config.get("protocol_version") != PROTOCOL_VERSION:
            raise ProtocolValidationError("private interposer protocol version mismatch")
        if config.get("protocol_bundle_sha256") != self.bundle.bundle_sha256:
            raise ProtocolValidationError("private interposer protocol hash mismatch")
        fault_id = config.get("fault_id")
        probe_domain = config.get("probe_domain")
        if probe_domain is not None and probe_domain not in PROBE_DOMAINS:
            raise ProtocolValidationError("unknown probe domain")
        if fault_id is None:
            if config.get("dose") is not None:
                raise ProtocolValidationError("nominal config must not contain a dose")
            return
        try:
            recipe = self.bundle.faults["faults"][fault_id]
        except KeyError as exc:
            raise ProtocolValidationError(f"unknown fault: {fault_id}") from exc
        if config.get("dose") not in recipe["dose_grid"]:
            raise ProtocolValidationError("fault dose is not in the declared grid")

    @property
    def elapsed(self) -> float:
        if self.sim_time is None or self.route_epoch_sim is None:
            return -math.inf
        return self.sim_time - self.route_epoch_sim

    def active(self) -> bool:
        return self.route_epoch_sim is not None and window_active(
            self.elapsed, self.trigger_window[0], self.trigger_window[1]
        )

    def probe_active(self, domain: str) -> bool:
        return self.probe_domain == domain and self.active()

    def on_route_response(self, message: RoutingResponse) -> None:
        with self.lock:
            if (
                self.route_epoch_sim is None
                and self.sim_time is not None
                and message.status.error_code == 0
                and len(message.road) > 0
            ):
                self.route_epoch_sim = self.sim_time

    def on_localization(self, message: LocalizationEstimate) -> None:
        with self.lock:
            pose = message.pose
            self.localization = {
                "x": pose.position.x,
                "y": pose.position.y,
                "heading": pose.heading,
                "speed": math.hypot(pose.linear_velocity.x, pose.linear_velocity.y),
                "acceleration": pose.linear_acceleration_vrf.y,
            }

    def _release_delayed_controls(self) -> None:
        if self.sim_time is None or self.fault_id != "control_command_transport_delay":
            return
        delay = float(self.dose["delay_s"])
        for sample in self.control_delay_queue.release_due_samples(self.sim_time, delay):
            output = ControlCommand()
            output.ParseFromString(sample.content)
            self.control_writer.write(output)
            self.counters["control_out"] += 1
            self.counters["delayed_releases"] += 1
            self.activation_observations.append(
                {
                    "simulator_time_s": sample.source_time - self.route_epoch_sim,
                    "metric_value": self.sim_time - sample.source_time,
                    "transform_residual": None,
                }
            )

    def on_clock(self, message: Clock) -> None:
        with self.lock:
            self.sim_time = message.clock / 1_000_000_000.0
            self._release_delayed_controls()

    def _append_actor_history(self, message: PredictionObstacles) -> None:
        if self.sim_time is None or not message.prediction_obstacle:
            return
        obstacle = message.prediction_obstacle[0].perception_obstacle
        self.actor_history.append(
            ActorHistorySample(
                self.sim_time,
                obstacle.position.x,
                obstacle.position.y,
                math.hypot(obstacle.velocity.x, obstacle.velocity.y),
                obstacle.theta,
            )
        )
        cutoff = (
            self.sim_time
            - self.probe_config.forecasting.history_window_s
            - self.probe_config.forecasting.step_s
        )
        while self.actor_history and self.actor_history[0].timestamp < cutoff:
            self.actor_history.popleft()

    def _log_transform(self, boundary: str, target_fields: Sequence[str], before_sha: str, after_sha: str) -> None:
        self.transform_log.append(
            {
                "boundary": boundary,
                "target_fields": list(target_fields),
                "start_s": self.trigger_window[0],
                "end_s": self.trigger_window[1],
                "dose": self.dose,
                "input_sha256": before_sha,
                "output_sha256": after_sha,
                "transformed_message_count": 1,
            }
        )

    def on_prediction(self, message: PredictionObstacles) -> None:
        with self.lock:
            try:
                self.counters["prediction_in"] += 1
                self._append_actor_history(message)
                output = PredictionObstacles()
                output.CopyFrom(message)
                before_sha = _sha(message)
                active = self.active()
                source_time = message.header.timestamp_sec
                self.prediction_delay_queue.buffer(source_time, message.SerializeToString())
                transformed = False
                if self.probe_active("interaction_forecasting"):
                    forecast = run_forecasting_probe(tuple(self.actor_history), self.probe_config.forecasting)
                    if not output.prediction_obstacle:
                        raise ProtocolValidationError("forecast probe input has no actor")
                    predicted = output.prediction_obstacle[0]
                    if not predicted.trajectory:
                        predicted.trajectory.add().probability = 1.0
                    _replace_trajectory_points(predicted.trajectory[0], forecast.trajectory)
                    self.counters["probe_applications"] += 1
                    transformed = True
                elif active and self.fault_id == "forecast_stale_or_delayed":
                    selected = self.prediction_delay_queue.select_sample(
                        self.sim_time, float(self.dose["delay_s"])
                    )
                    if selected is None:
                        self.counters["delay_warmup_failures"] += 1
                        self._fail("prediction_delay_warmup_failure")
                        return
                    output.ParseFromString(selected.content)
                    output.header.CopyFrom(message.header)
                    self.activation_observations.append(
                        {
                            "simulator_time_s": self.elapsed,
                            "metric_value": self.sim_time - selected.source_time,
                            "transform_residual": None,
                        }
                    )
                    self.prediction_delay_was_active = True
                    self.counters["fault_applications"] += 1
                    transformed = True
                elif active and self.fault_id == "forecast_heading_or_maneuver_bias":
                    attenuation = float(self.dose["attenuation"])
                    endpoint_changes = []
                    for predicted in output.prediction_obstacle:
                        for trajectory in predicted.trajectory:
                            before = _prediction_points(trajectory)
                            if len(before) < 2:
                                continue
                            after = attenuate_lateral_maneuver(before, attenuation)
                            endpoint_changes.append(
                                math.hypot(after[-1].x - before[-1].x, after[-1].y - before[-1].y)
                            )
                            _replace_trajectory_points(trajectory, after)
                    if not endpoint_changes:
                        raise ProtocolValidationError("maneuver fault found no trajectory")
                    self.activation_observations.append(
                        {
                            "simulator_time_s": self.elapsed,
                            "metric_value": sum(endpoint_changes) / len(endpoint_changes),
                            "transform_residual": 0.0,
                        }
                    )
                    self.counters["fault_applications"] += 1
                    transformed = True
                elif self.prediction_delay_was_active and self.elapsed > self.trigger_window[1]:
                    self.prediction_delay_queue.clear()
                    self.prediction_delay_was_active = False
                self.prediction_writer.write(output)
                self.counters["prediction_out"] += 1
                if transformed:
                    target_fields = (
                        ["predicted_trajectory_points", "predicted_heading"]
                        if self.probe_active("interaction_forecasting")
                        else self.bundle.faults["faults"][self.fault_id]["target_fields"]
                    )
                    self._log_transform(
                        "semantic_prediction_output",
                        target_fields,
                        before_sha,
                        _sha(output),
                    )
                if self.route_epoch_sim is not None and self.counters["prediction_in"] % 5 == 0:
                    self.capture["forecast_samples"].append(
                        {"t": round(self.elapsed, 3), "message_sha256": _sha(output)}
                    )
            except Exception as exc:
                self._fail(f"{type(exc).__name__}: {exc}")

    def on_planning(self, message: ADCTrajectory) -> None:
        with self.lock:
            try:
                self.counters["planning_in"] += 1
                output = ADCTrajectory()
                output.CopyFrom(message)
                before = _planning_points(message)
                after = before
                before_sha = _sha(message)
                transformed = False
                if self.probe_active("motion_planning"):
                    if self.localization is None:
                        raise ProtocolValidationError("planning probe lacks legal localization state")
                    forecast = run_forecasting_probe(tuple(self.actor_history), self.probe_config.forecasting)
                    after = list(
                        run_planning_probe(
                            before,
                            forecast.trajectory,
                            self.localization["speed"],
                            self.localization["acceleration"],
                            self.probe_config.planning,
                        )
                    )
                    self.counters["probe_applications"] += 1
                    transformed = True
                elif self.active() and self.fault_id == "planning_constraint_omitted":
                    after = attenuate_braking_suffix(before, float(self.dose["braking_attenuation"]))
                    removed = sum(
                        max(0.0, right_before.a - left_before.a)
                        * (next_before.relative_time - left_before.relative_time)
                        for left_before, next_before, right_before in zip(before, before[1:], after)
                        if left_before.a < 0.0
                    )
                    position_residual, speed_residual = kinematic_residuals(after)
                    self.activation_observations.append(
                        {
                            "simulator_time_s": self.elapsed,
                            "metric_value": removed,
                            "transform_residual": speed_residual,
                            "position_residual_m": position_residual,
                        }
                    )
                    self.counters["fault_applications"] += 1
                    transformed = True
                elif self.active() and self.fault_id == "planning_unsafe_cost_or_speed_bias":
                    scale = float(self.dose["time_scale"])
                    after = compress_trajectory_time(before, scale)
                    ratios = [
                        (right_after.relative_time - left_after.relative_time)
                        / (right_before.relative_time - left_before.relative_time)
                        for left_before, right_before, left_after, right_after in zip(
                            before, before[1:], after, after[1:]
                        )
                    ]
                    self.activation_observations.append(
                        {
                            "simulator_time_s": self.elapsed,
                            "metric_value": sorted(ratios)[len(ratios) // 2],
                            "transform_residual": 0.0,
                        }
                    )
                    self.counters["fault_applications"] += 1
                    transformed = True
                if transformed:
                    _replace_planning_points(output, after)
                    target_fields = (
                        ["x", "y", "heading", "path_point_s", "v", "a", "relative_time"]
                        if self.probe_active("motion_planning")
                        else self.bundle.faults["faults"][self.fault_id]["target_fields"]
                    )
                    self._log_transform(
                        "planning_trajectory_output",
                        target_fields,
                        before_sha,
                        _sha(output),
                    )
                self.latest_plan = tuple(after)
                self.planning_writer.write(output)
                self.counters["planning_out"] += 1
                if self.route_epoch_sim is not None and self.counters["planning_in"] % 5 == 0 and after:
                    self.capture["plan_samples"].append(
                        {
                            "t": round(self.elapsed, 3),
                            "point_count": len(after),
                            "maximum_speed_mps": max(point.v for point in after),
                        }
                    )
            except Exception as exc:
                self._fail(f"{type(exc).__name__}: {exc}")

    def on_control(self, message: ControlCommand) -> None:
        with self.lock:
            try:
                self.counters["control_in"] += 1
                output = ControlCommand()
                output.CopyFrom(message)
                before_sha = _sha(message)
                transformed = False
                if self.probe_active("tracking_execution"):
                    if self.localization is None or not self.latest_plan:
                        raise ProtocolValidationError("control probe lacks legal state or plan")
                    command = self.control_probe.command(
                        timestamp=message.header.timestamp_sec,
                        ego_x=self.localization["x"],
                        ego_y=self.localization["y"],
                        ego_heading=self.localization["heading"],
                        current_speed_mps=self.localization["speed"],
                        target_plan=self.latest_plan,
                        dt=self.fixed_step,
                        gear=message.gear_location,
                    )
                    output.throttle = command.throttle * 100.0
                    output.brake = command.brake * 100.0
                    output.steering_target = (
                        command.steering_target
                        / self.probe_config.control.maximum_steering_angle_deg
                        * 100.0
                    )
                    self.counters["probe_applications"] += 1
                    transformed = True
                elif self.active() and self.fault_id == "control_gain_saturation_tracking_bias":
                    before = ActuatorCommand(
                        message.header.timestamp_sec,
                        message.throttle,
                        message.brake,
                        message.steering_target,
                        message.gear_location,
                    )
                    after = scale_actuator_effectiveness(before, float(self.dose["effectiveness"]))
                    output.throttle = after.throttle
                    output.brake = after.brake
                    output.steering_target = after.steering_target
                    nonzero_ratios = [
                        transformed_value / original
                        for original, transformed_value in (
                            (before.throttle, after.throttle),
                            (before.brake, after.brake),
                            (before.steering_target, after.steering_target),
                        )
                        if abs(original) > 1e-9
                    ]
                    if nonzero_ratios:
                        self.activation_observations.append(
                            {
                                "simulator_time_s": self.elapsed,
                                "metric_value": sorted(nonzero_ratios)[len(nonzero_ratios) // 2],
                                "transform_residual": 0.0,
                            }
                        )
                    self.counters["fault_applications"] += 1
                    transformed = True
                elif self.active() and self.fault_id == "control_command_transport_delay":
                    self.control_delay_queue.buffer(self.sim_time, output.SerializeToString())
                    self.counters["fault_applications"] += 1
                    self._log_transform(
                        "control_command_transport",
                        self.bundle.faults["faults"][self.fault_id]["target_fields"],
                        before_sha,
                        before_sha,
                    )
                    return
                elif self.fault_id == "control_command_transport_delay" and len(self.control_delay_queue):
                    self.counters["post_window_controls_withheld"] += 1
                    return
                self.control_writer.write(output)
                self.counters["control_out"] += 1
                if transformed:
                    target_fields = (
                        ["throttle", "brake", "steering_target"]
                        if self.probe_active("tracking_execution")
                        else self.bundle.faults["faults"][self.fault_id]["target_fields"]
                    )
                    self._log_transform(
                        "control_command_to_actuator",
                        target_fields,
                        before_sha,
                        _sha(output),
                    )
                if self.route_epoch_sim is not None and self.counters["control_in"] % 5 == 0:
                    self.capture["control_samples"].append(
                        {
                            "t": round(self.elapsed, 3),
                            "throttle_pct": output.throttle,
                            "brake_pct": output.brake,
                            "steering_pct": output.steering_target,
                        }
                    )
            except Exception as exc:
                self._fail(f"{type(exc).__name__}: {exc}")

    def close(self) -> None:
        with self.lock:
            atomic_json(self.capture_path, self.capture)
            atomic_json(
                self.private_stats,
                {
                    "schema_version": 2,
                    "protocol_version": PROTOCOL_VERSION,
                    **self.counters,
                    "injector_exception": self.injector_exception,
                    "activation_observations": self.activation_observations,
                    "transform_log": self.transform_log,
                    "queued_prediction_samples": len(self.prediction_delay_queue),
                    "queued_control_samples": len(self.control_delay_queue),
                },
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-config", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--private-stats", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    args = parser.parse_args()
    runtime = BoundaryInterposer(
        json.loads(args.private_config.read_text()),
        args.capture,
        args.private_stats,
        args.repo_root,
    )

    def stop(_signum, _frame):
        runtime.stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("d0_interposer=READY protocol_v1=true diagnosis_access=false", flush=True)
    while not runtime.stopping.wait(0.2):
        pass
    runtime.close()
    os._exit(0 if runtime.injector_exception is None else 2)


if __name__ == "__main__":
    main()
