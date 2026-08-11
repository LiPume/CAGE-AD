#!/usr/bin/env python3
"""Measure the unmodified CARLA Lincoln response without Apollo or the bridge."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import carla


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _physics(vehicle: carla.Vehicle) -> dict:
    value = vehicle.get_physics_control()
    return {
        "type_id": vehicle.type_id,
        "mass_kg": value.mass,
        "drag_coefficient": value.drag_coefficient,
        "max_rpm": value.max_rpm,
        "use_gear_autobox": value.use_gear_autobox,
        "gear_switch_time_s": value.gear_switch_time,
        "clutch_strength": value.clutch_strength,
        "final_ratio": value.final_ratio,
        "torque_curve": [{"rpm": point.x, "torque_nm": point.y} for point in value.torque_curve],
        "forward_gears": [
            {"ratio": gear.ratio, "down_ratio": gear.down_ratio, "up_ratio": gear.up_ratio}
            for gear in value.forward_gears
        ],
    }


def _spawn(world: carla.World) -> carla.Vehicle:
    blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2017")
    blueprint.set_attribute("role_name", "ego_vehicle")
    transform = carla.Transform(
        carla.Location(x=202.550003, y=-59.330017, z=0.5),
        carla.Rotation(yaw=0.0),
    )
    vehicle = world.try_spawn_actor(blueprint, transform)
    if vehicle is None:
        raise RuntimeError("could not spawn vehicle.lincoln.mkz_2017 at frozen Town01 pose")
    return vehicle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10)
    world = client.get_world()
    if not world.get_map().name.endswith("/Town01"):
        world = client.load_world("Town01")
    existing_vehicles = world.get_actors().filter("vehicle.*")
    if existing_vehicles:
        raise RuntimeError(f"isolated step response requires zero existing vehicles, got {len(existing_vehicles)}")

    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    profiles = (
        {"name": "apollo_trace_median", "throttle": 0.2355, "duration_s": 8.0},
        {"name": "lower_reference", "throttle": 0.15, "duration_s": 8.0},
        {"name": "upper_reference", "throttle": 0.30, "duration_s": 8.0},
    )
    rows = []
    results = []
    physics = None
    vehicle = None
    try:
        for profile in profiles:
            vehicle = _spawn(world)
            world.tick()
            if physics is None:
                physics = _physics(vehicle)
            for _ in range(20):
                vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=0.0))
                world.tick()

            start = vehicle.get_transform().location
            phase_rows = []
            frame_count = int(round(profile["duration_s"] / 0.05))
            for step in range(frame_count):
                vehicle.apply_control(
                    carla.VehicleControl(throttle=profile["throttle"], brake=0.0, steer=0.0)
                )
                frame = world.tick()
                transform = vehicle.get_transform()
                velocity = vehicle.get_velocity()
                acceleration = vehicle.get_acceleration()
                forward = transform.get_forward_vector()
                row = {
                    "profile": profile["name"],
                    "step": step,
                    "frame": frame,
                    "sim_time_s": (step + 1) * 0.05,
                    "command": {"throttle": profile["throttle"], "brake": 0.0, "steer": 0.0},
                    "position": {"x": transform.location.x, "y": transform.location.y},
                    "speed_mps": math.hypot(velocity.x, velocity.y),
                    "longitudinal_speed_mps": velocity.x * forward.x + velocity.y * forward.y,
                    "longitudinal_acceleration_mps2": (
                        acceleration.x * forward.x + acceleration.y * forward.y
                    ),
                    "control_readback": {
                        "throttle": vehicle.get_control().throttle,
                        "brake": vehicle.get_control().brake,
                        "gear": vehicle.get_control().gear,
                        "reverse": vehicle.get_control().reverse,
                    },
                }
                rows.append(row)
                phase_rows.append(row)
            end = vehicle.get_transform().location
            results.append(
                {
                    **profile,
                    "distance_m": math.hypot(end.x - start.x, end.y - start.y),
                    "speed_at_2s_mps": phase_rows[39]["speed_mps"],
                    "speed_at_5s_mps": phase_rows[99]["speed_mps"],
                    "final_speed_mps": phase_rows[-1]["speed_mps"],
                    "max_speed_mps": max(row["speed_mps"] for row in phase_rows),
                    "max_abs_lateral_displacement_m": max(
                        abs(row["position"]["y"] - start.y) for row in phase_rows
                    ),
                }
            )
            vehicle.destroy()
            vehicle = None
            world.tick()
    finally:
        if vehicle is not None and vehicle.is_alive:
            vehicle.destroy()
        world.apply_settings(old_settings)

    args.trace.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.trace.with_suffix(args.trace.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, args.trace)
    summary = {
        "schema_version": 1,
        "label": "CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET",
        "map": world.get_map().name,
        "fixed_delta_seconds": 0.05,
        "physics": physics,
        "profiles": results,
    }
    _atomic_json(args.summary, summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
