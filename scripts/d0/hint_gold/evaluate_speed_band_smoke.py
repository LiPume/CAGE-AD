#!/usr/bin/env python3
"""Evaluate a frozen empty-road Apollo smoke for the 2-to-4 m/s table."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import median


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


_SPEED_OPTIMIZER_FAILURE = re.compile(
    r"(?:speed\s+optimizer\s+failed|speed\s+optimization\s+failed|failed\s+to\s+optimize\s+speed)",
    re.IGNORECASE,
)


def has_speed_optimizer_failure(stack_log: str) -> bool:
    """Recognize Apollo speed-optimizer failures without case-sensitive wording gaps."""

    return _SPEED_OPTIMIZER_FAILURE.search(stack_log) is not None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-data", type=Path, required=True)
    parser.add_argument("--legacy-result", type=Path, required=True)
    parser.add_argument("--expected-table-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary = load_json(args.run_data / "runtime_summary.json")
    legacy = load_json(args.legacy_result)
    interposer = load_json(args.run_data / "private/interposer_stats.json")
    trace = [
        json.loads(line)
        for line in (args.run_data / "trace.jsonl").read_text().splitlines()
    ]
    telemetry = [
        json.loads(line)
        for line in (args.run_data / "bridge_control_telemetry.jsonl")
        .read_text()
        .splitlines()
    ]
    table = (
        args.run_data
        / "apollo_conf/modules/control/control_component/conf/calibration_table.pb.txt"
    )
    stack_log = (args.run_data / "logs/stack.log").read_text(errors="replace")

    speeds = [float(row["carla"]["speed_mps"]) for row in trace]
    last_half = speeds[len(speeds) // 2 :]
    positions = [
        (float(row["carla"]["x"]), float(row["carla"]["y"])) for row in trace
    ]
    start_x, start_y = positions[0]
    max_lateral_deviation = max(abs(y - start_y) for _, y in positions)
    applies = [row for row in telemetry if row.get("record_type") == "control_apply"]
    gain_errors = [
        abs(
            float(row["carla_applied"]["throttle"])
            - min(
                1.0,
                max(
                    0.0,
                    float(row["apollo"]["throttle_percentage"]) * 1.5 / 100.0,
                ),
            )
        )
        for row in applies
    ]
    tracking = summary.get("tracking_window", {})
    checks = {
        "legacy_runtime_exit_zero": int(legacy.get("runtime_exit", -1)) == 0,
        "exactly_400_trace_frames": len(trace) == 400,
        "summary_trace_frames_400": int(summary.get("trace_frames", 0)) == 400,
        "no_frame_gaps": int(summary.get("non_unit_frame_gaps", -1)) == 0,
        "no_npc": int(summary.get("npc_vehicle_count", -1)) == 0,
        "route_accepted": bool(summary.get("route", {}).get("route_accepted")),
        "planning_coverage_at_least_0_95": float(
            summary.get("valid_trajectory_frame_coverage", 0.0)
        )
        >= 0.95,
        "nominal_identity_interposer": (
            int(interposer.get("fault_applications", -1)) == 0
            and interposer.get("injector_exception") is None
            and int(interposer.get("planning_in", -1))
            == int(interposer.get("planning_out", -2))
            and int(interposer.get("control_in", -1))
            == int(interposer.get("control_out", -2))
        ),
        "exact_candidate_table_loaded": table.is_file()
        and sha256(table) == args.expected_table_sha256,
        "bridge_gain_records_present": len(applies) > 0,
        "bridge_gain_error_at_most_1e_6": bool(gain_errors)
        and max(gain_errors) <= 1e-6,
        "speed_max_at_least_3_5_mps": max(speeds) >= 3.5,
        "speed_max_at_most_6_0_mps": max(speeds) <= 6.0,
        "last_half_speed_median_at_least_3_0_mps": median(last_half) >= 3.0,
        "tracking_ratio_at_least_0_80": float(
            tracking.get("actual_to_target_ratio", 0.0)
        )
        >= 0.80,
        "brake_active_fraction_at_most_0_10": float(
            summary.get("brake_active_fraction", 1.0)
        )
        <= 0.10,
        "max_lateral_deviation_at_most_0_20_m": max_lateral_deviation <= 0.20,
        "speed_optimizer_failures_zero": not has_speed_optimizer_failure(stack_log),
    }
    result = {
        "schema_version": 1,
        "label": "HINT_GOLD_SPEED_BAND_EMPTY_ROAD_VALIDATION_NOT_DATASET",
        "run_id": summary.get("run_id"),
        "expected_table_sha256": args.expected_table_sha256,
        "loaded_table_sha256": sha256(table) if table.is_file() else None,
        "metrics": {
            "trace_frames": len(trace),
            "speed_max_mps": max(speeds),
            "speed_median_mps": median(speeds),
            "last_half_speed_median_mps": median(last_half),
            "progress_m": math.hypot(
                positions[-1][0] - start_x, positions[-1][1] - start_y
            ),
            "tracking_ratio": tracking.get("actual_to_target_ratio"),
            "planning_coverage": summary.get("valid_trajectory_frame_coverage"),
            "brake_active_fraction": summary.get("brake_active_fraction"),
            "max_lateral_deviation_m": max_lateral_deviation,
            "control_apply_records": len(applies),
            "bridge_gain_max_absolute_error": max(gain_errors) if gain_errors else None,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
