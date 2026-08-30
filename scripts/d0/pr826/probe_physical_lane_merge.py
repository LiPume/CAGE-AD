#!/usr/bin/env python3
"""Probe a CARLA-physics lane merge without Apollo or pose/velocity overrides."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics

import carla


def clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def smoothstep(value: float) -> float:
    value = clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def wrap_radians(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def pure_pursuit_steer(
    transform: carla.Transform,
    target: carla.Location,
    wheelbase_m: float,
    maximum_steer_rad: float,
) -> float:
    """Return a physical Ackermann steering angle toward a world-space target."""
    yaw = math.radians(float(transform.rotation.yaw))
    dx = float(target.x - transform.location.x)
    dy = float(target.y - transform.location.y)
    right_x, right_y = -math.sin(yaw), math.cos(yaw)
    local_y = dx * right_x + dy * right_y
    distance_sq = max(0.25, dx * dx + dy * dy)
    angle = math.atan2(2.0 * wheelbase_m * local_y, distance_sq)
    return clamp(angle, -maximum_steer_rad, maximum_steer_rad)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def lane_waypoint(carla_map, location, desired_lane_id: int):
    seed = carla_map.get_waypoint(
        location, project_to_road=True, lane_type=carla.LaneType.Driving
    )
    if seed is None:
        raise RuntimeError("no driving waypoint for actor")
    queue = [seed]
    visited: set[tuple[int, int]] = set()
    while queue and len(visited) < 8:
        waypoint = queue.pop(0)
        key = (int(waypoint.road_id), int(waypoint.lane_id))
        if key in visited:
            continue
        visited.add(key)
        if int(waypoint.lane_id) == int(desired_lane_id):
            return waypoint
        for adjacent in (waypoint.get_left_lane(), waypoint.get_right_lane()):
            if adjacent is not None and adjacent.lane_type == carla.LaneType.Driving:
                queue.append(adjacent)
    raise RuntimeError(
        f"could not resolve lane {desired_lane_id}; seed={seed.road_id}/{seed.lane_id}"
    )


def next_waypoint(waypoint, distance_m: float):
    options = waypoint.next(distance_m)
    if not options:
        raise RuntimeError(f"lane {waypoint.road_id}/{waypoint.lane_id} has no next waypoint")
    same_lane = [item for item in options if item.lane_id == waypoint.lane_id]
    return (same_lane or options)[0]


def run(args) -> dict:
    client = carla.Client(args.host, args.port)
    client.set_timeout(20.0)
    world = client.load_world(args.map)
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = args.fixed_delta_seconds
    settings.substepping = True
    settings.max_substep_delta_time = 0.01
    settings.max_substeps = 10
    world.apply_settings(settings)
    world.tick()

    blueprint = world.get_blueprint_library().find(args.blueprint)
    if blueprint.has_attribute("role_name"):
        blueprint.set_attribute("role_name", "p2m_physics_probe")
    if blueprint.has_attribute("color"):
        colors = blueprint.get_attribute("color").recommended_values
        if colors:
            blueprint.set_attribute("color", colors[0])
    spawn = carla.Transform(
        carla.Location(x=args.spawn_x, y=args.spawn_y, z=args.spawn_z),
        carla.Rotation(yaw=args.spawn_yaw),
    )
    actor = world.try_spawn_actor(blueprint, spawn)
    if actor is None:
        raise RuntimeError("Microlino spawn failed")

    collision_events: list[dict] = []
    collision_bp = world.get_blueprint_library().find("sensor.other.collision")
    collision = world.spawn_actor(collision_bp, carla.Transform(), attach_to=actor)
    collision.listen(lambda event: collision_events.append({
        "frame": int(event.frame), "other_actor_id": int(event.other_actor.id)
    }))

    samples = []
    try:
        # Materialize the actor before reading its pose or lane, then let suspension settle.
        first_frame = world.tick()
        for _ in range(10):
            actor.apply_control(carla.VehicleControl(brake=1.0, hand_brake=False))
            world.tick()
        materialized = actor.get_transform()
        spawn_error = math.hypot(
            materialized.location.x - spawn.location.x,
            materialized.location.y - spawn.location.y,
        )
        initial_wp = world.get_map().get_waypoint(
            materialized.location,
            project_to_road=True,
            lane_type=carla.LaneType.Driving,
        )
        if spawn_error > 0.50 or initial_wp is None or initial_wp.lane_id != args.source_lane:
            raise RuntimeError(
                f"invalid materialized spawn error={spawn_error:.6f}, "
                f"lane={None if initial_wp is None else initial_wp.lane_id}"
            )

        start_elapsed = world.get_snapshot().timestamp.elapsed_seconds
        while True:
            snapshot = world.get_snapshot()
            elapsed = float(snapshot.timestamp.elapsed_seconds - start_elapsed)
            transform = actor.get_transform()
            source = lane_waypoint(world.get_map(), transform.location, args.source_lane)
            target = lane_waypoint(world.get_map(), transform.location, args.target_lane)
            source_ahead = next_waypoint(source, args.lookahead_m)
            target_ahead = next_waypoint(target, args.lookahead_m)
            alpha = smoothstep((elapsed - args.merge_start_s) / args.merge_duration_s)
            aim = carla.Location(
                x=(1.0 - alpha) * source_ahead.transform.location.x
                + alpha * target_ahead.transform.location.x,
                y=(1.0 - alpha) * source_ahead.transform.location.y
                + alpha * target_ahead.transform.location.y,
                z=(1.0 - alpha) * source_ahead.transform.location.z
                + alpha * target_ahead.transform.location.z,
            )
            steer = pure_pursuit_steer(
                transform, aim, args.wheelbase_m, args.maximum_steer_rad
            )
            command = carla.VehicleAckermannControl(
                steer=steer,
                steer_speed=args.steer_speed_rad_s,
                speed=args.speed_mps,
                acceleration=args.acceleration_mps2,
                jerk=args.jerk_mps3,
            )
            actor.apply_ackermann_control(command)
            velocity = actor.get_velocity()
            nearest = world.get_map().get_waypoint(
                transform.location,
                project_to_road=True,
                lane_type=carla.LaneType.Driving,
            )
            applied = actor.get_control()
            samples.append({
                "frame": int(snapshot.frame),
                "elapsed_s": elapsed,
                "location": [float(transform.location.x), float(transform.location.y), float(transform.location.z)],
                "yaw_deg": float(transform.rotation.yaw),
                "speed_mps": math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2),
                "nearest_road_id": None if nearest is None else int(nearest.road_id),
                "nearest_lane_id": None if nearest is None else int(nearest.lane_id),
                "blend_alpha": alpha,
                "aim_xy": [float(aim.x), float(aim.y)],
                "ackermann": {
                    "steer_rad": steer,
                    "steer_speed_rad_s": args.steer_speed_rad_s,
                    "speed_mps": args.speed_mps,
                    "acceleration_mps2": args.acceleration_mps2,
                    "jerk_mps3": args.jerk_mps3,
                },
                "vehicle_control": {
                    "throttle": float(applied.throttle),
                    "steer": float(applied.steer),
                    "brake": float(applied.brake),
                },
            })
            if elapsed >= args.duration_s:
                break
            world.tick()

        before = [s for s in samples if 1.0 <= s["elapsed_s"] <= args.merge_start_s - 0.5]
        after = [s for s in samples if args.merge_start_s + args.merge_duration_s + 2.0 <= s["elapsed_s"] <= args.duration_s]
        moving = [s["speed_mps"] for s in samples if s["elapsed_s"] >= 2.0]
        source_fraction = sum(s["nearest_lane_id"] == args.source_lane for s in before) / max(1, len(before))
        target_fraction = sum(s["nearest_lane_id"] == args.target_lane for s in after) / max(1, len(after))
        speed_median = statistics.median(moving) if moving else 0.0
        gates = {
            "source_lane_fraction_at_least_0_95": source_fraction >= 0.95,
            "target_lane_fraction_at_least_0_95": target_fraction >= 0.95,
            "speed_median_1_05_to_1_15_mps": 1.05 <= speed_median <= 1.15,
            "collision_count_zero": len(collision_events) == 0,
            "pose_or_velocity_override_api_used_false": True,
            "traffic_manager_used_false": True,
        }
        return {
            "schema_version": 1,
            "probe_id": args.probe_id,
            "status": "PASS" if all(gates.values()) else "REJECT",
            "map": args.map,
            "blueprint": args.blueprint,
            "fixed_delta_seconds": args.fixed_delta_seconds,
            "first_materialized_frame": int(first_frame),
            "spawn_xy_error_m": spawn_error,
            "controller": "CARLA_NATIVE_ACKERMANN_PHYSICS_PURE_PURSUIT",
            "prohibited_api_usage": {
                "set_transform": False,
                "ApplyTransform": False,
                "set_location": False,
                "ApplyLocation": False,
                "set_target_velocity": False,
                "ApplyVelocity": False,
                "enable_constant_velocity": False,
                "TrafficManager": False,
            },
            "source_lane_fraction": source_fraction,
            "target_lane_fraction": target_fraction,
            "speed_median_mps": speed_median,
            "collision_events": collision_events,
            "gates": gates,
            "parameters": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()
            },
            "samples": samples,
        }
    finally:
        collision.stop()
        collision.destroy()
        actor.destroy()
        settings = world.get_settings()
        settings.synchronous_mode = False
        settings.fixed_delta_seconds = None
        world.apply_settings(settings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe-id", default="P2M_ACKERMANN_PROBE_01")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--map", default="Town04")
    parser.add_argument("--blueprint", default="vehicle.micro.microlino")
    parser.add_argument("--spawn-x", type=float, default=12.856113)
    parser.add_argument("--spawn-y", type=float, default=186.451248)
    parser.add_argument("--spawn-z", type=float, default=0.281942)
    parser.add_argument("--spawn-yaw", type=float, default=-90.289116)
    parser.add_argument("--source-lane", type=int, default=-3)
    parser.add_argument("--target-lane", type=int, default=-2)
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--merge-start-s", type=float, default=6.0)
    parser.add_argument("--merge-duration-s", type=float, default=4.0)
    parser.add_argument("--duration-s", type=float, default=18.0)
    parser.add_argument("--speed-mps", type=float, default=1.10)
    parser.add_argument("--lookahead-m", type=float, default=3.0)
    parser.add_argument("--wheelbase-m", type=float, default=1.50)
    parser.add_argument("--maximum-steer-rad", type=float, default=0.50)
    parser.add_argument("--steer-speed-rad-s", type=float, default=0.50)
    parser.add_argument("--acceleration-mps2", type=float, default=1.0)
    parser.add_argument("--jerk-mps3", type=float, default=1.0)
    args = parser.parse_args()
    result = run(args)
    atomic_json(args.output, result)
    print(json.dumps({key: result[key] for key in (
        "probe_id", "status", "source_lane_fraction", "target_lane_fraction", "speed_median_mps", "gates"
    )}, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
