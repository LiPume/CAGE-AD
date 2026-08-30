#!/usr/bin/env python3
"""Protocol-v1 YAML-driven perfect-perception scenario runtime.

Simulator truth is confined to this private adapter and is used only to build
the Apollo PnC input. It is never written to diagnosis-visible evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import random
import signal
import threading

import carla
from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import (
    PerceptionObstacle,
    PerceptionObstacles,
)
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingResponse

from cage_ad.protocol_v1.loader import PROTOCOL_VERSION, ProtocolValidationError, load_protocol
from cage_ad.protocol_v1.probes import probe_suite_config
from cage_ad.protocol_v1.scenario import ScenarioCandidate, scenario_candidate_by_id


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _seed_everything(seed: int, client: carla.Client) -> None:
    if os.environ.get("PYTHONHASHSEED") != str(seed):
        raise ProtocolValidationError("PYTHONHASHSEED must be exported before scenario process launch")
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    client.get_trafficmanager().set_random_device_seed(seed)


class ScenarioRuntime:
    def __init__(self, config: dict, stats_path: Path, repo_root: Path) -> None:
        # Full JSON-Schema validation is mandatory in prepare_attempt. Apollo's
        # host Python deliberately stays dependency-minimal; this process repeats
        # all cross-registry checks and verifies the exact prevalidated bundle SHA.
        bundle = load_protocol(repo_root, validate_json_schema=False)
        if config.get("protocol_version") != PROTOCOL_VERSION:
            raise ProtocolValidationError("private scenario protocol version mismatch")
        if config.get("protocol_bundle_sha256") != bundle.bundle_sha256:
            raise ProtocolValidationError("private scenario protocol hash mismatch")
        self.candidate: ScenarioCandidate = scenario_candidate_by_id(
            bundle, config["scenario_id"], config["candidate_id"]
        )
        self.common = bundle.scenarios["common"]
        self.forecast_config = probe_suite_config(bundle).forecasting
        self.seed = int(config["seed"])
        self.stats_path = stats_path
        self.client = carla.Client("127.0.0.1", 2000)
        self.client.set_timeout(10)
        _seed_everything(self.seed, self.client)
        self.world = self.client.get_world()
        if not self.world.get_map().name.endswith(str(self.common["map"])):
            raise ProtocolValidationError("CARLA map does not match protocol")
        self._set_fixed_environment()
        self.actor = None
        self.spawn_basis = None
        self.route_epoch_sim = None
        self.stopping = threading.Event()
        self.lock = threading.RLock()
        self.sim_time = None
        self.frames = 0
        self.predictions = 0
        self.route_accepted = False
        self.actor_spawned = False
        self.clock_values: list[float] = []
        self.injector_exception: str | None = None

        cyber.init("cage_d0_protocol_v1_scenario")
        self.node = cyber.Node("cage_d0_protocol_v1_scenario")
        self.prediction_writer = self.node.create_writer(
            "/apollo/prediction_raw", PredictionObstacles, 10
        )
        self.perception_writer = self.node.create_writer(
            "/apollo/perception/obstacles", PerceptionObstacles, 10
        )
        self.readers = [
            self.node.create_reader("/clock", Clock, self.on_clock),
            self.node.create_reader("/apollo/routing_response", RoutingResponse, self.on_route_response),
        ]
        self._write_live_status()

    def _write_live_status(self) -> None:
        atomic_json(
            self.stats_path,
            {
                "schema_version": 2,
                "protocol_version": PROTOCOL_VERSION,
                "actor_spawned": self.actor_spawned,
                "route_accepted": self.route_accepted,
                "injector_exception": self.injector_exception,
            },
        )

    def _set_fixed_environment(self) -> None:
        fixed = self.common["fixed_environment"]
        weather = carla.WeatherParameters(
            cloudiness=float(fixed["cloudiness"]),
            precipitation=float(fixed["precipitation"]),
            precipitation_deposits=float(fixed["precipitation_deposits"]),
            wind_intensity=float(fixed["wind_intensity"]),
            sun_azimuth_angle=float(fixed["sun_azimuth_angle"]),
            sun_altitude_angle=float(fixed["sun_altitude_angle"]),
            fog_density=float(fixed["fog_density"]),
            fog_distance=float(fixed["fog_distance"]),
            wetness=float(fixed["wetness"]),
        )
        self.world.set_weather(weather)

    def on_route_response(self, message: RoutingResponse) -> None:
        with self.lock:
            accepted = message.status.error_code == 0 and len(message.road) > 0
            self.route_accepted = self.route_accepted or accepted
            if accepted and self.route_epoch_sim is None and self.sim_time is not None:
                self.route_epoch_sim = self.sim_time

    def find_ego(self):
        candidates = [
            actor
            for actor in self.world.get_actors().filter("vehicle.*")
            if actor.attributes.get("role_name") == "ego_vehicle"
        ]
        return candidates[0] if len(candidates) == 1 else None

    def spawn_actor(self, ego) -> None:
        transform = ego.get_transform()
        forward = transform.get_forward_vector()
        right = transform.get_right_vector()
        longitudinal, lateral = self.candidate.spawn_offsets_m
        location = transform.location + forward * longitudinal + right * lateral
        location.z += float(self.common["runtime_binding"]["actor_z_offset_m"])
        actor_transform = carla.Transform(location, transform.rotation)
        blueprint = self.world.get_blueprint_library().find(self.common["actor_blueprint"])
        blueprint.set_attribute("role_name", "cage_interaction_actor")
        self.actor = self.world.try_spawn_actor(blueprint, actor_transform)
        if self.actor is None:
            raise RuntimeError("failed to spawn declared interaction actor")
        self.spawn_basis = (
            (forward.x, -forward.y),
            (right.x, -right.y),
            -math.radians(transform.rotation.yaw),
        )
        self.actor_spawned = True

    def intended_state(self, elapsed: float, horizon: float) -> tuple[float, float]:
        return self.candidate.velocity(elapsed + horizon)

    def drive_actor(self, elapsed: float, active: bool) -> None:
        longitudinal, lateral = self.intended_state(elapsed, 0.0) if active else (0.0, 0.0)
        transform = self.actor.get_transform()
        forward = transform.get_forward_vector()
        right = transform.get_right_vector()
        self.actor.set_target_velocity(
            carla.Vector3D(
                x=forward.x * longitudinal + right.x * lateral,
                y=forward.y * longitudinal + right.y * lateral,
                z=0.0,
            )
        )

    @staticmethod
    def fill_obstacle(message, actor, timestamp: float) -> None:
        transform = actor.get_transform()
        velocity = actor.get_velocity()
        extent = actor.bounding_box.extent
        message.id = 1001
        message.position.x = transform.location.x
        message.position.y = -transform.location.y
        message.position.z = transform.location.z
        message.theta = -math.radians(transform.rotation.yaw)
        message.velocity.x = velocity.x
        message.velocity.y = -velocity.y
        message.velocity.z = velocity.z
        message.length = extent.x * 2.0
        message.width = extent.y * 2.0
        message.height = extent.z * 2.0
        message.type = PerceptionObstacle.VEHICLE
        message.timestamp = timestamp
        message.tracking_time = timestamp
        message.confidence = 1.0

    def publish_stack_input(self, timestamp: float, elapsed: float) -> None:
        perception = PerceptionObstacles()
        perception.header.timestamp_sec = timestamp
        perception.header.module_name = "cage_d0_perfect_perception_adapter"
        obstacle = perception.perception_obstacle.add()
        self.fill_obstacle(obstacle, self.actor, timestamp)
        self.perception_writer.write(perception)

        prediction = PredictionObstacles()
        prediction.header.timestamp_sec = timestamp
        prediction.header.module_name = "cage_d0_semantic_forecast_adapter"
        prediction.start_timestamp = timestamp
        prediction.end_timestamp = timestamp + self.forecast_config.horizon_s
        predicted = prediction.prediction_obstacle.add()
        predicted.perception_obstacle.CopyFrom(obstacle)
        predicted.timestamp = timestamp
        predicted.predicted_period = self.forecast_config.horizon_s
        trajectory = predicted.trajectory.add()
        trajectory.probability = 1.0
        start_x, start_y = obstacle.position.x, obstacle.position.y
        forward, right, actor_heading = self.spawn_basis
        x, y, path_s = start_x, start_y, 0.0
        previous_speed = None
        previous_horizon = 0.0
        point_count = int(round(self.forecast_config.horizon_s / self.forecast_config.step_s)) + 1
        for index in range(point_count):
            horizon = index * self.forecast_config.step_s
            longitudinal, lateral = self.intended_state(elapsed, horizon)
            velocity_x = forward[0] * longitudinal + right[0] * lateral
            velocity_y = forward[1] * longitudinal + right[1] * lateral
            speed = math.hypot(velocity_x, velocity_y)
            if index:
                delta = horizon - previous_horizon
                next_x, next_y = x + velocity_x * delta, y + velocity_y * delta
                path_s += math.hypot(next_x - x, next_y - y)
                x, y = next_x, next_y
            heading = math.atan2(velocity_y, velocity_x) if speed > 1e-9 else actor_heading
            point = trajectory.trajectory_point.add()
            point.path_point.x = x
            point.path_point.y = y
            point.path_point.z = obstacle.position.z
            point.path_point.theta = heading
            point.path_point.s = path_s
            point.v = speed
            point.a = (
                0.0
                if previous_speed is None
                else (speed - previous_speed) / self.forecast_config.step_s
            )
            point.relative_time = horizon
            previous_speed = speed
            previous_horizon = horizon
        self.prediction_writer.write(prediction)
        self.predictions += 1

    def on_clock(self, message: Clock) -> None:
        with self.lock:
            try:
                timestamp = message.clock / 1_000_000_000.0
                self.sim_time = timestamp
                self.clock_values.append(timestamp)
                ego = self.find_ego()
                if ego is None:
                    return
                if self.actor is None:
                    self.spawn_actor(ego)
                elapsed = 0.0 if self.route_epoch_sim is None else timestamp - self.route_epoch_sim
                self.drive_actor(elapsed, self.route_epoch_sim is not None)
                self.publish_stack_input(timestamp, elapsed)
                self.frames += 1
            except Exception as exc:
                self.injector_exception = f"{type(exc).__name__}: {exc}"
                self._write_live_status()
                self.stopping.set()

    def close(self) -> None:
        with self.lock:
            if self.actor is not None:
                self.actor.destroy()
                self.actor = None
            deltas = [right - left for left, right in zip(self.clock_values, self.clock_values[1:])]
            non_fixed_clock_steps = sum(abs(delta - 0.05) > 1e-6 for delta in deltas)
            atomic_json(
                self.stats_path,
                {
                    "schema_version": 2,
                    "protocol_version": PROTOCOL_VERSION,
                    "frames": self.frames,
                    "predictions": self.predictions,
                    "actor_spawned": self.actor_spawned,
                    "actor_destroyed": True,
                    "route_accepted": self.route_accepted,
                    "route_epoch_sim": self.route_epoch_sim,
                    "non_fixed_clock_steps": non_fixed_clock_steps,
                    "injector_exception": self.injector_exception,
                },
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-scenario-config", type=Path, required=True)
    parser.add_argument("--private-stats", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    args = parser.parse_args()
    runtime = ScenarioRuntime(
        json.loads(args.private_scenario_config.read_text()), args.private_stats, args.repo_root
    )

    def stop(_signum, _frame):
        runtime.stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("d0_scenario_runtime=READY protocol_v1=true diagnosis_access=false", flush=True)
    while not runtime.stopping.wait(0.2):
        pass
    runtime.close()
    os._exit(0 if runtime.injector_exception is None else 2)


if __name__ == "__main__":
    main()
