#!/usr/bin/env python3
"""CPU-only check of the patched CARLA bridge chassis gear mapping."""

from __future__ import annotations

import sys
import types
import io
import json

import carla
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis
from modules.common_msgs.transform_msgs.transform_pb2 import TransformStamped


class _Vehicle:
    @staticmethod
    def get_vehicle_speed_abs(_actor) -> float:
        return 0.0


# This verifier executes the real EgoVehicle.send_vehicle_msgs method.  Stub only
# its unrelated inheritance/geometry imports so the check stays CPU-only and does
# not require the bridge's full ROS-era Python dependency set.
vehicle_module = types.ModuleType("carla_bridge.actor.vehicle")
vehicle_module.Vehicle = _Vehicle
sys.modules[vehicle_module.__name__] = vehicle_module
utils_module = types.ModuleType("carla_bridge.utils")
utils_module.__path__ = []
transforms_module = types.ModuleType("carla_bridge.utils.transforms")
utils_module.transforms = transforms_module
sys.modules[utils_module.__name__] = utils_module
sys.modules[transforms_module.__name__] = transforms_module

from carla_bridge.actor.ego_vehicle import EgoVehicle


class _Writer:
    def __init__(self) -> None:
        self.messages = []

    def write(self, message) -> None:
        clone = type(message)()
        clone.CopyFrom(message)
        self.messages.append(clone)


class _Spectator:
    def set_transform(self, _transform) -> None:
        return None


class _World:
    def get_spectator(self) -> _Spectator:
        return _Spectator()

    @staticmethod
    def get_snapshot():
        return types.SimpleNamespace(
            frame=17,
            timestamp=types.SimpleNamespace(elapsed_seconds=2.5),
        )


class _Actor:
    def __init__(self, control: carla.VehicleControl) -> None:
        self.control = control

    def get_control(self) -> carla.VehicleControl:
        return self.control

    def get_velocity(self) -> carla.Vector3D:
        return carla.Vector3D()

    def get_transform(self) -> carla.Transform:
        return carla.Transform()


def _ego_with_writer(control: carla.VehicleControl) -> EgoVehicle:
    ego = object.__new__(EgoVehicle)
    ego.carla_actor = _Actor(control)
    ego.world = _World()
    ego.vehicle_chassis_writer = _Writer()
    ego.tf_writer = _Writer()
    ego.get_tf_msg = lambda _timestamp: TransformStamped()
    ego.write_localization = lambda _timestamp: None
    ego.control_telemetry = None
    return ego


def _published_gear(control: carla.VehicleControl) -> int:
    ego = _ego_with_writer(control)
    EgoVehicle.send_vehicle_msgs(ego, 1.0)
    assert len(ego.vehicle_chassis_writer.messages) == 1
    return int(ego.vehicle_chassis_writer.messages[0].gear_location)


def _paired_record(control: carla.VehicleControl) -> dict:
    ego = _ego_with_writer(control)
    ego.control_telemetry = io.StringIO()
    EgoVehicle.send_vehicle_msgs(ego, 2.5)
    return json.loads(ego.control_telemetry.getvalue())


def main() -> None:
    neutral = carla.VehicleControl(reverse=False, hand_brake=False, gear=0)
    drive = carla.VehicleControl(reverse=False, hand_brake=False, gear=1)
    reverse = carla.VehicleControl(reverse=True, hand_brake=False, gear=-1)
    reverse_by_gear = carla.VehicleControl(reverse=False, hand_brake=False, gear=-1)
    parking = carla.VehicleControl(reverse=False, hand_brake=True, gear=1)
    observed = {
        "neutral": _published_gear(neutral),
        "drive": _published_gear(drive),
        "reverse": _published_gear(reverse),
        "reverse_by_gear": _published_gear(reverse_by_gear),
        "parking": _published_gear(parking),
    }
    expected = {
        "neutral": int(Chassis.GearPosition.GEAR_NEUTRAL),
        "drive": int(Chassis.GearPosition.GEAR_DRIVE),
        "reverse": int(Chassis.GearPosition.GEAR_REVERSE),
        "reverse_by_gear": int(Chassis.GearPosition.GEAR_REVERSE),
        "parking": int(Chassis.GearPosition.GEAR_PARKING),
    }
    if observed != expected:
        raise SystemExit(f"bridge gear mapping mismatch observed={observed} expected={expected}")

    paired = {name: _paired_record(control) for name, control in (
        ("neutral", neutral),
        ("drive", drive),
        ("reverse", reverse),
        ("parking", parking),
    )}
    for name, record in paired.items():
        if record["record_type"] != "chassis_feedback":
            raise SystemExit(f"missing paired chassis record for {name}: {record}")
        if record["carla_actual"]["gear"] != {
            "neutral": 0, "drive": 1, "reverse": -1, "parking": 1
        }[name]:
            raise SystemExit(f"wrong paired actual gear for {name}: {record}")
        if record["apollo_published"]["gear_location"] != expected[name]:
            raise SystemExit(f"wrong paired published gear for {name}: {record}")

    transition_actor = _Actor(drive)
    transition_ego = _ego_with_writer(drive)
    transition_ego.carla_actor = transition_actor
    transition_gears = []
    for control in (neutral, drive, reverse, reverse_by_gear, drive, parking):
        transition_actor.control = control
        EgoVehicle.send_vehicle_msgs(transition_ego, 1.0)
        transition_gears.append(
            int(transition_ego.vehicle_chassis_writer.messages[-1].gear_location)
        )
    expected_transition = [
        expected["neutral"],
        expected["drive"],
        expected["reverse"],
        expected["reverse_by_gear"],
        expected["drive"],
        expected["parking"],
    ]
    if transition_gears != expected_transition:
        raise SystemExit(
            "bridge gear transition mismatch "
            f"observed={transition_gears} expected={expected_transition}"
        )
    print(
        "bridge_gear_mapping=PASS "
        f"observed={observed} transition={transition_gears} paired=PASS"
    )


if __name__ == "__main__":
    main()
