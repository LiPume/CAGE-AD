#!/usr/bin/env python3
"""Measure five frozen Lincoln throttle levels without Apollo or bridge."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import carla


LEVELS = (0.15, 0.20, 0.2355, 0.30, 0.40)


def _speed(vehicle: carla.Vehicle) -> float:
    velocity = vehicle.get_velocity()
    return math.hypot(velocity.x, velocity.y)


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


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10)
    world = client.get_world()
    if not world.get_map().name.endswith("/Town01"):
        raise RuntimeError("throttle characterization requires preloaded Town01")
    existing = world.get_actors().filter("vehicle.*")
    if len(existing) != 0:
        raise RuntimeError(
            f"isolated throttle characterization requires zero vehicles, got {len(existing)}"
        )

    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)
    applied = world.get_settings()
    rows: list[dict] = []
    profiles: list[dict] = []
    vehicle = None
    try:
        for throttle in LEVELS:
            vehicle = _spawn(world)
            world.tick()
            for _ in range(20):
                vehicle.apply_control(carla.VehicleControl())
                world.tick()
            start = vehicle.get_transform().location
            phase: list[dict] = []
            for step in range(160):
                vehicle.apply_control(carla.VehicleControl(throttle=throttle))
                frame = world.tick()
                transform = vehicle.get_transform()
                acceleration = vehicle.get_acceleration()
                forward = transform.get_forward_vector()
                control = vehicle.get_control()
                row = {
                    "throttle": throttle,
                    "step": step,
                    "frame": frame,
                    "sim_time_s": (step + 1) * 0.05,
                    "speed_mps": _speed(vehicle),
                    "position": {"x": transform.location.x, "y": transform.location.y},
                    "longitudinal_acceleration_mps2": (
                        acceleration.x * forward.x + acceleration.y * forward.y
                    ),
                    "control_readback": {
                        "throttle": control.throttle,
                        "brake": control.brake,
                        "gear": control.gear,
                        "reverse": control.reverse,
                    },
                }
                rows.append(row)
                phase.append(row)
            end = vehicle.get_transform().location
            profiles.append(
                {
                    "throttle": throttle,
                    "sample_count": len(phase),
                    "speed_at_2s_mps": phase[39]["speed_mps"],
                    "speed_at_4s_mps": phase[79]["speed_mps"],
                    "speed_at_8s_mps": phase[-1]["speed_mps"],
                    "maximum_speed_mps": max(row["speed_mps"] for row in phase),
                    "distance_8s_m": math.hypot(end.x - start.x, end.y - start.y),
                    "minimum_acceleration_mps2": min(
                        row["longitudinal_acceleration_mps2"] for row in phase
                    ),
                    "maximum_acceleration_mps2": max(
                        row["longitudinal_acceleration_mps2"] for row in phase
                    ),
                    "readback_matches": all(
                        abs(row["control_readback"]["throttle"] - throttle) < 1e-6
                        and row["control_readback"]["brake"] == 0.0
                        and row["control_readback"]["gear"] == 1
                        and not row["control_readback"]["reverse"]
                        for row in phase
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

    speeds = [profile["speed_at_8s_mps"] for profile in profiles]
    summary = {
        "schema_version": 1,
        "label": "CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET",
        "map": world.get_map().name,
        "vehicle": "vehicle.lincoln.mkz_2017",
        "fixed_delta_seconds": applied.fixed_delta_seconds,
        "profiles": profiles,
        "all_profiles_complete": all(p["sample_count"] == 160 for p in profiles),
        "all_readbacks_match": all(p["readback_matches"] for p in profiles),
        "endpoint_speed_strictly_monotonic": all(
            later > earlier for earlier, later in zip(speeds, speeds[1:])
        ),
    }
    _atomic_json(args.summary, summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
