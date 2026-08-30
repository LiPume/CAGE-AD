#!/usr/bin/env python3
"""Read CARLA Lincoln physics and run one frozen 10 s full-throttle sanity check."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import carla


DT = 0.05
SETTLE_STEPS = 20
MEASUREMENT_STEPS = 200
REQUESTED_THROTTLE = 1.0
HEALTHY_FINAL_SPEED_MPS = 10.0
DEFINITELY_WEAK_FINAL_SPEED_MPS = 3.0


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def vector(value) -> dict:
    return {"x": float(value.x), "y": float(value.y), "z": float(value.z)}


def control_dict(control: carla.VehicleControl) -> dict:
    return {
        "throttle": float(control.throttle),
        "brake": float(control.brake),
        "steer": float(control.steer),
        "gear": int(control.gear),
        "manual_gear_shift": bool(control.manual_gear_shift),
        "reverse": bool(control.reverse),
        "hand_brake": bool(control.hand_brake),
    }


def physics_dict(actor: carla.Vehicle) -> dict:
    physics = actor.get_physics_control()
    return {
        "type_id": actor.type_id,
        "attributes": dict(sorted(actor.attributes.items())),
        "torque_curve": [
            {"rpm": float(point.x), "torque_nm": float(point.y)}
            for point in physics.torque_curve
        ],
        "max_rpm": float(physics.max_rpm),
        "moi": float(physics.moi),
        "damping_rate_full_throttle": float(physics.damping_rate_full_throttle),
        "damping_rate_zero_throttle_clutch_engaged": float(
            physics.damping_rate_zero_throttle_clutch_engaged
        ),
        "damping_rate_zero_throttle_clutch_disengaged": float(
            physics.damping_rate_zero_throttle_clutch_disengaged
        ),
        "use_gear_autobox": bool(physics.use_gear_autobox),
        "gear_switch_time_s": float(physics.gear_switch_time),
        "clutch_strength": float(physics.clutch_strength),
        "final_ratio": float(physics.final_ratio),
        "forward_gears": [
            {
                "ratio": float(gear.ratio),
                "down_ratio": float(gear.down_ratio),
                "up_ratio": float(gear.up_ratio),
            }
            for gear in physics.forward_gears
        ],
        "mass_kg": float(physics.mass),
        "drag_coefficient": float(physics.drag_coefficient),
        "center_of_mass_m": vector(physics.center_of_mass),
        "steering_curve": [
            {"speed_mps": float(point.x), "steering_ratio": float(point.y)}
            for point in physics.steering_curve
        ],
        "use_sweep_wheel_collision": bool(physics.use_sweep_wheel_collision),
        "wheels": [
            {
                "tire_friction": float(wheel.tire_friction),
                "damping_rate": float(wheel.damping_rate),
                "max_steer_angle_deg": float(wheel.max_steer_angle),
                "radius_cm": float(wheel.radius),
                "max_brake_torque": float(wheel.max_brake_torque),
                "max_handbrake_torque": float(wheel.max_handbrake_torque),
            }
            for wheel in physics.wheels
        ],
    }


def speed(actor: carla.Vehicle) -> float:
    velocity = actor.get_velocity()
    return math.hypot(velocity.x, velocity.y)


def spawn(world: carla.World) -> carla.Vehicle:
    blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2017")
    blueprint.set_attribute("role_name", "v16a_physics_audit_vehicle")
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10)
    world = client.get_world()
    if not world.get_map().name.endswith("/Town01"):
        raise RuntimeError("v16a physics audit requires preloaded Town01")
    if world.get_actors().filter("vehicle.*"):
        raise RuntimeError("v16a physics audit requires zero existing vehicles")

    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = DT
    world.apply_settings(settings)
    applied_settings = world.get_settings()

    actor = None
    collision_sensor = None
    collision_frames: list[int] = []
    rows: list[dict] = []
    try:
        actor = spawn(world)
        collision_sensor = world.spawn_actor(
            world.get_blueprint_library().find("sensor.other.collision"),
            carla.Transform(),
            attach_to=actor,
        )
        collision_sensor.listen(lambda event: collision_frames.append(int(event.frame)))
        world.tick()
        for _ in range(SETTLE_STEPS):
            actor.apply_control(carla.VehicleControl())
            world.tick()

        start_speed = speed(actor)
        start_control = control_dict(actor.get_control())
        physics_before = physics_dict(actor)
        initial_transform = actor.get_transform()
        initial_location = initial_transform.location

        for step in range(MEASUREMENT_STEPS):
            actor.apply_control(
                carla.VehicleControl(
                    throttle=REQUESTED_THROTTLE,
                    steer=0.0,
                    brake=0.0,
                    hand_brake=False,
                    reverse=False,
                    manual_gear_shift=False,
                )
            )
            frame = world.tick()
            transform = actor.get_transform()
            acceleration = actor.get_acceleration()
            forward = transform.get_forward_vector()
            control = actor.get_control()
            rows.append({
                "step": step,
                "frame": frame,
                "measurement_time_s": (step + 1) * DT,
                "requested_control": {
                    "throttle": REQUESTED_THROTTLE,
                    "brake": 0.0,
                    "steer": 0.0,
                    "hand_brake": False,
                    "reverse": False,
                    "manual_gear_shift": False,
                },
                "actual_control": control_dict(control),
                "speed_mps": speed(actor),
                "velocity_mps": vector(actor.get_velocity()),
                "acceleration_mps2": vector(acceleration),
                "longitudinal_acceleration_mps2": (
                    acceleration.x * forward.x + acceleration.y * forward.y
                ),
                "location_m": vector(transform.location),
                "yaw_deg": float(transform.rotation.yaw),
                "road_speed_limit_kmh_observation_only": float(actor.get_speed_limit()),
                "failure_state": str(actor.get_failure_state()),
            })

        physics_after = physics_dict(actor)
        final_transform = actor.get_transform()
        distance_m = math.dist(
            (initial_location.x, initial_location.y, initial_location.z),
            (
                final_transform.location.x,
                final_transform.location.y,
                final_transform.location.z,
            ),
        )
    finally:
        if collision_sensor is not None:
            collision_sensor.stop()
            collision_sensor.destroy()
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

    controls_exact = bool(rows) and all(
        abs(row["actual_control"]["throttle"] - REQUESTED_THROTTLE) < 1e-6
        and row["actual_control"]["brake"] == 0.0
        and row["actual_control"]["steer"] == 0.0
        and not row["actual_control"]["hand_brake"]
        and not row["actual_control"]["reverse"]
        and not row["actual_control"]["manual_gear_shift"]
        for row in rows
    )
    final_speed = rows[-1]["speed_mps"] if rows else None
    max_speed = max((row["speed_mps"] for row in rows), default=None)
    max_gear = max((row["actual_control"]["gear"] for row in rows), default=None)
    checks = {
        "exactly_200_measurement_frames": len(rows) == MEASUREMENT_STEPS,
        "start_speed_at_most_0_05_mps": start_speed <= 0.05,
        "requested_control_exactly_applied": controls_exact,
        "physics_unchanged_during_test": physics_before == physics_after,
        "automatic_transmission_enabled": physics_before["use_gear_autobox"],
        "reached_forward_gear": bool(max_gear is not None and max_gear >= 1),
        "reached_second_or_higher_gear": bool(max_gear is not None and max_gear >= 2),
        "no_collision": not collision_frames,
        "final_speed_at_least_10_mps": bool(
            final_speed is not None and final_speed >= HEALTHY_FINAL_SPEED_MPS
        ),
    }
    if not controls_exact or physics_before != physics_after or collision_frames:
        verdict = "INVALID_STOP"
    elif final_speed is not None and final_speed <= DEFINITELY_WEAK_FINAL_SPEED_MPS:
        verdict = "FAIL_PLANT_WEAK_STOP"
    elif all(checks.values()):
        verdict = "PASS_PLANT_BASELINE"
    else:
        verdict = "INCONCLUSIVE_STOP"

    summary = {
        "schema_version": 1,
        "label": "CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET",
        "test_id": "V16A_FULL_THROTTLE_PHYSICS_BASELINE",
        "map": world.get_map().name,
        "fixed_delta_seconds": applied_settings.fixed_delta_seconds,
        "duration_s": MEASUREMENT_STEPS * DT,
        "settle_duration_s": SETTLE_STEPS * DT,
        "requested_throttle": REQUESTED_THROTTLE,
        "start_speed_mps": start_speed,
        "start_control": start_control,
        "final_speed_mps": final_speed,
        "max_speed_mps": max_speed,
        "max_gear": max_gear,
        "distance_m": distance_m,
        "collision_frames": sorted(set(collision_frames)),
        "physics_before": physics_before,
        "physics_after": physics_after,
        "checks": checks,
        "verdict": verdict,
        "passed": verdict == "PASS_PLANT_BASELINE",
    }
    atomic_json(args.summary, summary)
    print(json.dumps(summary, sort_keys=True))
    raise SystemExit(0 if summary["passed"] else 2)


if __name__ == "__main__":
    main()
