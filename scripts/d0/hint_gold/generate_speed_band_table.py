#!/usr/bin/env python3
"""Generate an audited 2-to-4 m/s positive control-table extension."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


SPEED_MIN_EXCLUSIVE_MPS = 2.0
SPEED_MAX_INCLUSIVE_MPS = 4.0
EXPECTED_SPEED_ANCHORS = (2.0, 3.0, 4.0)
EXPECTED_CARLA_THROTTLES = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
BRIDGE_THROTTLE_GAIN = 1.5
ACCELERATION_GRID = (
    0.0,
    0.03,
    0.06,
    0.10,
    0.20,
    0.30,
    0.40,
    0.60,
    0.80,
    1.00,
    1.15,
    1.50,
    2.00,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_table(path: Path) -> list[dict]:
    entries = []
    for block in re.findall(r"calibration\s*\{(.*?)\}", path.read_text(), re.S):
        fields = {
            key: float(value)
            for key, value in re.findall(
                r"(speed|acceleration|command):\s*([-+0-9.eE]+)", block
            )
        }
        if len(fields) == 3:
            entries.append(fields)
    if not entries:
        raise ValueError("no calibration entries parsed")
    return entries


def load_responses(path: Path) -> dict[float, tuple[float, ...]]:
    summary = json.loads(path.read_text())
    if not summary.get("passed"):
        raise ValueError("measurement summary did not pass its preregistered gate")
    if tuple(map(float, summary.get("target_speeds_mps", ()))) != EXPECTED_SPEED_ANCHORS:
        raise ValueError("measurement speed anchors do not match frozen domain")
    if tuple(map(float, summary.get("throttle_levels", ()))) != EXPECTED_CARLA_THROTTLES:
        raise ValueError("measurement throttle levels do not match frozen domain")
    if int(summary.get("repeats", 0)) != 3:
        raise ValueError("measurement must contain three repeats per cell")

    responses: dict[float, tuple[float, ...]] = {}
    for speed in EXPECTED_SPEED_ANCHORS:
        profiles = sorted(
            (
                profile
                for profile in summary.get("profiles", ())
                if float(profile["target_start_speed_mps"]) == speed
            ),
            key=lambda profile: float(profile["throttle"]),
        )
        throttles = tuple(float(profile["throttle"]) for profile in profiles)
        values = tuple(float(profile["median_speed_slope_mps2"]) for profile in profiles)
        if throttles != EXPECTED_CARLA_THROTTLES:
            raise ValueError(f"incomplete response profile at {speed} m/s")
        if any(
            int(profile["repeat_count"]) != 3
            or profile["repeat_speed_slope_range_mps2"] is None
            or float(profile["repeat_speed_slope_range_mps2"]) > 0.20
            for profile in profiles
        ):
            raise ValueError(f"invalid response repeats at {speed} m/s")
        if not all(later > earlier for earlier, later in zip(values, values[1:])):
            raise ValueError(f"response profile is not strictly monotonic at {speed} m/s")
        responses[speed] = values
    return responses


def response_at_speed(
    responses: dict[float, tuple[float, ...]], speed: float
) -> tuple[float, ...]:
    if not SPEED_MIN_EXCLUSIVE_MPS < speed <= SPEED_MAX_INCLUSIVE_MPS:
        raise ValueError("speed is outside replacement domain")
    for left, right in zip(EXPECTED_SPEED_ANCHORS, EXPECTED_SPEED_ANCHORS[1:]):
        if speed <= right:
            ratio = (speed - left) / (right - left)
            return tuple(
                left_value + ratio * (right_value - left_value)
                for left_value, right_value in zip(
                    responses[left], responses[right]
                )
            )
    raise AssertionError("unreachable speed interpolation")


def inverse_command(
    responses: dict[float, tuple[float, ...]], speed: float, acceleration: float
) -> float:
    values = response_at_speed(responses, speed)
    apollo_commands = tuple(
        throttle * 100.0 / BRIDGE_THROTTLE_GAIN
        for throttle in EXPECTED_CARLA_THROTTLES
    )
    if acceleration <= values[0]:
        return apollo_commands[0]
    if acceleration >= values[-1]:
        return apollo_commands[-1]
    for index, (left, right) in enumerate(zip(values, values[1:])):
        if acceleration <= right:
            ratio = (acceleration - left) / (right - left)
            return apollo_commands[index] + ratio * (
                apollo_commands[index + 1] - apollo_commands[index]
            )
    raise AssertionError("unreachable response inversion")


def command_at(entries: list[dict], speed: float, acceleration: float) -> float:
    row = sorted(
        (
            entry
            for entry in entries
            if abs(entry["speed"] - speed) < 1e-9 and entry["acceleration"] >= 0.0
        ),
        key=lambda entry: entry["acceleration"],
    )
    if not row:
        raise ValueError(f"no nonnegative row at speed {speed}")
    if acceleration <= row[0]["acceleration"]:
        return row[0]["command"]
    if acceleration >= row[-1]["acceleration"]:
        return row[-1]["command"]
    for left, right in zip(row, row[1:]):
        if acceleration <= right["acceleration"]:
            ratio = (acceleration - left["acceleration"]) / (
                right["acceleration"] - left["acceleration"]
            )
            return left["command"] + ratio * (
                right["command"] - left["command"]
            )
    raise AssertionError("unreachable command interpolation")


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(value)
    os.replace(temporary, path)


def tuples(entries: list[dict], predicate) -> list[tuple[float, float, float]]:
    return sorted(
        (entry["speed"], entry["acceleration"], entry["command"])
        for entry in entries
        if predicate(entry)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--expected-base-sha256", required=True)
    parser.add_argument("--measurement-summary", type=Path, required=True)
    parser.add_argument("--expected-measurement-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if sha256(args.base) != args.expected_base_sha256:
        raise SystemExit("base calibration SHA256 mismatch")
    if sha256(args.measurement_summary) != args.expected_measurement_sha256:
        raise SystemExit("measurement summary SHA256 mismatch")
    original = parse_table(args.base)
    responses = load_responses(args.measurement_summary)
    speeds = sorted({entry["speed"] for entry in original})
    replacement_speeds = [
        speed
        for speed in speeds
        if SPEED_MIN_EXCLUSIVE_MPS < speed <= SPEED_MAX_INCLUSIVE_MPS
    ]
    if not replacement_speeds or replacement_speeds[-1] != SPEED_MAX_INCLUSIVE_MPS:
        raise SystemExit("base table does not contain the complete replacement speed grid")

    retained = [
        dict(entry)
        for entry in original
        if not (
            SPEED_MIN_EXCLUSIVE_MPS < entry["speed"] <= SPEED_MAX_INCLUSIVE_MPS
            and entry["acceleration"] >= 0.0
        )
    ]
    replacements = [
        {
            "speed": speed,
            "acceleration": acceleration,
            "command": inverse_command(responses, speed, acceleration),
        }
        for speed in replacement_speeds
        for acceleration in ACCELERATION_GRID
    ]
    candidate = sorted(
        retained + replacements,
        key=lambda entry: (entry["speed"], entry["acceleration"]),
    )
    atomic_text(
        args.output,
        "".join(
            "calibration {\n"
            f"  speed: {entry['speed']:.17g}\n"
            f"  acceleration: {entry['acceleration']:.17g}\n"
            f"  command: {entry['command']:.17g}\n"
            "}\n"
            for entry in candidate
        ),
    )
    reparsed = parse_table(args.output)

    preserved_low = lambda entry: entry["speed"] <= SPEED_MIN_EXCLUSIVE_MPS
    preserved_high = lambda entry: entry["speed"] > SPEED_MAX_INCLUSIVE_MPS
    negative = lambda entry: entry["acceleration"] < 0.0
    boundary_accelerations = (0.2, 0.4, 0.6, 1.0, 1.15, 1.5, 2.0)
    boundary_relative_jumps = {
        str(acceleration): abs(
            command_at(reparsed, 2.2, acceleration)
            - command_at(reparsed, 2.0, acceleration)
        )
        / command_at(reparsed, 2.0, acceleration)
        for acceleration in boundary_accelerations
    }
    checks = {
        "measurement_gate_passed": True,
        "all_low_speed_entries_preserved": tuples(original, preserved_low)
        == tuples(reparsed, preserved_low),
        "all_high_speed_entries_preserved": tuples(original, preserved_high)
        == tuples(reparsed, preserved_high),
        "all_negative_entries_preserved": tuples(original, negative)
        == tuples(reparsed, negative),
        "replacement_grid_complete": all(
            sum(
                entry["speed"] == speed and entry["acceleration"] >= 0.0
                for entry in reparsed
            )
            == len(ACCELERATION_GRID)
            for speed in replacement_speeds
        ),
        "commands_bounded_20_to_40_percent": all(
            20.0 <= entry["command"] <= 40.0
            for entry in replacements
        ),
        "two_to_two_point_two_boundary_jump_at_most_10_percent": max(
            boundary_relative_jumps.values()
        )
        <= 0.10,
        "candidate_has_no_nonnegative_acceleration_negative_command": not any(
            entry["acceleration"] >= 0.0 and entry["command"] < 0.0
            for entry in reparsed
        ),
    }
    manifest = {
        "schema_version": 1,
        "label": "HINT_GOLD_RUN_SCOPED_CONTROL_TABLE_CANDIDATE_NOT_DATASET",
        "base_sha256": sha256(args.base),
        "measurement_summary_sha256": sha256(args.measurement_summary),
        "candidate_sha256": sha256(args.output),
        "replacement_domain": {
            "speed_min_exclusive_mps": SPEED_MIN_EXCLUSIVE_MPS,
            "speed_max_inclusive_mps": SPEED_MAX_INCLUSIVE_MPS,
            "nonnegative_acceleration_only": True,
        },
        "speed_anchors_mps": list(EXPECTED_SPEED_ANCHORS),
        "carla_throttles": list(EXPECTED_CARLA_THROTTLES),
        "bridge_throttle_gain": BRIDGE_THROTTLE_GAIN,
        "acceleration_grid_mps2": list(ACCELERATION_GRID),
        "replacement_speed_rows": replacement_speeds,
        "boundary_relative_command_jumps": boundary_relative_jumps,
        "responses_mps2": {
            str(speed): list(values) for speed, values in responses.items()
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    atomic_text(args.manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))
    raise SystemExit(0 if manifest["passed"] else 2)


if __name__ == "__main__":
    main()
