#!/usr/bin/env python3
"""Audit the longitudinal chain from frozen runtime evidence without simulation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import fmean, median


def finite(values):
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def describe(values):
    values = sorted(finite(values))
    return {
        "count": len(values),
        "min": values[0],
        "median": median(values),
        "mean": fmean(values),
        "max": values[-1],
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def calibration_entries(path: Path) -> list[dict]:
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
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--calibration-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.trace.read_text().splitlines()]
    complete = [
        row for row in rows
        if row["apollo"]["planning"]
        and row["apollo"]["control_guarded"]
        and row["apollo"]["localization"]
    ]
    gear_one = [row for row in complete if row["carla"]["actual_gear"] == 1]
    applies = [
        json.loads(line) for line in args.telemetry.read_text().splitlines()
        if json.loads(line).get("record_type") == "control_apply"
    ]
    gain_errors = [
        abs(
            record["carla_applied"]["throttle"]
            - min(1.0, max(0.0, record["apollo"]["throttle_percentage"] * 1.5 / 100.0))
        )
        for record in applies
    ]
    table = calibration_entries(args.calibration_table)
    debug = [row["apollo"]["control_guarded"]["simple_lon_debug"] for row in gear_one]
    apollo_throttle = [row["apollo"]["control_guarded"]["throttle_percentage"] for row in gear_one]

    summary = {
        "schema_version": 1,
        "label": "OFFLINE_CONTROL_LOOP_AUDIT_NOT_DATASET",
        "trace_frames": len(rows),
        "complete_signal_frames": len(complete),
        "actual_gear_one_frames": len(gear_one),
        "signals_at_actual_gear_one": {
            "planning_target_speed_at_plus_1s_mps": describe(
                row["apollo"]["planning"]["target_speed_1s_mps"] for row in gear_one
            ),
            "planning_target_acceleration_at_plus_1s_mps2": describe(
                row["apollo"]["planning"]["target_acceleration_1s_mps2"] for row in gear_one
            ),
            "control_current_speed_reference_mps": describe(
                item["speed_reference"] for item in debug
            ),
            "control_preview_speed_reference_mps": describe(
                item["preview_speed_reference"] for item in debug
            ),
            "control_acceleration_command_mps2": describe(
                item["acceleration_cmd"] for item in debug
            ),
            "calibration_value_percent": describe(
                item["calibration_value"] for item in debug
            ),
            "apollo_throttle_percent": describe(apollo_throttle),
            "carla_applied_throttle": describe(
                row["carla"]["throttle"] for row in gear_one
            ),
            "carla_longitudinal_acceleration_mps2": describe(
                row["carla"]["acceleration"]["longitudinal_mps2"] for row in gear_one
            ),
            "carla_speed_mps": describe(row["carla"]["speed_mps"] for row in gear_one),
            "throttle_at_15_7_percent_frames": sum(
                abs(value - 15.7) < 1e-5 for value in apollo_throttle
            ),
            "positive_acceleration_lookup_with_negative_calibration_frames": sum(
                item["acceleration_lookup"] >= 0.0 and item["calibration_value"] < 0.0
                for item in debug
            ),
        },
        "paired_bridge_transmission": {
            "control_apply_records": len(applies),
            "expected_gain": 1.5,
            "max_absolute_throttle_error": max(gain_errors),
            "error_over_1e_6_records": sum(error > 1e-6 for error in gain_errors),
        },
        "active_calibration_table": {
            "sha256": sha256(args.calibration_table),
            "entries": len(table),
            "speed_grid_points": len({entry["speed"] for entry in table}),
            "nonnegative_acceleration_negative_command_entries": sum(
                entry["acceleration"] >= 0.0 and entry["command"] < 0.0
                for entry in table
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, args.output)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
