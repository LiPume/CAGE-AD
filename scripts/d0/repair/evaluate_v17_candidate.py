#!/usr/bin/env python3
"""Evaluate the frozen V17 contract from saved evidence only."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
from pathlib import Path
import re
from statistics import median


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_table(path: Path) -> dict[float, dict[float, float]]:
    table: dict[float, dict[float, float]] = {}
    for block in re.findall(r"calibration\s*\{(.*?)\}", path.read_text(), re.S):
        fields = {key: float(value) for key, value in re.findall(
            r"(speed|acceleration|command):\s*([-+0-9.eE]+)", block
        )}
        if len(fields) == 3:
            table.setdefault(fields["speed"], {})[fields["acceleration"]] = fields["command"]
    if not table:
        raise ValueError(f"no calibration entries in {path}")
    return table


def interpolate_line(values: dict[float, float], key: float) -> float:
    keys = sorted(values)
    if key <= keys[0] + 1e-6:
        return values[keys[0]]
    if key >= keys[-1] - 1e-6:
        return values[keys[-1]]
    index = bisect.bisect_left(keys, key)
    left, right = keys[index - 1], keys[index]
    if abs(key - left) < 1e-6:
        return values[left]
    if abs(key - right) < 1e-6:
        return values[right]
    return values[left] + (values[right] - values[left]) * (key - left) / (right - left)


def interpolate(table: dict[float, dict[float, float]], speed: float, acceleration: float) -> float:
    speeds = sorted(table)
    if speed <= speeds[0] + 1e-6:
        return interpolate_line(table[speeds[0]], acceleration)
    if speed >= speeds[-1] - 1e-6:
        return interpolate_line(table[speeds[-1]], acceleration)
    index = bisect.bisect_left(speeds, speed)
    left, right = speeds[index - 1], speeds[index]
    left_value = interpolate_line(table[left], acceleration)
    right_value = interpolate_line(table[right], acceleration)
    if abs(speed - left) < 1e-6:
        return left_value
    if abs(speed - right) < 1e-6:
        return right_value
    return left_value + (right_value - left_value) * (speed - left) / (right - left)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--stack-log", type=Path, required=True)
    parser.add_argument("--legacy-result", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.trace.read_text().splitlines()]
    summary = json.loads(args.summary.read_text())
    run_manifest = json.loads(args.run_manifest.read_text())
    legacy_result = json.loads(args.legacy_result.read_text())
    candidate = parse_table(args.candidate)
    base = parse_table(args.base)
    candidate_sha = sha256(args.candidate)
    run_table_sha = run_manifest["files"][
        "apollo_conf/modules/control/control_component/conf/calibration_table.pb.txt"
    ]

    candidate_region = []
    for row in rows:
        control = row["apollo"].get("control_guarded")
        debug = None if not control else control.get("simple_lon_debug")
        if not debug:
            continue
        speed_lookup = abs(debug["speed_lookup"])
        acceleration_lookup = debug["acceleration_lookup"]
        if speed_lookup <= 2.0 and acceleration_lookup >= 0.0:
            candidate_region.append({
                "actual": debug["calibration_value"],
                "candidate": interpolate(candidate, speed_lookup, acceleration_lookup),
                "base": interpolate(base, speed_lookup, acceleration_lookup),
                "throttle": control["throttle_percentage"],
            })
    normal = [
        item for item in candidate_region
        if abs(item["actual"]) > 1e-9 or item["throttle"] > 0.0
    ]

    lateral_deviation = max(
        abs(row["carla"]["y"] - rows[0]["carla"]["y"]) for row in rows
    )
    throttle_max = max(row["carla"]["throttle"] for row in rows)
    filtered_accelerations = [
        row["apollo"]["localization"]["linear_acceleration_vrf"]["y"]
        for row in rows if row["apollo"].get("localization")
    ]
    speed_failure_pattern = re.compile(
        r"speed.*optim.*fail|piecewisejerkspeed.*fail|solver failure case", re.I
    )
    speed_optimizer_failures = sum(
        bool(speed_failure_pattern.search(line))
        for line in args.stack_log.read_text(errors="replace").splitlines()
    )

    metrics = {
        "candidate_sha256": candidate_sha,
        "run_table_sha256": run_table_sha,
        "candidate_region_frames": len(candidate_region),
        "startup_zero_frames": len(candidate_region) - len(normal),
        "normal_candidate_frames": len(normal),
        "candidate_matching_frames": sum(
            abs(item["actual"] - item["candidate"]) <= 1e-6 for item in normal
        ),
        "base_matching_frames": sum(
            abs(item["actual"] - item["base"]) <= 1e-6 for item in normal
        ),
        "candidate_max_absolute_error": max(
            (abs(item["actual"] - item["candidate"]) for item in normal), default=None
        ),
        "base_median_absolute_error": median(
            abs(item["actual"] - item["base"]) for item in normal
        ) if normal else None,
        "trace_frames": len(rows),
        "planning_coverage": summary["valid_trajectory_frame_coverage"],
        "speed_optimizer_failures": speed_optimizer_failures,
        "false_drive_feedback_frames": summary["apollo_drive_but_carla_not_gear_one_frames"],
        "sampled_feedback_timing_mismatch_frames": summary["actual_gear_feedback_mismatch_frames"],
        "control_request_before_gear_engagement_frames": summary["drive_gear_mismatch_frames"],
        "max_lateral_deviation_m": lateral_deviation,
        "carla_throttle_max": throttle_max,
        "brake_active_fraction": summary["brake_active_fraction"],
        "filtered_longitudinal_acceleration_min_mps2": min(filtered_accelerations),
        "filtered_longitudinal_acceleration_max_mps2": max(filtered_accelerations),
        "tracking_ratio": summary["tracking_window"]["actual_to_target_ratio"],
        "legacy_evaluator_result": legacy_result["result"],
        "legacy_only_failed_check": [
            key for key, value in legacy_result["checks"].items() if not value
        ],
    }
    checks = {
        "run_loaded_exact_candidate_sha": run_table_sha == candidate_sha,
        "candidate_internal_lookup_active": bool(normal) and all(
            abs(item["actual"] - item["candidate"]) <= 1e-6 for item in normal
        ),
        "base_not_active_in_candidate_region": bool(normal) and all(
            abs(item["actual"] - item["base"]) > 1e-6 for item in normal
        ),
        "exactly_400_frames": len(rows) == 400,
        "no_frame_gaps": summary["non_unit_frame_gaps"] == 0,
        "planning_coverage_at_least_0_95": summary["valid_trajectory_frame_coverage"] >= 0.95,
        "speed_optimizer_failures_zero": speed_optimizer_failures == 0,
        "false_drive_feedback_zero": summary["apollo_drive_but_carla_not_gear_one_frames"] == 0,
        "max_lateral_deviation_at_most_0_20_m": lateral_deviation <= 0.20,
        "carla_throttle_at_most_0_50": throttle_max <= 0.50 + 1e-6,
        "brake_active_fraction_at_most_0_05": summary["brake_active_fraction"] <= 0.05,
        "filtered_acceleration_at_least_minus_6": min(filtered_accelerations) >= -6.0,
        "filtered_acceleration_at_most_2": max(filtered_accelerations) <= 2.0,
        "tracking_ratio_at_least_0_70": summary["tracking_window"]["actual_to_target_ratio"] >= 0.70,
    }
    result = {
        "schema_version": 1,
        "label": "V17_FROZEN_CONTRACT_EVALUATION_NOT_DATASET",
        "execution_source_commit": legacy_result["source_commit"],
        "evaluator_source_commit": args.source_commit,
        "metrics": metrics,
        "checks": checks,
        "passed": all(checks.values()),
        "verdict": "V17_PASS_INTERACTION_SMOKE_ALLOWED" if all(checks.values()) else "V17_REJECT_STOP",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
