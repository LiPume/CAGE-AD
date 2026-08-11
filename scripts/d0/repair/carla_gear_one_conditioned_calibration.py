#!/usr/bin/env python3
"""Measure throttle response from a common actual-gear-one initial condition."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from statistics import median

import carla


LEVELS = (0.20, 0.2355, 0.2575, 0.30, 0.35, 0.40, 0.50)
REPEATS = 3
DT = 0.05
PRECONDITION_THROTTLE = 0.40
PRECONDITION_MAX_STEPS = 160
MEASUREMENT_STEPS = 60
EVALUATION_START_STEP = 10


def speed(vehicle: carla.Vehicle) -> float:
    velocity = vehicle.get_velocity()
    return math.hypot(velocity.x, velocity.y)


def spawn(world: carla.World) -> carla.Vehicle:
    blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2017")
    blueprint.set_attribute("role_name", "v13_calibration_vehicle")
    actor = world.try_spawn_actor(
        blueprint,
        carla.Transform(
            carla.Location(x=202.550003, y=-59.330017, z=0.5),
            carla.Rotation(yaw=0.0),
        ),
    )
    if actor is None:
        raise RuntimeError("could not spawn frozen Lincoln at the Town01 test pose")
    return actor


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def speed_slope(rows: list[dict]) -> float:
    times = [row["measurement_time_s"] for row in rows]
    speeds = [row["speed_mps"] for row in rows]
    mean_time = sum(times) / len(times)
    mean_speed = sum(speeds) / len(speeds)
    return sum(
        (sample_time - mean_time) * (sample_speed - mean_speed)
        for sample_time, sample_speed in zip(times, speeds)
    ) / sum((sample_time - mean_time) ** 2 for sample_time in times)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10)
    world = client.get_world()
    if not world.get_map().name.endswith("/Town01"):
        raise RuntimeError("v13 calibration requires preloaded Town01")
    existing = world.get_actors().filter("vehicle.*")
    if existing:
        raise RuntimeError(f"v13 calibration requires zero vehicles, got {len(existing)}")

    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = DT
    world.apply_settings(settings)
    applied_settings = world.get_settings()
    rows = []
    samples = []
    actor = None
    try:
        for throttle in LEVELS:
            for repeat in range(REPEATS):
                actor = spawn(world)
                world.tick()
                for _ in range(20):
                    actor.apply_control(carla.VehicleControl())
                    world.tick()

                reached = False
                precondition_steps = 0
                for precondition_steps in range(1, PRECONDITION_MAX_STEPS + 1):
                    actor.apply_control(carla.VehicleControl(throttle=PRECONDITION_THROTTLE))
                    world.tick()
                    control = actor.get_control()
                    if control.gear == 1 and speed(actor) >= 1.0:
                        reached = True
                        break
                start_speed = speed(actor)
                start_control = actor.get_control()
                phase = []
                start_location = actor.get_transform().location
                if reached:
                    for step in range(MEASUREMENT_STEPS):
                        actor.apply_control(carla.VehicleControl(throttle=throttle))
                        frame = world.tick()
                        transform = actor.get_transform()
                        acceleration = actor.get_acceleration()
                        forward = transform.get_forward_vector()
                        control = actor.get_control()
                        row = {
                            "throttle": throttle,
                            "repeat": repeat,
                            "step": step,
                            "frame": frame,
                            "measurement_time_s": (step + 1) * DT,
                            "precondition_steps": precondition_steps,
                            "precondition_start_speed_mps": start_speed,
                            "speed_mps": speed(actor),
                            "longitudinal_acceleration_mps2": (
                                acceleration.x * forward.x + acceleration.y * forward.y
                            ),
                            "position": {
                                "x": transform.location.x,
                                "y": transform.location.y,
                            },
                            "control_readback": {
                                "throttle": control.throttle,
                                "brake": control.brake,
                                "gear": control.gear,
                                "manual_gear_shift": control.manual_gear_shift,
                                "reverse": control.reverse,
                                "hand_brake": control.hand_brake,
                            },
                        }
                        rows.append(row)
                        phase.append(row)

                evaluation = phase[EVALUATION_START_STEP:]
                end_location = actor.get_transform().location
                sample = {
                    "throttle": throttle,
                    "repeat": repeat,
                    "precondition_reached": reached,
                    "precondition_steps": precondition_steps,
                    "start_speed_mps": start_speed,
                    "start_actual_gear": start_control.gear,
                    "sample_count": len(phase),
                    "evaluation_count": len(evaluation),
                    "evaluation_median_acceleration_mps2": (
                        median(row["longitudinal_acceleration_mps2"] for row in evaluation)
                        if evaluation else None
                    ),
                    "evaluation_speed_slope_mps2": (
                        speed_slope(evaluation) if evaluation else None
                    ),
                    "evaluation_median_speed_mps": (
                        median(row["speed_mps"] for row in evaluation) if evaluation else None
                    ),
                    "end_speed_mps": phase[-1]["speed_mps"] if phase else None,
                    "distance_m": math.hypot(
                        end_location.x - start_location.x,
                        end_location.y - start_location.y,
                    ),
                    "readback_valid": bool(
                        phase
                        and all(
                            abs(row["control_readback"]["throttle"] - throttle) < 1e-6
                            and row["control_readback"]["brake"] == 0.0
                            and row["control_readback"]["gear"] > 0
                            and not row["control_readback"]["manual_gear_shift"]
                            and not row["control_readback"]["reverse"]
                            and not row["control_readback"]["hand_brake"]
                            for row in phase
                        )
                    ),
                }
                samples.append(sample)
                actor.destroy()
                actor = None
                world.tick()
    finally:
        if actor is not None and actor.is_alive:
            actor.destroy()
        world.apply_settings(old_settings)

    args.trace.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.trace.with_suffix(args.trace.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, args.trace)

    profiles = []
    for throttle in LEVELS:
        group = [sample for sample in samples if sample["throttle"] == throttle]
        instantaneous_values = [
            sample["evaluation_median_acceleration_mps2"]
            for sample in group
            if sample["evaluation_median_acceleration_mps2"] is not None
        ]
        slope_values = [
            sample["evaluation_speed_slope_mps2"]
            for sample in group
            if sample["evaluation_speed_slope_mps2"] is not None
        ]
        profiles.append({
            "throttle": throttle,
            "repeat_count": len(group),
            "median_instantaneous_acceleration_mps2": (
                median(instantaneous_values)
                if len(instantaneous_values) == REPEATS else None
            ),
            "median_speed_slope_mps2": (
                median(slope_values) if len(slope_values) == REPEATS else None
            ),
            "repeat_speed_slope_range_mps2": (
                max(slope_values) - min(slope_values)
                if len(slope_values) == REPEATS else None
            ),
            "samples": group,
        })

    profile_slopes = [
        profile["median_speed_slope_mps2"]
        for profile in profiles
        if profile["median_speed_slope_mps2"] is not None
    ]
    checks = {
        "all_21_samples_present": len(samples) == len(LEVELS) * REPEATS,
        "all_preconditions_reached": all(sample["precondition_reached"] for sample in samples),
        "all_start_in_gear_one": all(sample["start_actual_gear"] == 1 for sample in samples),
        "all_start_speeds_in_range": all(1.0 <= sample["start_speed_mps"] <= 1.15 for sample in samples),
        "all_samples_complete": all(sample["sample_count"] == MEASUREMENT_STEPS for sample in samples),
        "all_readbacks_valid": all(sample["readback_valid"] for sample in samples),
        "repeat_speed_slope_ranges_at_most_0_20": all(
            profile["repeat_speed_slope_range_mps2"] is not None
            and profile["repeat_speed_slope_range_mps2"] <= 0.20
            for profile in profiles
        ),
        "speed_slope_nondecreasing_with_0_05_tolerance": len(profile_slopes) == len(LEVELS) and all(
            later + 0.05 >= earlier
            for earlier, later in zip(profile_slopes, profile_slopes[1:])
        ),
        "speed_slope_spans_near_zero": bool(profile_slopes) and min(profile_slopes) <= 0.10,
        "speed_slope_spans_at_least_0_35": bool(profile_slopes) and max(profile_slopes) >= 0.35,
    }
    summary = {
        "schema_version": 1,
        "label": "CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET",
        "map": world.get_map().name,
        "vehicle": "vehicle.lincoln.mkz_2017",
        "fixed_delta_seconds": applied_settings.fixed_delta_seconds,
        "levels": list(LEVELS),
        "repeats": REPEATS,
        "precondition_throttle": PRECONDITION_THROTTLE,
        "measurement_steps": MEASUREMENT_STEPS,
        "evaluation_start_step": EVALUATION_START_STEP,
        "profiles": profiles,
        "checks": checks,
        "passed": all(checks.values()),
    }
    atomic_json(args.summary, summary)
    print(json.dumps(summary, sort_keys=True))
    raise SystemExit(0 if summary["passed"] else 2)


if __name__ == "__main__":
    main()
