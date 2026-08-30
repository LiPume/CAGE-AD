#!/usr/bin/env python3
"""Measure sub-3% CARLA braking at 2 m/s without Apollo or the bridge."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from statistics import median

import carla


LEVELS = (0.0, 0.001, 0.003, 0.005, 0.01, 0.02, 0.03)
REPEATS = 3
DT = 0.05
TARGET_SPEED_MPS = 2.0
PRECONDITION_THROTTLE = 0.50
PRECONDITION_MAX_STEPS = 240
MEASUREMENT_STEPS = 60


def speed(actor: carla.Vehicle) -> float:
    value = actor.get_velocity()
    return math.hypot(value.x, value.y)


def physics_signature(actor: carla.Vehicle) -> dict:
    value = actor.get_physics_control()
    return {
        "mass": float(value.mass),
        "drag_coefficient": float(value.drag_coefficient),
        "use_gear_autobox": bool(value.use_gear_autobox),
        "gear_switch_time": float(value.gear_switch_time),
        "clutch_strength": float(value.clutch_strength),
        "final_ratio": float(value.final_ratio),
        "damping_zero_engaged": float(value.damping_rate_zero_throttle_clutch_engaged),
        "damping_zero_disengaged": float(value.damping_rate_zero_throttle_clutch_disengaged),
        "max_brake_torque": [float(wheel.max_brake_torque) for wheel in value.wheels],
    }


def spawn(world: carla.World) -> carla.Vehicle:
    blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2017")
    blueprint.set_attribute("role_name", "v19_micro_brake_vehicle")
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
    os.chmod(temporary, 0o600)
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
        raise RuntimeError("v19 micro-brake test requires preloaded Town01")
    if world.get_actors().filter("vehicle.*"):
        raise RuntimeError("v19 micro-brake test requires zero existing vehicles")

    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = DT
    world.apply_settings(settings)
    rows: list[dict] = []
    samples: list[dict] = []
    actor = None
    try:
        for brake in LEVELS:
            for repeat in range(REPEATS):
                actor = spawn(world)
                world.tick()
                physics_before = physics_signature(actor)
                for _ in range(20):
                    actor.apply_control(carla.VehicleControl())
                    world.tick()
                reached = False
                for precondition_step in range(1, PRECONDITION_MAX_STEPS + 1):
                    actor.apply_control(carla.VehicleControl(throttle=PRECONDITION_THROTTLE))
                    world.tick()
                    if actor.get_control().gear > 0 and speed(actor) >= TARGET_SPEED_MPS:
                        reached = True
                        break
                start_speed = speed(actor)
                start_gear = int(actor.get_control().gear)
                start_location = actor.get_location()
                phase: list[dict] = []
                if reached:
                    for step in range(MEASUREMENT_STEPS):
                        actor.apply_control(carla.VehicleControl(brake=brake))
                        frame = world.tick()
                        control = actor.get_control()
                        transform = actor.get_transform()
                        acceleration = actor.get_acceleration()
                        forward = transform.get_forward_vector()
                        row = {
                            "brake": brake,
                            "repeat": repeat,
                            "step": step,
                            "frame": frame,
                            "measurement_time_s": (step + 1) * DT,
                            "start_speed_mps": start_speed,
                            "speed_mps": speed(actor),
                            "longitudinal_acceleration_mps2": acceleration.x * forward.x + acceleration.y * forward.y,
                            "requested_control": {"throttle": 0.0, "brake": brake},
                            "actual_control": {
                                "throttle": float(control.throttle),
                                "brake": float(control.brake),
                                "gear": int(control.gear),
                                "manual_gear_shift": bool(control.manual_gear_shift),
                                "hand_brake": bool(control.hand_brake),
                                "reverse": bool(control.reverse),
                            },
                        }
                        rows.append(row)
                        phase.append(row)
                        if row["speed_mps"] < 0.02 and step >= 1:
                            break
                end_location = actor.get_location()
                stopped = bool(phase and phase[-1]["speed_mps"] < 0.02)
                samples.append({
                    "brake": brake,
                    "repeat": repeat,
                    "precondition_reached": reached,
                    "precondition_steps": precondition_step,
                    "start_speed_mps": start_speed,
                    "start_gear": start_gear,
                    "sample_count": len(phase),
                    "stopped": stopped,
                    "stop_time_s": phase[-1]["measurement_time_s"] if stopped else None,
                    "distance_m": math.hypot(end_location.x - start_location.x, end_location.y - start_location.y),
                    "final_speed_mps": phase[-1]["speed_mps"] if phase else None,
                    "minimum_longitudinal_acceleration_mps2": min((row["longitudinal_acceleration_mps2"] for row in phase), default=None),
                    "readback_valid": bool(phase and all(
                        row["actual_control"]["throttle"] == 0.0
                        and abs(row["actual_control"]["brake"] - brake) < 1e-6
                        and not row["actual_control"]["manual_gear_shift"]
                        and not row["actual_control"]["hand_brake"]
                        and not row["actual_control"]["reverse"]
                        for row in phase
                    )),
                    "physics_unchanged": physics_before == physics_signature(actor),
                })
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
    os.chmod(temporary, 0o600)
    os.replace(temporary, args.trace)

    profiles = []
    effective_times = []
    for brake in LEVELS:
        group = [sample for sample in samples if sample["brake"] == brake]
        times = [sample["stop_time_s"] if sample["stop_time_s"] is not None else (MEASUREMENT_STEPS + 1) * DT for sample in group]
        median_time = median(times) if len(times) == REPEATS else None
        profiles.append({
            "brake": brake,
            "repeat_count": len(group),
            "median_effective_stop_time_s": median_time,
            "censored_at_3s_count": sum(sample["stop_time_s"] is None for sample in group),
            "samples": group,
        })
        if brake > 0.0 and median_time is not None:
            effective_times.append(median_time)
    valid_checks = {
        "all_21_samples_present": len(samples) == len(LEVELS) * REPEATS,
        "all_preconditions_reached": all(sample["precondition_reached"] for sample in samples),
        "all_start_speeds_in_2_00_to_2_15_mps": all(TARGET_SPEED_MPS <= sample["start_speed_mps"] <= 2.15 for sample in samples),
        "all_start_gears_forward": all(sample["start_gear"] > 0 for sample in samples),
        "all_controls_read_back_exactly": all(sample["readback_valid"] for sample in samples),
        "vehicle_physics_unchanged": all(sample["physics_unchanged"] for sample in samples),
    }
    monotonic = len(effective_times) == len(LEVELS) - 1 and all(
        later <= earlier + 0.05 for earlier, later in zip(effective_times, effective_times[1:])
    )
    gradual_count = sum(0.25 <= value <= 3.05 for value in effective_times)
    distinguishable = any(
        earlier - later >= 0.10 for earlier, later in zip(effective_times, effective_times[1:])
    )
    valid = all(valid_checks.values())
    gradual_region_found = valid and monotonic and gradual_count >= 2 and distinguishable
    verdict = (
        "INVALID_MEASUREMENT_STOP" if not valid else
        "PASS_RESOLVABLE_GRADUAL_REGION" if gradual_region_found else
        "NO_RESOLVABLE_GRADUAL_REGION"
    )
    summary = {
        "schema_version": 1,
        "label": "CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET",
        "test_id": "V19_LOW_SPEED_MICRO_BRAKE",
        "map": world.get_map().name,
        "vehicle": "vehicle.lincoln.mkz_2017",
        "target_start_speed_mps": TARGET_SPEED_MPS,
        "levels": list(LEVELS),
        "repeats": REPEATS,
        "measurement_window_s": MEASUREMENT_STEPS * DT,
        "profiles": profiles,
        "validity_checks": valid_checks,
        "positive_median_effective_stop_times_s": effective_times,
        "positive_levels_monotonic": monotonic,
        "gradual_positive_level_count": gradual_count,
        "adjacent_levels_distinguishable": distinguishable,
        "verdict": verdict,
    }
    atomic_json(args.summary, summary)
    print(json.dumps(summary, sort_keys=True))
    raise SystemExit(0 if valid else 2)


if __name__ == "__main__":
    main()
