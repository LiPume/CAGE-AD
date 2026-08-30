#!/usr/bin/env python3
"""Measure the CARLA Lincoln positive-throttle plant from 2 through 5 m/s."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from statistics import median

import carla


TARGET_SPEEDS = (2.0, 3.0, 4.0)
THROTTLE_LEVELS = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
REPEATS = 3
DT = 0.05
PRECONDITION_THROTTLE = 0.50
PRECONDITION_MAX_STEPS = 600
SETTLE_STEPS = 20
MEASUREMENT_STEPS = 12
EVALUATION_START_STEP = 2


def vehicle_speed(actor: carla.Vehicle) -> float:
    velocity = actor.get_velocity()
    return math.hypot(velocity.x, velocity.y)


def speed_slope(rows: list[dict]) -> float:
    times = [row["measurement_time_s"] for row in rows]
    speeds = [row["speed_mps"] for row in rows]
    mean_time = sum(times) / len(times)
    mean_speed = sum(speeds) / len(speeds)
    return sum(
        (sample_time - mean_time) * (sample_speed - mean_speed)
        for sample_time, sample_speed in zip(times, speeds)
    ) / sum((sample_time - mean_time) ** 2 for sample_time in times)


def spawn(world: carla.World) -> carla.Vehicle:
    blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2017")
    blueprint.set_attribute("role_name", "hint_gold_speed_band_calibration")
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


def write_trace(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
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
        raise RuntimeError("speed-band calibration requires preloaded Town01")
    if world.get_actors().filter("vehicle.*"):
        raise RuntimeError("speed-band calibration requires zero existing vehicles")

    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = DT
    world.apply_settings(settings)
    applied_settings = world.get_settings()
    rows: list[dict] = []
    samples: list[dict] = []
    actor = None
    try:
        for target_speed in TARGET_SPEEDS:
            for throttle in THROTTLE_LEVELS:
                for repeat in range(REPEATS):
                    actor = spawn(world)
                    world.tick()
                    for _ in range(SETTLE_STEPS):
                        actor.apply_control(carla.VehicleControl())
                        world.tick()

                    reached = False
                    precondition_steps = 0
                    for precondition_steps in range(1, PRECONDITION_MAX_STEPS + 1):
                        actor.apply_control(
                            carla.VehicleControl(throttle=PRECONDITION_THROTTLE)
                        )
                        world.tick()
                        if actor.get_control().gear > 0 and vehicle_speed(actor) >= target_speed:
                            reached = True
                            break

                    start_speed = vehicle_speed(actor)
                    start_gear = actor.get_control().gear
                    phase: list[dict] = []
                    if reached:
                        for step in range(MEASUREMENT_STEPS):
                            actor.apply_control(carla.VehicleControl(throttle=throttle))
                            frame = world.tick()
                            transform = actor.get_transform()
                            acceleration = actor.get_acceleration()
                            forward = transform.get_forward_vector()
                            control = actor.get_control()
                            row = {
                                "target_start_speed_mps": target_speed,
                                "throttle": throttle,
                                "repeat": repeat,
                                "step": step,
                                "frame": frame,
                                "measurement_time_s": (step + 1) * DT,
                                "start_speed_mps": start_speed,
                                "start_gear": start_gear,
                                "speed_mps": vehicle_speed(actor),
                                "longitudinal_acceleration_mps2": (
                                    acceleration.x * forward.x
                                    + acceleration.y * forward.y
                                ),
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
                    samples.append(
                        {
                            "target_start_speed_mps": target_speed,
                            "throttle": throttle,
                            "repeat": repeat,
                            "precondition_reached": reached,
                            "precondition_steps": precondition_steps,
                            "start_speed_mps": start_speed,
                            "start_gear": start_gear,
                            "sample_count": len(phase),
                            "speed_slope_mps2": (
                                speed_slope(evaluation) if evaluation else None
                            ),
                            "instantaneous_acceleration_median_mps2": (
                                median(
                                    row["longitudinal_acceleration_mps2"]
                                    for row in evaluation
                                )
                                if evaluation
                                else None
                            ),
                            "readback_valid": bool(
                                phase
                                and all(
                                    abs(
                                        row["control_readback"]["throttle"]
                                        - throttle
                                    )
                                    < 1e-6
                                    and row["control_readback"]["brake"] == 0.0
                                    and row["control_readback"]["gear"] > 0
                                    and not row["control_readback"][
                                        "manual_gear_shift"
                                    ]
                                    and not row["control_readback"]["reverse"]
                                    and not row["control_readback"]["hand_brake"]
                                    for row in phase
                                )
                            ),
                        }
                    )
                    actor.destroy()
                    actor = None
                    world.tick()
    finally:
        if actor is not None and actor.is_alive:
            actor.destroy()
        world.apply_settings(old_settings)

    write_trace(args.trace, rows)
    profiles = []
    for target_speed in TARGET_SPEEDS:
        for throttle in THROTTLE_LEVELS:
            group = [
                sample
                for sample in samples
                if sample["target_start_speed_mps"] == target_speed
                and sample["throttle"] == throttle
            ]
            slopes = [
                sample["speed_slope_mps2"]
                for sample in group
                if sample["speed_slope_mps2"] is not None
            ]
            profiles.append(
                {
                    "target_start_speed_mps": target_speed,
                    "throttle": throttle,
                    "repeat_count": len(group),
                    "median_speed_slope_mps2": (
                        median(slopes) if len(slopes) == REPEATS else None
                    ),
                    "repeat_speed_slope_range_mps2": (
                        max(slopes) - min(slopes) if len(slopes) == REPEATS else None
                    ),
                    "samples": group,
                }
            )

    expected_samples = len(TARGET_SPEEDS) * len(THROTTLE_LEVELS) * REPEATS
    checks = {
        "all_samples_present": len(samples) == expected_samples,
        "all_preconditions_reached": all(
            sample["precondition_reached"] for sample in samples
        ),
        "all_start_speeds_in_range": all(
            sample["target_start_speed_mps"]
            <= sample["start_speed_mps"]
            <= sample["target_start_speed_mps"] + 0.20
            for sample in samples
        ),
        "all_forward_gear": all(sample["start_gear"] > 0 for sample in samples),
        "all_samples_complete": all(
            sample["sample_count"] == MEASUREMENT_STEPS for sample in samples
        ),
        "all_readbacks_valid": all(sample["readback_valid"] for sample in samples),
        "repeat_ranges_at_most_0_20": all(
            profile["repeat_speed_slope_range_mps2"] is not None
            and profile["repeat_speed_slope_range_mps2"] <= 0.20
            for profile in profiles
        ),
    }
    for target_speed in TARGET_SPEEDS:
        values = [
            profile["median_speed_slope_mps2"]
            for profile in profiles
            if profile["target_start_speed_mps"] == target_speed
            and profile["median_speed_slope_mps2"] is not None
        ]
        key = str(target_speed).replace(".", "_")
        checks[f"speed_{key}_monotonic"] = len(values) == len(
            THROTTLE_LEVELS
        ) and all(later + 0.05 >= earlier for earlier, later in zip(values, values[1:]))
        checks[f"speed_{key}_spans_zero"] = bool(values) and min(values) <= 0.0 <= max(
            values
        )
        checks[f"speed_{key}_spans_acceleration_1"] = bool(values) and max(
            values
        ) >= 1.0

    summary = {
        "schema_version": 1,
        "label": "HINT_GOLD_CONTROL_CALIBRATION_DIAGNOSTIC_NOT_DATASET",
        "map": world.get_map().name,
        "vehicle": "vehicle.lincoln.mkz_2017",
        "fixed_delta_seconds": applied_settings.fixed_delta_seconds,
        "target_speeds_mps": list(TARGET_SPEEDS),
        "throttle_levels": list(THROTTLE_LEVELS),
        "repeats": REPEATS,
        "expected_samples": expected_samples,
        "profiles": profiles,
        "checks": checks,
        "passed": all(checks.values()),
    }
    atomic_json(args.summary, summary)
    print(json.dumps({"passed": summary["passed"], "checks": checks}, sort_keys=True))
    raise SystemExit(0 if summary["passed"] else 2)


if __name__ == "__main__":
    main()
