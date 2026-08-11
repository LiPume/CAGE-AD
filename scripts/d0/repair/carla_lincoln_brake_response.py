#!/usr/bin/env python3
"""Measure CARLA Lincoln braking without Apollo or the bridge."""

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


def _spawn(world: carla.World) -> carla.Vehicle:
    blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2017")
    blueprint.set_attribute("role_name", "ego_vehicle")
    vehicle = world.try_spawn_actor(
        blueprint,
        carla.Transform(
            carla.Location(x=202.550003, y=-59.330017, z=0.5),
            carla.Rotation(yaw=0.0),
        ),
    )
    if vehicle is None:
        raise RuntimeError("could not spawn frozen Lincoln at the Town01 test pose")
    return vehicle


def _speed(vehicle: carla.Vehicle) -> float:
    velocity = vehicle.get_velocity()
    return math.hypot(velocity.x, velocity.y)


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
    existing = world.get_actors().filter("vehicle.*")
    if len(existing) != 0:
        raise RuntimeError(f"isolated brake response requires zero vehicles, got {len(existing)}")

    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)
    applied_settings = world.get_settings()

    rows = []
    results = []
    vehicle = None
    try:
        for brake in (0.03, 0.05, 0.10, 0.15):
            vehicle = _spawn(world)
            world.tick()
            for _ in range(20):
                vehicle.apply_control(carla.VehicleControl())
                world.tick()

            acceleration_steps = 0
            while _speed(vehicle) < 1.20 and acceleration_steps < 240:
                vehicle.apply_control(carla.VehicleControl(throttle=0.30))
                world.tick()
                acceleration_steps += 1
            initial_speed = _speed(vehicle)
            if initial_speed < 1.15:
                raise RuntimeError(
                    f"failed to reach comparable braking speed for brake={brake}: {initial_speed}"
                )

            start = vehicle.get_transform().location
            phase = []
            for step in range(60):
                vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=brake))
                frame = world.tick()
                transform = vehicle.get_transform()
                acceleration = vehicle.get_acceleration()
                forward = transform.get_forward_vector()
                row = {
                    "brake": brake,
                    "step": step,
                    "frame": frame,
                    "sim_time_s": (step + 1) * 0.05,
                    "speed_mps": _speed(vehicle),
                    "position": {"x": transform.location.x, "y": transform.location.y},
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
                phase.append(row)
                if row["speed_mps"] < 0.02 and step >= 1:
                    break
            end = vehicle.get_transform().location
            stopped = phase[-1]["speed_mps"] < 0.02
            results.append(
                {
                    "brake": brake,
                    "initial_speed_mps": initial_speed,
                    "acceleration_time_s": acceleration_steps * 0.05,
                    "stopped": stopped,
                    "stop_time_s": phase[-1]["sim_time_s"] if stopped else None,
                    "stop_distance_m": math.hypot(end.x - start.x, end.y - start.y),
                    "minimum_longitudinal_acceleration_mps2": min(
                        row["longitudinal_acceleration_mps2"] for row in phase
                    ),
                    "final_speed_mps": phase[-1]["speed_mps"],
                    "sample_count": len(phase),
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
        "vehicle": "vehicle.lincoln.mkz_2017",
        "fixed_delta_seconds": applied_settings.fixed_delta_seconds,
        "substepping": applied_settings.substepping,
        "max_substep_delta_time": applied_settings.max_substep_delta_time,
        "max_substeps": applied_settings.max_substeps,
        "profiles": results,
    }
    _atomic_json(args.summary, summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
