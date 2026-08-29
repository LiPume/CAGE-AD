#!/usr/bin/env python3
"""Run one stock Apollo normal-only failed-overtake reference screening."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import threading
import time

import carla
from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import (
    PerceptionObstacle,
    PerceptionObstacles,
)
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles
from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest, RoutingResponse


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def actor_speed(actor) -> float:
    velocity = actor.get_velocity()
    return math.hypot(velocity.x, velocity.y)


def proto_sha256(message) -> str:
    return hashlib.sha256(message.SerializeToString(deterministic=True)).hexdigest()


def header_record(header) -> dict:
    return {
        "timestamp_sec": float(header.timestamp_sec),
        "sequence_num": int(header.sequence_num),
        "module_name": header.module_name,
        "frame_id": header.frame_id,
    }


def vector_record(value) -> list[float]:
    return [float(value.x), float(value.y), float(value.z)]


def transform_record(value) -> dict:
    return {
        "location": vector_record(value.location),
        "rotation_rpy_deg": [
            float(value.rotation.roll),
            float(value.rotation.pitch),
            float(value.rotation.yaw),
        ],
    }


def actor_rectangle_2d(actor) -> list[tuple[float, float]]:
    """Return the actor's oriented bounding rectangle in deterministic corner order."""
    transform = actor.get_transform()
    box = actor.bounding_box
    corners = []
    for dx, dy in (
        (box.extent.x, box.extent.y),
        (box.extent.x, -box.extent.y),
        (-box.extent.x, -box.extent.y),
        (-box.extent.x, box.extent.y),
    ):
        point = transform.transform(carla.Location(
            x=box.location.x + dx,
            y=box.location.y + dy,
            z=box.location.z,
        ))
        corners.append((float(point.x), float(point.y)))
    return corners


def point_segment_distance_2d(point, start, end) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    if denominator <= 1e-18:
        return math.hypot(px - ax, py - ay)
    ratio = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denominator))
    return math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy))


def segments_intersect_2d(a, b, c, d) -> bool:
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    ab_c, ab_d = cross(a, b, c), cross(a, b, d)
    cd_a, cd_b = cross(c, d, a), cross(c, d, b)
    epsilon = 1e-9
    if ((ab_c > epsilon and ab_d < -epsilon) or (ab_c < -epsilon and ab_d > epsilon)) and (
        (cd_a > epsilon and cd_b < -epsilon) or (cd_a < -epsilon and cd_b > epsilon)
    ):
        return True
    return any(
        point_segment_distance_2d(point, start, end) <= epsilon
        for point, start, end in ((c, a, b), (d, a, b), (a, c, d), (b, c, d))
    )


def rectangle_clearance_2d(first, second) -> float:
    edges_first = list(zip(first, first[1:] + first[:1]))
    edges_second = list(zip(second, second[1:] + second[:1]))
    if any(
        segments_intersect_2d(a, b, c, d)
        for a, b in edges_first for c, d in edges_second
    ):
        return 0.0
    return min(
        [point_segment_distance_2d(point, a, b)
         for point in first for a, b in edges_second]
        + [point_segment_distance_2d(point, a, b)
           for point in second for a, b in edges_first]
    )


def set_message_fields(message) -> list[str]:
    return [field.name for field, _value in message.ListFields()]


class ReferenceScreen:
    target_id = 1001

    def __init__(self, manifest: dict, output: Path) -> None:
        self.manifest = manifest
        self.output = output
        self.candidate = manifest["candidate"]
        self.fixed = manifest["fixed_environment"]
        self.client = carla.Client("127.0.0.1", 2000)
        self.client.set_timeout(10)
        self.world = self.client.get_world()
        if not self.world.get_map().name.endswith("/" + self.candidate["map"]):
            raise RuntimeError("CARLA map does not match frozen manifest")
        self.map = self.world.get_map()
        self.lock = threading.RLock()
        self.timeline_path = output.with_name("planning_input_timeline.jsonl")
        self.timeline = self.timeline_path.open("x", encoding="utf-8", buffering=1)
        self.timeline_events = 0
        self.stop_event = threading.Event()
        self.initial_snapshot = self.world.get_snapshot()
        self.samples: list[dict] = []
        self.ego = self.find_ego()
        if self.ego is None:
            raise RuntimeError("exactly one ego_vehicle is required")
        self.spawn_sequence = [{
            "order": 1,
            "kind": "existing_ego",
            "actor_id": int(self.ego.id),
            "world_frame": int(self.world.get_snapshot().frame),
        }]
        self.npc_agent = None
        self.traffic_manager = None
        self.traffic_manager_port = None
        self.npc = self.spawn_npc()
        self.collisions: list[dict] = []
        self.collision_sensor = self.make_collision_sensor()
        self.lane_invasions: list[dict] = []
        self.lane_invasion_sensor = self.make_lane_invasion_sensor()
        self.initial_actor_records = {
            "ego": self.actor_record(self.ego),
            "target_npc": self.actor_record(
                self.npc, physics_control_repr=self.npc_physics_control_repr
            ),
        }
        self.route = {"responses": 0, "accepted": False, "roads": 0}
        self.counts = {
            "clock": 0,
            "perception_published": 0,
            "prediction": 0,
            "target_prediction": 0,
            "target_prediction_with_trajectory": 0,
            "planning_raw": 0,
            "planning_relayed": 0,
            "planning_identity_mismatch": 0,
            "planning": 0,
            "planning_valid": 0,
            "control": 0,
            "localization": 0,
            "chassis": 0,
            "target_heading_commands": 0,
            "target_heading_command_errors": 0,
        }
        self.prediction_probabilities: list[float] = []
        self.sequence = 0
        self.last_clock = None
        self.latest_prediction = None
        self.latest_localization = None
        self.latest_chassis = None
        self.exception = None
        cyber.init("cage_pr826_reference_" + manifest["screening_id"])
        self.node = cyber.Node("cage_pr826_reference_" + manifest["screening_id"])
        self.perception_writer = self.node.create_writer(
            "/apollo/perception/obstacles", PerceptionObstacles, 10
        )
        self.route_writer = self.node.create_writer("/apollo/routing_request", RoutingRequest, 10)
        # The D0 Planning configuration deliberately publishes to planning_raw so a diagnosis
        # interposer can occupy the public interface.  Reference screening has no diagnosis
        # interposer, therefore install a byte-preserving identity relay.  This is plumbing, not
        # an intervention: the same protobuf object is written without changing any field.
        self.planning_writer = self.node.create_writer(
            "/apollo/planning", ADCTrajectory, 10
        )
        self.readers = [
            self.node.create_reader("/clock", Clock, self.on_clock),
            self.node.create_reader("/apollo/routing_response", RoutingResponse, self.on_route),
            self.node.create_reader("/apollo/prediction", PredictionObstacles, self.on_prediction),
            self.node.create_reader(
                "/apollo/localization/pose", LocalizationEstimate, self.on_localization
            ),
            self.node.create_reader("/apollo/canbus/chassis", Chassis, self.on_chassis),
            self.node.create_reader(
                "/apollo/planning_raw", ADCTrajectory, self.on_planning_raw
            ),
            self.node.create_reader("/apollo/planning", ADCTrajectory, self.on_planning),
            self.node.create_reader("/apollo/control", ControlCommand, self.on_control),
        ]

    def find_ego(self):
        actors = [
            actor for actor in self.world.get_actors().filter("vehicle.*")
            if actor.attributes.get("role_name") == "ego_vehicle"
        ]
        return actors[0] if len(actors) == 1 else None

    def spawn_npc(self):
        spec = self.candidate["npc_spawn_carla"]
        transform = carla.Transform(
            carla.Location(x=float(spec["x"]), y=float(spec["y"]), z=float(spec["z"]) + 0.3),
            carla.Rotation(yaw=float(spec["yaw_deg"])),
        )
        blueprint = self.world.get_blueprint_library().find(self.fixed["npc_blueprint"])
        blueprint.set_attribute("role_name", "pr826_reference_lead")
        actor = self.world.try_spawn_actor(blueprint, transform)
        if actor is None:
            raise RuntimeError("failed to spawn frozen reference NPC")
        self.spawn_sequence.append({
            "order": len(self.spawn_sequence) + 1,
            "kind": "target_npc",
            "actor_id": int(actor.id),
            "world_frame": int(self.world.get_snapshot().frame),
        })
        self.npc_physics_control_repr = str(actor.get_physics_control())
        policy = self.candidate.get("npc_policy", {
            "type": "STATIONARY_PHYSICS_DISABLED", "speed_mps": 0.0,
            "traffic_manager_used": False,
        })
        policy_type = policy["type"]
        speed_mps = float(policy.get("speed_mps", 0.0))
        if policy_type == "STATIONARY_PHYSICS_DISABLED":
            actor.set_simulate_physics(False)
            actor.set_target_velocity(carla.Vector3D())
            self.npc_policy_record = {
                "type": policy_type,
                "simulate_physics": False,
                "speed_mps": 0.0,
                "constant_velocity_local_mps": [0.0, 0.0, 0.0],
                "traffic_manager_used": False,
            }
        elif policy_type == "CARLA_CONSTANT_LOCAL_VELOCITY":
            if speed_mps <= 0.0:
                raise RuntimeError("moving NPC policy requires positive speed_mps")
            if policy.get("traffic_manager_used", False):
                raise RuntimeError("reference NPC policy must not use TrafficManager")
            # CARLA 0.9.15 documents enable_constant_velocity() in the actor's local frame.
            # It is used only for the NPC; Apollo remains the sole controller of the ego.
            actor.set_simulate_physics(True)
            actor.enable_constant_velocity(carla.Vector3D(x=speed_mps, y=0.0, z=0.0))
            self.npc_policy_record = {
                "type": policy_type,
                "simulate_physics": True,
                "speed_mps": speed_mps,
                "constant_velocity_local_mps": [speed_mps, 0.0, 0.0],
                "traffic_manager_used": False,
            }
        elif policy_type == "CARLA_CONSTANT_VELOCITY_AGENT":
            if speed_mps <= 0.0:
                raise RuntimeError("moving NPC policy requires positive speed_mps")
            if policy.get("traffic_manager_used", False):
                raise RuntimeError("constant-velocity agent must not use TrafficManager")
            destination = policy.get("destination_carla_xy")
            if not isinstance(destination, list) or len(destination) != 2:
                raise RuntimeError("constant-velocity agent requires destination_carla_xy")
            # CARLA 0.9.15's bundled ConstantVelocityAgent combines the official local-frame
            # constant-velocity primitive with LocalPlanner steering.  Unlike the raw primitive,
            # it follows the map centerline instead of preserving the spawn tangent until it
            # leaves a curved lane.  The NPC alone uses this controller; Apollo remains the sole
            # controller of ego.
            from agents.navigation.constant_velocity_agent import ConstantVelocityAgent
            # The bundled constructor interprets target_speed as km/h for its planner but passes
            # that same numeric value once to enable_constant_velocity(), whose API is m/s.
            # Freeze the actor during planner construction so this one-time unit mismatch cannot
            # move the scenario before observation starts; immediately restore the intended
            # physical state and m/s command afterwards.
            actor.disable_constant_velocity()
            actor.set_simulate_physics(False)
            agent = ConstantVelocityAgent(
                actor,
                target_speed=speed_mps * 3.6,
                opt_dict={
                    "ignore_traffic_lights": True,
                    "ignore_stop_signs": True,
                    "ignore_vehicles": True,
                    "sampling_resolution": 1.0,
                },
                map_inst=self.map,
            )
            self.spawn_sequence.append({
                "order": len(self.spawn_sequence) + 1,
                "kind": "npc_agent_collision_sensor",
                "actor_id": int(agent._collision_sensor.id),
                "world_frame": int(self.world.get_snapshot().frame),
            })
            agent.set_destination(carla.Location(
                x=float(destination[0]), y=float(destination[1]), z=float(spec["z"])
            ))
            actor.disable_constant_velocity()
            actor.set_simulate_physics(True)
            actor.enable_constant_velocity(carla.Vector3D(x=speed_mps, y=0.0, z=0.0))
            self.npc_agent = agent
            self.npc_policy_record = {
                "type": policy_type,
                "simulate_physics": True,
                "speed_mps": speed_mps,
                "constant_velocity_local_mps": [speed_mps, 0.0, 0.0],
                "destination_carla_xy": [float(destination[0]), float(destination[1])],
                "traffic_manager_used": False,
                "controller": "CARLA_0_9_15_BUNDLED_CONSTANT_VELOCITY_AGENT",
            }
        elif policy_type == "CARLA_SYNCHRONOUS_TRAFFIC_MANAGER":
            if speed_mps <= 0.0:
                raise RuntimeError("Traffic Manager NPC policy requires positive speed_mps")
            if not policy.get("traffic_manager_used", False):
                raise RuntimeError("Traffic Manager policy must declare traffic_manager_used=true")
            settings = self.world.get_settings()
            if not settings.synchronous_mode or settings.fixed_delta_seconds is None:
                raise RuntimeError(
                    "Traffic Manager reference requires synchronous world with fixed delta"
                )
            port = int(policy.get("port", 8060))
            if not 1024 <= port <= 65535:
                raise RuntimeError("invalid frozen Traffic Manager port")
            tm_seed = int(policy.get("seed", self.fixed["seed"]))
            if tm_seed != int(self.fixed["seed"]):
                raise RuntimeError("Traffic Manager seed must equal the frozen reference seed")
            destination = policy.get("destination_carla_xy")
            if not isinstance(destination, list) or len(destination) != 2:
                raise RuntimeError("Traffic Manager policy requires destination_carla_xy")
            tm = self.client.get_trafficmanager(port)
            # CARLA's deterministic-mode contract requires world sync first, followed by TM sync
            # and a seed reset after every world reload. The bridge has already performed and
            # attested the deterministic reload before this runner is started.
            tm.set_synchronous_mode(True)
            tm.set_random_device_seed(tm_seed)
            tm.set_hybrid_physics_mode(False)
            actor.set_autopilot(True, port)
            tm.auto_lane_change(actor, False)
            tm.random_left_lanechange_percentage(actor, 0.0)
            tm.random_right_lanechange_percentage(actor, 0.0)
            tm.ignore_vehicles_percentage(actor, 100.0)
            tm.ignore_lights_percentage(actor, 100.0)
            tm.ignore_signs_percentage(actor, 100.0)
            desired_speed_kmh = speed_mps * 3.6
            tm.set_desired_speed(actor, desired_speed_kmh)
            tm.set_path(actor, [carla.Location(
                x=float(destination[0]), y=float(destination[1]), z=float(spec["z"])
            )])
            self.traffic_manager = tm
            self.traffic_manager_port = port
            self.npc_policy_record = {
                "type": policy_type,
                "simulate_physics": True,
                "speed_mps": speed_mps,
                "desired_speed_kmh": desired_speed_kmh,
                "destination_carla_xy": [float(destination[0]), float(destination[1])],
                "traffic_manager_used": True,
                "traffic_manager_port": port,
                "traffic_manager_seed": tm_seed,
                "traffic_manager_synchronous": True,
                "hybrid_physics": False,
                "auto_lane_change": False,
                "random_left_lanechange_percentage": 0.0,
                "random_right_lanechange_percentage": 0.0,
                "ignore_vehicles_percentage": 100.0,
                "ignore_lights_percentage": 100.0,
                "ignore_signs_percentage": 100.0,
                "controller": "CARLA_0_9_15_TRAFFIC_MANAGER",
            }
        elif policy_type == "CARLA_CONSTANT_LOCAL_VELOCITY_LANE_TANGENT":
            if speed_mps <= 0.0:
                raise RuntimeError("lane-tangent NPC policy requires positive speed_mps")
            if policy.get("traffic_manager_used", False):
                raise RuntimeError("lane-tangent NPC policy must not use TrafficManager")
            # Longitudinal motion remains CARLA's documented local constant-velocity primitive.
            # The runner only updates heading from the actor's *current* nearest driving-lane
            # waypoint; it never reads a future pose, future trajectory, or any Apollo output.
            actor.set_simulate_physics(True)
            actor.enable_constant_velocity(carla.Vector3D(x=speed_mps, y=0.0, z=0.0))
            self.npc_policy_record = {
                "type": policy_type,
                "simulate_physics": True,
                "speed_mps": speed_mps,
                "constant_velocity_local_mps": [speed_mps, 0.0, 0.0],
                "traffic_manager_used": False,
                "heading_source": "CURRENT_NEAREST_DRIVING_LANE_TANGENT",
                "future_ground_truth_used": False,
                "command_transport": "APPLY_BATCH_SYNC_NO_TICK",
                "position_projection": False,
                "controller": "CARLA_LOCAL_VELOCITY_WITH_CURRENT_LANE_HEADING",
            }
        else:
            actor.destroy()
            raise RuntimeError(f"unsupported frozen NPC policy: {policy_type}")
        return actor

    def make_collision_sensor(self):
        blueprint = self.world.get_blueprint_library().find("sensor.other.collision")
        sensor = self.world.spawn_actor(blueprint, carla.Transform(), attach_to=self.ego)

        def callback(event) -> None:
            other = event.other_actor
            impulse = event.normal_impulse
            self.collisions.append({
                "frame": event.frame,
                "counterpart": other.attributes.get("role_name") or other.type_id,
                "impulse": math.sqrt(impulse.x ** 2 + impulse.y ** 2 + impulse.z ** 2),
            })

        sensor.listen(callback)
        self.spawn_sequence.append({
            "order": len(self.spawn_sequence) + 1,
            "kind": "collision_sensor",
            "actor_id": int(sensor.id),
            "world_frame": int(self.world.get_snapshot().frame),
        })
        return sensor

    def make_lane_invasion_sensor(self):
        blueprint = self.world.get_blueprint_library().find("sensor.other.lane_invasion")
        sensor = self.world.spawn_actor(blueprint, carla.Transform(), attach_to=self.ego)

        def callback(event) -> None:
            self.lane_invasions.append({
                "frame": int(event.frame),
                "markings": [{
                    "type": str(marking.type),
                    "color": str(marking.color),
                    "lane_change": str(marking.lane_change),
                    "width": float(marking.width),
                } for marking in event.crossed_lane_markings],
            })

        sensor.listen(callback)
        self.spawn_sequence.append({
            "order": len(self.spawn_sequence) + 1,
            "kind": "lane_invasion_sensor",
            "actor_id": int(sensor.id),
            "world_frame": int(self.world.get_snapshot().frame),
        })
        return sensor

    def write_timeline(self, event: str, payload: dict) -> None:
        with self.lock:
            record = {"event": event, "ordinal": self.timeline_events, **payload}
            self.timeline.write(json.dumps(record, sort_keys=True) + "\n")
            self.timeline_events += 1

    @staticmethod
    def fill_obstacle(message, actor, timestamp: float) -> None:
        transform = actor.get_transform()
        extent = actor.bounding_box.extent
        velocity = actor.get_velocity()
        message.id = ReferenceScreen.target_id
        message.position.x = transform.location.x
        message.position.y = -transform.location.y
        message.position.z = max(transform.location.z, 1e-9)
        message.theta = -math.radians(transform.rotation.yaw)
        message.velocity.x = velocity.x
        message.velocity.y = -velocity.y
        message.velocity.z = 1e-9
        message.length = extent.x * 2.0
        message.width = extent.y * 2.0
        message.height = extent.z * 2.0
        message.type = PerceptionObstacle.VEHICLE
        message.timestamp = timestamp
        message.tracking_time = timestamp
        message.confidence = 1.0
        for x, y in ((extent.x, extent.y), (extent.x, -extent.y),
                     (-extent.x, -extent.y), (-extent.x, extent.y)):
            point = transform.transform(carla.Location(x=x, y=y, z=0.0))
            polygon = message.polygon_point.add()
            polygon.x = point.x
            polygon.y = -point.y
            polygon.z = max(point.z, 1e-9)

    def on_clock(self, message: Clock) -> None:
        try:
            timestamp = message.clock / 1_000_000_000.0
            perception = PerceptionObstacles()
            perception.header.timestamp_sec = timestamp
            perception.header.module_name = "cage_pr826_reference_perfect_perception"
            self.sequence += 1
            perception.header.sequence_num = self.sequence
            obstacle = perception.perception_obstacle.add()
            self.fill_obstacle(obstacle, self.npc, timestamp)
            self.perception_writer.write(perception)
            with self.lock:
                self.counts["clock"] += 1
                self.counts["perception_published"] += 1
                self.last_clock = timestamp
        except Exception as exc:  # pragma: no cover - runtime guard
            self.exception = f"{type(exc).__name__}: {exc}"
            self.stop_event.set()

    def on_route(self, message: RoutingResponse) -> None:
        passages = []
        for road in message.road:
            for passage_index, passage in enumerate(road.passage):
                passages.append({
                    "road_id": str(road.id),
                    "passage_index": passage_index,
                    "can_exit": bool(passage.can_exit),
                    "change_lane_type": int(passage.change_lane_type),
                    "segments": [{
                        "lane_id": str(segment.id),
                        "start_s": float(segment.start_s),
                        "end_s": float(segment.end_s),
                    } for segment in passage.segment],
                })
        route_record = {
            "clock_s": self.last_clock,
            "header": header_record(message.header),
            "accepted": bool(message.status.error_code == 0 and len(message.road) > 0),
            "road_count": len(message.road),
            "passages": passages,
        }
        with self.lock:
            self.route["responses"] += 1
            accepted = message.status.error_code == 0 and len(message.road) > 0
            self.route["accepted"] = self.route["accepted"] or accepted
            self.route["roads"] = max(self.route["roads"], len(message.road))
        self.write_timeline("routing_response", route_record)

    def on_prediction(self, message: PredictionObstacles) -> None:
        target = None
        target_record = None
        for obstacle in message.prediction_obstacle:
            if obstacle.perception_obstacle.id != self.target_id:
                continue
            target = obstacle
            trajectory_records = []
            for trajectory in obstacle.trajectory:
                points = trajectory.trajectory_point
                trajectory_records.append({
                    "probability": float(trajectory.probability),
                    "point_count": len(points),
                    "sha256": proto_sha256(trajectory),
                    "first_point": None if not points else {
                        "relative_time": float(points[0].relative_time),
                        "x": float(points[0].path_point.x),
                        "y": float(points[0].path_point.y),
                        "v": float(points[0].v),
                    },
                    "last_point": None if not points else {
                        "relative_time": float(points[-1].relative_time),
                        "x": float(points[-1].path_point.x),
                        "y": float(points[-1].path_point.y),
                        "v": float(points[-1].v),
                    },
                })
            target_record = {
                "is_static": bool(obstacle.is_static),
                "source_timestamp_sec": float(obstacle.timestamp),
                "trajectory_count": len(obstacle.trajectory),
                "trajectory_point_count": sum(
                    len(trajectory.trajectory_point) for trajectory in obstacle.trajectory
                ),
                "probabilities": [float(value.probability) for value in obstacle.trajectory],
                "trajectories": trajectory_records,
                "perception_speed_mps": math.hypot(
                    obstacle.perception_obstacle.velocity.x,
                    obstacle.perception_obstacle.velocity.y,
                ),
            }
            break
        received = {
            "header": header_record(message.header),
            "sha256": proto_sha256(message),
            "clock_s": self.last_clock,
            "target": target_record,
        }
        with self.lock:
            self.counts["prediction"] += 1
            self.latest_prediction = received
            if target is not None:
                self.counts["target_prediction"] += 1
                if any(trajectory.trajectory_point for trajectory in target.trajectory):
                    self.counts["target_prediction_with_trajectory"] += 1
                self.prediction_probabilities.extend(
                    float(trajectory.probability) for trajectory in target.trajectory
                )
        self.write_timeline("prediction", received)

    def on_localization(self, message: LocalizationEstimate) -> None:
        received = {
            "header": header_record(message.header),
            "measurement_time": float(message.measurement_time),
            "sha256": proto_sha256(message),
            "clock_s": self.last_clock,
        }
        with self.lock:
            self.counts["localization"] += 1
            self.latest_localization = received

    def on_chassis(self, message: Chassis) -> None:
        received = {
            "header": header_record(message.header),
            "speed_mps": float(message.speed_mps),
            "sha256": proto_sha256(message),
            "clock_s": self.last_clock,
        }
        with self.lock:
            self.counts["chassis"] += 1
            self.latest_chassis = received

    def on_planning(self, message: ADCTrajectory) -> None:
        with self.lock:
            self.counts["planning"] += 1
            if len(message.trajectory_point) > 0 and message.total_path_length > 1.0:
                self.counts["planning_valid"] += 1

    def on_planning_raw(self, message: ADCTrajectory) -> None:
        before = message.SerializeToString(deterministic=True)
        planning_data = message.debug.planning_data
        target_debug = []
        for obstacle in planning_data.obstacle:
            if obstacle.id != str(self.target_id):
                continue
            target_debug.append({
                "id": obstacle.id,
                "sl_boundary": {
                    "start_s": float(obstacle.sl_boundary.start_s),
                    "end_s": float(obstacle.sl_boundary.end_s),
                    "start_l": float(obstacle.sl_boundary.start_l),
                    "end_l": float(obstacle.sl_boundary.end_l),
                },
                "decision_tags": [{
                    "decider_tag": tag.decider_tag,
                    "decision_fields": set_message_fields(tag.decision),
                } for tag in obstacle.decision_tag],
            })
        embedded = {
            "prediction_header": header_record(planning_data.prediction_header),
            "localization_header": header_record(planning_data.adc_position.header),
            "localization_measurement_time": float(planning_data.adc_position.measurement_time),
            "localization_sha256": proto_sha256(planning_data.adc_position),
            "chassis_header": header_record(planning_data.chassis.header),
            "chassis_speed_mps": float(planning_data.chassis.speed_mps),
            "chassis_sha256": proto_sha256(planning_data.chassis),
        }
        plan_timestamp = float(message.header.timestamp_sec)
        record = {
            "clock_s": self.last_clock,
            "header": header_record(message.header),
            "sha256": hashlib.sha256(before).hexdigest(),
            # Prediction/Planning headers use Apollo wall-clock epoch time in this stack, while
            # bridge Localization/Chassis headers use CARLA simulation time. Never subtract the
            # two domains. Each age below is computed against its matching clock domain.
            "input_ages_s": {
                "prediction_wall_clock": (
                    None if embedded["prediction_header"]["timestamp_sec"] <= 0.0 else
                    plan_timestamp - embedded["prediction_header"]["timestamp_sec"]
                ),
                "localization_sim_clock": (
                    None if self.last_clock is None or
                    embedded["localization_header"]["timestamp_sec"] <= 0.0 else
                    self.last_clock - embedded["localization_header"]["timestamp_sec"]
                ),
                "chassis_sim_clock": (
                    None if self.last_clock is None or
                    embedded["chassis_header"]["timestamp_sec"] <= 0.0 else
                    self.last_clock - embedded["chassis_header"]["timestamp_sec"]
                ),
            },
            "embedded_inputs": embedded,
            "latest_channel_inputs": {
                "prediction": self.latest_prediction,
                "localization": self.latest_localization,
                "chassis": self.latest_chassis,
            },
            "scenario": {
                "scenario_type": int(planning_data.scenario.scenario_type),
                "stage_type": int(planning_data.scenario.stage_type),
                "scenario_plugin_type": planning_data.scenario.scenario_plugin_type,
                "stage_plugin_type": planning_data.scenario.stage_plugin_type,
                "message": planning_data.scenario.msg,
            },
            "init_point": {
                "relative_time": float(planning_data.init_point.relative_time),
                "s": float(planning_data.init_point.path_point.s),
                "v": float(planning_data.init_point.v),
                "a": float(planning_data.init_point.a),
            },
            "reference_lines": [{
                "id": value.id,
                "length": float(value.length),
                "cost": float(value.cost),
                "is_change_lane_path": bool(value.is_change_lane_path),
                "is_drivable": bool(value.is_drivable),
                "is_offroad": bool(value.is_offroad),
            } for value in planning_data.reference_line],
            "paths": [{
                "name": value.name,
                "point_count": len(value.path_point),
                "first_point": None if not value.path_point else {
                    "x": float(value.path_point[0].x),
                    "y": float(value.path_point[0].y),
                    "s": float(value.path_point[0].s),
                },
                "last_point": None if not value.path_point else {
                    "x": float(value.path_point[-1].x),
                    "y": float(value.path_point[-1].y),
                    "s": float(value.path_point[-1].s),
                },
            } for value in planning_data.path],
            "speed_plans": [{"name": value.name, "point_count": len(value.speed_point)}
                            for value in planning_data.speed_plan],
            "target_obstacle_debug": target_debug,
            "front_clear_distance": float(planning_data.front_clear_distance),
            "trajectory": {
                "point_count": len(message.trajectory_point),
                "total_path_length": float(message.total_path_length),
                "total_path_time": float(message.total_path_time),
                "trajectory_type": int(message.trajectory_type),
                "is_replan": bool(message.is_replan),
                "replan_reason": message.replan_reason,
                "estop": bool(message.estop.is_estop),
                "main_decision_fields": set_message_fields(message.decision.main_decision),
                "first_point": None if not message.trajectory_point else {
                    "x": float(message.trajectory_point[0].path_point.x),
                    "y": float(message.trajectory_point[0].path_point.y),
                    "s": float(message.trajectory_point[0].path_point.s),
                },
                "last_point": None if not message.trajectory_point else {
                    "x": float(message.trajectory_point[-1].path_point.x),
                    "y": float(message.trajectory_point[-1].path_point.y),
                    "s": float(message.trajectory_point[-1].path_point.s),
                },
            },
            "latency": {
                "total_time_ms": float(message.latency_stats.total_time_ms),
                "init_frame_time_ms": float(message.latency_stats.init_frame_time_ms),
                "tasks": [{"name": task.name, "time_ms": float(task.time_ms)}
                          for task in message.latency_stats.task_stats],
            },
        }
        self.write_timeline("planning_raw", record)
        self.planning_writer.write(message)
        after = message.SerializeToString(deterministic=True)
        with self.lock:
            self.counts["planning_raw"] += 1
            self.counts["planning_relayed"] += 1
            if before != after:
                self.counts["planning_identity_mismatch"] += 1

    def on_control(self, message: ControlCommand) -> None:
        lon = message.debug.simple_lon_debug
        received = {
            "clock_s": self.last_clock,
            "header": header_record(message.header),
            "sha256": proto_sha256(message),
            "throttle": float(message.throttle),
            "brake": float(message.brake),
            "steering_target": float(message.steering_target),
            "steering_rate": float(message.steering_rate),
            "speed": float(message.speed),
            "acceleration": float(message.acceleration),
            "gear_location": int(message.gear_location),
            "is_in_safe_mode": bool(message.is_in_safe_mode),
            "simple_lon_debug": {
                "speed_reference": float(lon.speed_reference),
                "speed_error": float(lon.speed_error),
                "current_speed": float(lon.current_speed),
                "acceleration_reference": float(lon.acceleration_reference),
                "acceleration_cmd": float(lon.acceleration_cmd),
                "acceleration_lookup": float(lon.acceleration_lookup),
                "speed_lookup": float(lon.speed_lookup),
                "calibration_value": float(lon.calibration_value),
                "throttle_cmd": float(lon.throttle_cmd),
                "brake_cmd": float(lon.brake_cmd),
            },
        }
        with self.lock:
            self.counts["control"] += 1
        self.write_timeline("control", received)

    def publish_route(self) -> None:
        request = RoutingRequest()
        request.header.module_name = "cage_pr826_reference_runner"
        request.is_start_pose_set = True
        route_waypoints = self.candidate.get("route_waypoints_apollo_xy", [
            self.candidate["route_start_apollo_xy"],
            self.candidate["route_end_apollo_xy"],
        ])
        for x, y in route_waypoints:
            waypoint = request.waypoint.add()
            waypoint.pose.x = float(x)
            waypoint.pose.y = float(y)
            waypoint.heading = -math.radians(float(self.candidate["ego_spawn_carla"]["yaw_deg"]))
        deadline = time.monotonic() + 12.0
        sequence = 0
        self.write_timeline("routing_publish_start", {
            "clock_s": self.last_clock,
            "start_xy": self.candidate["route_start_apollo_xy"],
            "end_xy": self.candidate["route_end_apollo_xy"],
            "waypoints_xy": route_waypoints,
        })
        while time.monotonic() < deadline and not self.route["accepted"]:
            sequence += 1
            request.header.sequence_num = sequence
            request.header.timestamp_sec = time.time()
            self.route_writer.write(request)
            self.stop_event.wait(0.5)

    def sample(self, elapsed: float, origin, forward, right) -> dict:
        ego_location = self.ego.get_location()
        npc_location = self.npc.get_location()
        npc_transform = self.npc.get_transform()
        npc_velocity = self.npc.get_velocity()
        dx, dy = ego_location.x - origin.x, ego_location.y - origin.y
        ndx, ndy = npc_location.x - origin.x, npc_location.y - origin.y
        ego_s = dx * forward.x + dy * forward.y
        ego_l = dx * right.x + dy * right.y
        npc_s = ndx * forward.x + ndy * forward.y
        waypoint = self.map.get_waypoint(
            ego_location, project_to_road=True, lane_type=carla.LaneType.Driving
        )
        npc_waypoint = self.map.get_waypoint(
            npc_location, project_to_road=True, lane_type=carla.LaneType.Driving
        )
        npc_lane_center_distance = math.hypot(
            npc_location.x - npc_waypoint.transform.location.x,
            npc_location.y - npc_waypoint.transform.location.y,
        )
        success_region = self.candidate.get("success_region_carla")
        success_region_distance = None
        if success_region:
            center_x, center_y = success_region["center_xy"]
            success_region_distance = math.hypot(
                ego_location.x - float(center_x), ego_location.y - float(center_y)
            )
        return {
            "elapsed_s": elapsed,
            "simulation_elapsed_seconds": float(
                self.world.get_snapshot().timestamp.elapsed_seconds
            ),
            "ego_carla_xy": [ego_location.x, ego_location.y],
            "npc_carla_xy": [npc_location.x, npc_location.y],
            "npc_velocity_carla_xyz_mps": vector_record(npc_velocity),
            "npc_yaw_deg": float(npc_transform.rotation.yaw),
            "ego_speed_mps": actor_speed(self.ego),
            "npc_speed_mps": actor_speed(self.npc),
            "ego_longitudinal_m": ego_s,
            "ego_lateral_m": ego_l,
            "npc_longitudinal_m": npc_s,
            "pass_margin_m": ego_s - npc_s,
            "center_separation_m": ego_location.distance(npc_location),
            "bbox_clearance_2d_m": rectangle_clearance_2d(
                actor_rectangle_2d(self.ego), actor_rectangle_2d(self.npc)
            ),
            "carla_road_id": waypoint.road_id,
            "carla_lane_id": waypoint.lane_id,
            "npc_carla_road_id": npc_waypoint.road_id,
            "npc_carla_lane_id": npc_waypoint.lane_id,
            "npc_lane_center_distance_m": npc_lane_center_distance,
            "success_region_distance_m": success_region_distance,
            "carla_frame": int(self.world.get_snapshot().frame),
        }

    @staticmethod
    def carla_settings_record(settings) -> dict:
        names = (
            "synchronous_mode", "fixed_delta_seconds", "substepping",
            "max_substep_delta_time", "max_substeps", "no_rendering_mode",
            "deterministic_ragdolls", "tile_stream_distance", "actor_active_distance",
        )
        return {name: getattr(settings, name, None) for name in names}

    @staticmethod
    def actor_record(actor, physics_control_repr: str | None = None) -> dict:
        control_text = physics_control_repr
        if control_text is None:
            control_text = str(actor.get_physics_control())
        return {
            "id": int(actor.id),
            "type_id": actor.type_id,
            "role_name": actor.attributes.get("role_name"),
            "transform": transform_record(actor.get_transform()),
            "velocity": vector_record(actor.get_velocity()),
            "angular_velocity": vector_record(actor.get_angular_velocity()),
            "bounding_box_extent": vector_record(actor.bounding_box.extent),
            "physics_control_repr": control_text,
            "physics_control_sha256": hashlib.sha256(control_text.encode()).hexdigest(),
        }

    def run(self) -> dict:
        self.publish_route()
        if not self.route["accepted"]:
            return self.finish([], "REJECT", "ROUTE_NOT_ACCEPTED")
        initial = self.ego.get_transform()
        origin = initial.location
        forward, right = initial.get_forward_vector(), initial.get_right_vector()
        samples = self.samples
        start_snapshot = self.world.get_snapshot()
        started = start_snapshot.timestamp.elapsed_seconds
        self.write_timeline("observation_start", {
            "clock_s": self.last_clock,
            "carla_frame": int(start_snapshot.frame),
            "simulation_elapsed_seconds": float(start_snapshot.timestamp.elapsed_seconds),
        })
        duration = float(self.candidate.get(
            "observation_window_s", self.fixed["observation_window_s"]
        ))
        while not self.stop_event.is_set():
            snapshot = self.world.wait_for_tick(5)
            elapsed = snapshot.timestamp.elapsed_seconds - started
            if self.npc_agent is not None:
                npc_control = self.npc_agent.run_step()
                self.npc.apply_control(npc_control)
                # Reference-runner and CARLA tick ownership live in different clients.  Make the
                # local-speed command the last RPC for the next synchronous frame; otherwise the
                # steering control and constant-velocity RPC alternate, yielding one moving and
                # one near-zero velocity frame and an artificial 50% Prediction trajectory gate.
                self.npc.enable_constant_velocity(carla.Vector3D(
                    x=float(self.npc_policy_record["speed_mps"]), y=0.0, z=0.0
                ))
            elif self.npc_policy_record["type"] == (
                "CARLA_CONSTANT_LOCAL_VELOCITY_LANE_TANGENT"
            ):
                transform = self.npc.get_transform()
                waypoint = self.map.get_waypoint(
                    transform.location,
                    project_to_road=True,
                    lane_type=carla.LaneType.Driving,
                )
                if waypoint is None:
                    raise RuntimeError("lane-tangent policy lost nearest driving waypoint")
                # Normalize equivalent accumulated CARLA map headings (for example -450 deg)
                # before applying them. Position, roll and pitch are preserved byte-semantically
                # as floating-point fields from the current actor transform.
                transform.rotation.yaw = (
                    (float(waypoint.transform.rotation.yaw) + 180.0) % 360.0
                ) - 180.0
                responses = self.client.apply_batch_sync([
                    carla.command.ApplyTransform(int(self.npc.id), transform)
                ], False)
                self.counts["target_heading_commands"] += 1
                errors = [response.error for response in responses if response.has_error()]
                if errors:
                    self.counts["target_heading_command_errors"] += len(errors)
                    raise RuntimeError(
                        "lane-tangent batch command failed: " + "; ".join(errors)
                    )
            samples.append(self.sample(elapsed, origin, forward, right))
            if elapsed >= duration:
                break
        return self.finish(samples)

    def finish(self, samples: list[dict], forced_status: str | None = None,
               forced_reject: str | None = None) -> dict:
        oracle = self.fixed["success_oracle"]
        counts = dict(self.counts)
        max_lateral = max((abs(s["ego_lateral_m"]) for s in samples), default=0.0)
        max_pass_margin = max((s["pass_margin_m"] for s in samples), default=-math.inf)
        distinct_lanes = sorted({s["carla_lane_id"] for s in samples})
        target_prediction = counts["target_prediction"]
        trajectory_coverage = (
            counts["target_prediction_with_trajectory"] / target_prediction
            if target_prediction else 0.0
        )
        minimum_trajectory_coverage = float(
            oracle.get("minimum_target_prediction_trajectory_coverage", 0.0)
        )
        allowed_overtake_lanes = set(self.candidate.get("allowed_overtake_lane_ids", []))
        entered_allowed_overtake_lane = (
            not allowed_overtake_lanes or bool(allowed_overtake_lanes.intersection(distinct_lanes))
        )
        success_region = self.candidate.get("success_region_carla")
        success_region_reached = True
        success_region_first_reached_elapsed_s = None
        if success_region:
            success_samples = [
                sample for sample in samples
                if sample["carla_road_id"] == int(success_region["road_id"])
                and sample["carla_lane_id"] == int(success_region["lane_id"])
                and sample["success_region_distance_m"] is not None
                and sample["success_region_distance_m"] <= float(success_region["radius_m"])
            ]
            success_region_reached = bool(success_samples)
            if success_samples:
                success_region_first_reached_elapsed_s = float(
                    success_samples[0]["elapsed_s"]
                )
        planning_channel_coverage = (
            counts["planning"] / counts["clock"] if counts["clock"] else 0.0
        )
        planning_valid_ratio = (
            counts["planning_valid"] / counts["planning"] if counts["planning"] else 0.0
        )
        expected_control_per_clock = float(oracle.get("expected_control_per_clock", 5.0))
        control_channel_coverage = (
            counts["control"] / (counts["clock"] * expected_control_per_clock)
            if counts["clock"] and expected_control_per_clock > 0.0 else 0.0
        )
        allowed_markings = set(
            self.candidate.get("allowed_lane_crossing_marking_signatures", [])
        )
        observed_markings = [
            "|".join((marking["type"], marking["color"], marking["lane_change"]))
            for event in self.lane_invasions for marking in event["markings"]
        ]
        illegal_lane_invasion_count = sum(
            signature not in allowed_markings for signature in observed_markings
        )
        infrastructure_ok = (
            self.route["accepted"]
            and counts["planning_raw"] >= int(oracle["minimum_planning_messages"])
            and counts["planning_relayed"] == counts["planning_raw"]
            and counts["planning_identity_mismatch"] == 0
            and counts["planning"] >= int(oracle["minimum_planning_messages"])
            and counts["control"] >= int(oracle["minimum_control_messages"])
            and counts["target_prediction"] >= int(oracle["minimum_target_prediction_messages"])
            and planning_channel_coverage >= float(
                oracle.get("minimum_planning_channel_coverage", 0.0)
            )
            and control_channel_coverage >= float(
                oracle.get("minimum_control_channel_coverage", 0.0)
            )
            and planning_valid_ratio >= float(
                oracle.get("minimum_planning_valid_ratio", 0.0)
            )
            and self.exception is None
        )
        overtake = (
            max_pass_margin >= float(oracle["minimum_pass_margin_m"])
            and max_lateral >= float(oracle["minimum_lateral_excursion_m"])
        )
        if forced_status:
            status, reject = forced_status, forced_reject
        elif not infrastructure_ok:
            status, reject = "REJECT", "REFERENCE_INFRASTRUCTURE_INVALID"
        elif self.collisions:
            status, reject = "REJECT", "REFERENCE_COLLISION"
        elif illegal_lane_invasion_count:
            status, reject = "REJECT", "ILLEGAL_LANE_INVASION"
        elif trajectory_coverage < minimum_trajectory_coverage:
            status, reject = "REJECT", "PREDICTION_TRAJECTORY_COVERAGE_BELOW_GATE"
        elif not entered_allowed_overtake_lane:
            status, reject = "REJECT", "ALLOWED_OVERTAKE_LANE_NOT_ENTERED"
        elif not overtake:
            status, reject = "REJECT", "STOCK_REFERENCE_NO_OVERTAKE"
        elif not success_region_reached:
            status, reject = "REJECT", "SUCCESS_REGION_NOT_REACHED"
        else:
            status, reject = "SCREENING_PASS", None
        metrics = {
            "route": dict(self.route),
            "counts": counts,
            "collision_count": len(self.collisions),
            "minimum_center_separation_m": min(
                (sample["center_separation_m"] for sample in samples), default=None
            ),
            "minimum_bbox_clearance_2d_m": min(
                (sample["bbox_clearance_2d_m"] for sample in samples), default=None
            ),
            "max_abs_lateral_excursion_m": max_lateral,
            "max_pass_margin_m": None if max_pass_margin == -math.inf else max_pass_margin,
            "distinct_carla_lane_ids": distinct_lanes,
            "overtake_success": overtake,
            "infrastructure_valid": infrastructure_ok,
            "prediction_probability_min": min(self.prediction_probabilities, default=None),
            "prediction_probability_max": max(self.prediction_probabilities, default=None),
            "target_prediction_trajectory_coverage": trajectory_coverage,
            "minimum_target_prediction_trajectory_coverage": minimum_trajectory_coverage,
            "entered_allowed_overtake_lane": entered_allowed_overtake_lane,
            "allowed_overtake_lane_ids": sorted(allowed_overtake_lanes),
            "success_region_reached": success_region_reached,
            "success_region_first_reached_elapsed_s": (
                success_region_first_reached_elapsed_s
            ),
            "success_region": success_region,
            "runtime_exception": self.exception,
            "lane_invasion_event_count": len(self.lane_invasions),
            "observed_lane_crossing_marking_signatures": sorted(set(observed_markings)),
            "allowed_lane_crossing_marking_signatures": sorted(allowed_markings),
            "illegal_lane_invasion_count": illegal_lane_invasion_count,
            "planning_channel_coverage": planning_channel_coverage,
            "planning_valid_ratio": planning_valid_ratio,
            "control_channel_coverage": control_channel_coverage,
            "expected_control_per_clock": expected_control_per_clock,
            "timeline_event_count": self.timeline_events,
        }
        self.timeline.flush()
        return {
            "schema_version": 1,
            "screening_id": self.manifest["screening_id"],
            "phase": self.manifest.get("phase", "NORMAL_ONLY_REFERENCE"),
            "admission_evidence": bool(self.manifest.get("admission_evidence", True)),
            "admission": {"status": status, "reject_code": reject},
            "metrics": metrics,
            "collisions": self.collisions,
            "lane_invasions": self.lane_invasions,
            "determinism": {
                "map": self.map.name,
                "initial_snapshot": {
                    "frame": int(self.initial_snapshot.frame),
                    "elapsed_seconds": float(self.initial_snapshot.timestamp.elapsed_seconds),
                },
                "settings": self.carla_settings_record(self.world.get_settings()),
                "traffic_manager": {
                    "used": bool(self.npc_policy_record.get("traffic_manager_used", False)),
                    "port": self.npc_policy_record.get("traffic_manager_port"),
                    "seed": self.npc_policy_record.get("traffic_manager_seed"),
                    "synchronous": self.npc_policy_record.get(
                        "traffic_manager_synchronous"
                    ),
                    "hybrid_physics": self.npc_policy_record.get("hybrid_physics"),
                },
                "spawn_sequence": self.spawn_sequence,
                "actors_at_runtime_start": self.initial_actor_records,
                "npc_policy": dict(self.npc_policy_record),
                "planning_overrides": dict(self.candidate.get("planning_overrides", {})),
                "seed": self.fixed["seed"],
            },
            "artifacts": {"planning_input_timeline": str(self.timeline_path)},
            "samples": samples,
        }

    def close(self) -> None:
        if self.lane_invasion_sensor is not None:
            try:
                self.lane_invasion_sensor.stop()
                self.lane_invasion_sensor.destroy()
            except RuntimeError:
                pass
        if self.collision_sensor is not None:
            try:
                self.collision_sensor.stop()
                self.collision_sensor.destroy()
            except RuntimeError:
                pass
        if self.npc is not None:
            try:
                if self.npc_agent is not None:
                    self.npc_agent.destroy_sensor()
                if self.traffic_manager is not None:
                    self.npc.set_autopilot(False, int(self.traffic_manager_port))
                if self.npc_policy_record["type"] in {
                    "CARLA_CONSTANT_LOCAL_VELOCITY", "CARLA_CONSTANT_VELOCITY_AGENT",
                    "CARLA_CONSTANT_LOCAL_VELOCITY_LANE_TANGENT",
                }:
                    self.npc.disable_constant_velocity()
                self.npc.destroy()
            except RuntimeError:
                pass
        if self.traffic_manager is not None:
            try:
                # CARLA requires the TM synchronous server to be disabled before its owning
                # client exits; the bridge remains the sole world tick owner until stack cleanup.
                self.traffic_manager.set_synchronous_mode(False)
            except RuntimeError:
                pass
        if self.timeline is not None:
            self.timeline.flush()
            self.timeline.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    runtime = ReferenceScreen(manifest, args.output)

    def stop(_signum, _frame) -> None:
        runtime.stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    result = None
    try:
        result = runtime.run()
        atomic_json(args.output, result)
    except Exception as exc:  # preserve failed-run evidence instead of losing the run
        runtime.exception = f"{type(exc).__name__}: {exc}"
        result = {
            "schema_version": 1,
            "screening_id": manifest["screening_id"],
            "phase": manifest.get("phase", "NORMAL_ONLY_REFERENCE"),
            "admission_evidence": bool(manifest.get("admission_evidence", True)),
            "admission": {"status": "REJECT", "reject_code": "RUNTIME_EXCEPTION"},
            "metrics": {
                "counts": dict(runtime.counts),
                "runtime_exception": runtime.exception,
                "timeline_event_count": runtime.timeline_events,
            },
            "samples": runtime.samples,
        }
        atomic_json(args.output, result)
    finally:
        runtime.close()
    # Cyber's Python teardown can block after all evidence has been flushed. This process owns
    # no other resources after close(), so use the same bounded exit pattern as scenario_runtime.
    os._exit(0 if result["admission"]["status"] == "SCREENING_PASS" else 3)


if __name__ == "__main__":
    main()
