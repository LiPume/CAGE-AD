#!/usr/bin/env python3
"""Perfect-perception interaction actor and prediction-input publisher for Apollo D0.

Simulator truth is consumed only here to construct the PnC stack input. The
diagnosis process never imports this entry point or reads its private config.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import threading
from pathlib import Path

import carla
from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import (
    PerceptionObstacle,
    PerceptionObstacles,
)
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


class ScenarioRuntime:
    def __init__(self, config: dict, stats_path: Path) -> None:
        self.config = config
        self.stats_path = stats_path
        self.client = carla.Client("127.0.0.1", 2000)
        self.client.set_timeout(10)
        self.world = self.client.get_world()
        self.actor = None
        self.started_sim = None
        self.interaction_started_sim = None
        self.stopping = threading.Event()
        self.lock = threading.RLock()
        self.sim_time = None
        self.frames = 0
        self.predictions = 0

        cyber.init("cage_d0_scenario_runtime")
        self.node = cyber.Node("cage_d0_scenario_runtime")
        self.prediction_writer = self.node.create_writer(
            "/apollo/prediction_raw", PredictionObstacles, 10
        )
        self.perception_writer = self.node.create_writer(
            "/apollo/perception/obstacles", PerceptionObstacles, 10
        )
        self.clock_reader = self.node.create_reader("/clock", Clock, self.on_clock)
        self.route_reader = self.node.create_reader(
            "/apollo/routing_request", RoutingRequest, self.on_route
        )

    def on_route(self, _message: RoutingRequest) -> None:
        # Route publication is the deterministic scenario epoch.  It avoids
        # both stack-warmup drift and the stationary-obstacle bootstrap that
        # occurs if activation waits for ego motion.
        with self.lock:
            if self.interaction_started_sim is None and self.sim_time is not None:
                self.interaction_started_sim = self.sim_time

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
        scenario = self.config["scenario_kind"]
        longitudinal = 22.0 if scenario == "lead_vehicle_deceleration" else 20.0
        lateral = 0.0 if scenario == "lead_vehicle_deceleration" else -3.5
        location = transform.location + forward * longitudinal + right * lateral
        location.z += 0.5
        actor_transform = carla.Transform(location, transform.rotation)
        blueprints = self.world.get_blueprint_library()
        blueprint = blueprints.find("vehicle.audi.tt")
        blueprint.set_attribute("role_name", "cage_interaction_actor")
        self.actor = self.world.try_spawn_actor(blueprint, actor_transform)
        if self.actor is None:
            raise RuntimeError("failed to spawn deterministic interaction actor")

    def intended_state(self, elapsed: float, horizon: float) -> tuple[float, float]:
        future = elapsed + horizon
        if self.config["scenario_kind"] == "lead_vehicle_deceleration":
            speed = 4.0 if future < 5.0 else max(0.0, 4.0 - (future - 5.0) * 2.0)
            return speed, 0.0
        longitudinal = 2.5
        lateral = 0.0 if future < 4.0 else min(1.2, (future - 4.0) * 0.45)
        return longitudinal, lateral

    def drive_actor(self, elapsed: float, active: bool) -> None:
        # Keep the interaction actor at its initial pose while Apollo is warming
        # up.  Otherwise stack-start latency changes the initial separation and
        # makes nominal/fault/counterfactual runs incomparable.
        longitudinal, lateral = (
            self.intended_state(elapsed, 0.0) if active else (0.0, 0.0)
        )
        transform = self.actor.get_transform()
        forward = transform.get_forward_vector()
        right = transform.get_right_vector()
        self.actor.set_target_velocity(
            carla.Vector3D(
                x=forward.x * longitudinal + right.x * lateral,
                y=forward.y * longitudinal + right.y * lateral,
                z=0,
            )
        )

    @staticmethod
    def fill_obstacle(message, actor, timestamp: float) -> None:
        transform = actor.get_transform()
        velocity = actor.get_velocity()
        extent = actor.bounding_box.extent
        obstacle = message
        obstacle.id = 1001
        obstacle.position.x = transform.location.x
        obstacle.position.y = -transform.location.y
        obstacle.position.z = transform.location.z
        obstacle.theta = -math.radians(transform.rotation.yaw)
        obstacle.velocity.x = velocity.x
        obstacle.velocity.y = -velocity.y
        obstacle.velocity.z = velocity.z
        obstacle.length = extent.x * 2
        obstacle.width = extent.y * 2
        obstacle.height = extent.z * 2
        obstacle.type = PerceptionObstacle.VEHICLE
        obstacle.timestamp = timestamp
        obstacle.tracking_time = timestamp
        obstacle.confidence = 1.0

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
        prediction.end_timestamp = timestamp + 5.0
        predicted = prediction.prediction_obstacle.add()
        predicted.perception_obstacle.CopyFrom(obstacle)
        predicted.timestamp = timestamp
        predicted.predicted_period = 5.0
        trajectory = predicted.trajectory.add()
        trajectory.probability = 1.0
        transform = self.actor.get_transform()
        start_x = transform.location.x
        start_y = -transform.location.y
        heading = -math.radians(transform.rotation.yaw)
        x, y = start_x, start_y
        previous_horizon = 0.0
        for index in range(26):
            horizon = index * 0.2
            speed, lateral = self.intended_state(elapsed, horizon)
            delta = horizon - previous_horizon
            x += speed * math.cos(heading) * delta
            y += speed * math.sin(heading) * delta - lateral * delta
            point = trajectory.trajectory_point.add()
            point.path_point.x = x
            point.path_point.y = y
            point.path_point.z = transform.location.z
            point.path_point.theta = heading
            point.path_point.s = max(0.0, math.hypot(x - start_x, y - start_y))
            point.v = math.hypot(speed, lateral)
            point.relative_time = horizon
            previous_horizon = horizon
        self.prediction_writer.write(prediction)
        self.predictions += 1

    def on_clock(self, message: Clock) -> None:
        with self.lock:
            timestamp = message.clock / 1_000_000_000.0
            self.sim_time = timestamp
            if self.started_sim is None:
                self.started_sim = timestamp
            ego = self.find_ego()
            if ego is None:
                return
            if self.actor is None:
                self.spawn_actor(ego)
            elapsed = (
                0.0
                if self.interaction_started_sim is None
                else timestamp - self.interaction_started_sim
            )
            self.drive_actor(elapsed, self.interaction_started_sim is not None)
            self.publish_stack_input(timestamp, elapsed)
            self.frames += 1

    def close(self) -> None:
        with self.lock:
            if self.actor is not None:
                self.actor.destroy()
                self.actor = None
            atomic_json(
                self.stats_path,
                {
                    "schema_version": 1,
                    "frames": self.frames,
                    "predictions": self.predictions,
                    "actor_destroyed": True,
                },
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-scenario-config", type=Path, required=True)
    parser.add_argument("--private-stats", type=Path, required=True)
    args = parser.parse_args()
    runtime = ScenarioRuntime(json.loads(args.private_scenario_config.read_text()), args.private_stats)

    def stop(_signum, _frame):
        runtime.stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("d0_scenario_runtime=READY perfect_perception_input=true diagnosis_access=false", flush=True)
    while not runtime.stopping.wait(0.2):
        pass
    runtime.close()
    # Cyber's CPython teardown can race its callback threads and segfault.
    # State is already atomically persisted and the per-run server reset owns
    # actor cleanup, so bypass interpreter/global-library destructors.
    os._exit(0)


if __name__ == "__main__":
    main()
