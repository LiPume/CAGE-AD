#!/usr/bin/env python3
"""Summarize one instrumented P2-D run without changing its primary evidence."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import statistics


LOG_TIME = re.compile(r"^[IWEF]\d{4} (\d\d:\d\d:\d\d\.\d{6}) ")
LOG_EVENTS = {
    "lane_borrow_enter": "Switch from SELF-LANE path to LANE-BORROW path.",
    "speed_optimizer_failure": "Piecewise jerk speed optimizer failed!.try to fallback.",
    "speed_fallback": "Use last frame good path to do speed fallback",
    "path_bound_failure": "Decide path bound failed",
    "path_optimizer_failure": "Optmize path failed",
}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return sorted(values)[min(len(values) - 1, int(fraction * len(values)))]


def event_record(index: int, row: dict) -> dict:
    return {
        "planning_index": index,
        "clock_s": row.get("clock_s"),
        "sequence_num": row["header"]["sequence_num"],
        "init_point": row["init_point"],
        "trajectory": row["trajectory"],
        "paths": [value["name"] for value in row["paths"]],
        "speed_plans": row["speed_plans"],
        "target_obstacle_debug": row["target_obstacle_debug"],
        "input_ages_s": row["input_ages_s"],
    }


def first_matching(rows: list[dict], predicate) -> dict | None:
    for index, row in enumerate(rows):
        if predicate(row):
            return event_record(index, row)
    return None


def first_control_matching(rows: list[dict], predicate) -> dict | None:
    for index, row in enumerate(rows):
        if predicate(row):
            return {
                "control_index": index,
                "clock_s": row.get("clock_s"),
                "header": row["header"],
                "throttle": row["throttle"],
                "brake": row["brake"],
                "steering_target": row["steering_target"],
                "speed": row["speed"],
                "acceleration": row["acceleration"],
                "is_in_safe_mode": row["is_in_safe_mode"],
            }
    return None


def parse_log(path: Path) -> dict:
    counts = {name: 0 for name in LOG_EVENTS}
    first = {name: None for name in LOG_EVENTS}
    first_times = {}
    with path.open(errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            for name, marker in LOG_EVENTS.items():
                if marker not in line:
                    continue
                counts[name] += 1
                if first[name] is None:
                    matched = LOG_TIME.match(line)
                    parsed = (datetime.strptime(matched.group(1), "%H:%M:%S.%f")
                              if matched else None)
                    first_times[name] = parsed
                    first[name] = {
                        "line_number": line_number,
                        "wall_time": matched.group(1) if matched else None,
                        "text": line.rstrip()[:1000],
                    }
    lane_time = first_times.get("lane_borrow_enter")
    if lane_time:
        for name, item in first.items():
            if item is not None and first_times.get(name):
                item["seconds_after_lane_borrow_enter"] = (
                    first_times[name] - lane_time
                ).total_seconds()
    return {"path": str(path.resolve()), "counts": counts, "first_events": first}


def normalize_age(row: dict, key: str) -> float | None:
    ages = row["input_ages_s"]
    if key in ages:
        return ages[key]
    # Debug 02 used an ambiguous legacy label. Recompute the sim-domain ages from retained fields.
    if key == "prediction_wall_clock":
        timestamp = row["embedded_inputs"]["prediction_header"]["timestamp_sec"]
        return None if timestamp <= 0.0 else row["header"]["timestamp_sec"] - timestamp
    source = "localization_header" if key.startswith("localization") else "chassis_header"
    clock = row.get("clock_s")
    timestamp = row["embedded_inputs"][source]["timestamp_sec"]
    return None if clock is None or timestamp <= 0.0 else clock - timestamp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = json.loads((args.run_dir / "summary.json").read_text())
    rows = [json.loads(line) for line in
            (args.run_dir / "planning_input_timeline.jsonl").read_text().splitlines()
            if line.strip()]
    planning = [row for row in rows if row["event"] == "planning_raw"]
    prediction = [row for row in rows if row["event"] == "prediction"]
    control = [row for row in rows if row["event"] == "control"]
    observation_start = next(
        (row for row in rows if row["event"] == "observation_start"), None
    )
    native_index = json.loads((args.run_dir / "native_planning_logs.json").read_text())
    native_logs = [Path(record["path"]) for record in native_index["files"]
                   if ".INFO." in Path(record["path"]).name]
    log_analysis = parse_log(native_logs[0]) if len(native_logs) == 1 else {
        "error": f"expected one native INFO log, found {len(native_logs)}"
    }
    bridge_telemetry_path = args.run_dir / "bridge_control_telemetry.jsonl"
    bridge_telemetry = []
    if bridge_telemetry_path.exists():
        bridge_telemetry = [json.loads(line) for line in bridge_telemetry_path.read_text().splitlines()
                            if line.strip()]
    control_apply = [row for row in bridge_telemetry if row["record_type"] == "control_apply"]
    chassis_feedback = [row for row in bridge_telemetry
                        if row["record_type"] == "chassis_feedback"]

    def first_bridge(values, predicate):
        return next((value for value in values if predicate(value)), None)

    age_keys = ("prediction_wall_clock", "localization_sim_clock", "chassis_sim_clock")
    age_stats = {}
    for key in age_keys:
        values = [normalize_age(row, key) for row in planning]
        values = [value for value in values if value is not None]
        age_stats[key] = {
            "min": min(values, default=None),
            "median": statistics.median(values) if values else None,
            "p95": percentile(values, 0.95),
            "max": max(values, default=None),
        }
    latencies = [row["latency"]["total_time_ms"] for row in planning]
    result = {
        "schema_version": 1,
        "run_id": summary["screening_id"],
        "admission_evidence": summary.get("admission_evidence"),
        "primary_result": summary["admission"],
        "metrics": summary["metrics"],
        "determinism": summary.get("determinism"),
        "timeline": {
            "total_events": len(rows),
            "planning_events": len(planning),
            "prediction_events": len(prediction),
            "control_events": len(control),
            "observation_start": observation_start,
            "input_age_stats_s": age_stats,
            "planning_latency_ms": {
                "median": statistics.median(latencies) if latencies else None,
                "p95": percentile(latencies, 0.95),
                "max": max(latencies, default=None),
            },
            "first_normal_trajectory": first_matching(
                planning, lambda row: row["trajectory"]["trajectory_type"] == 1
            ),
            "first_leftreverse_candidate": first_matching(
                planning, lambda row: any("leftreverse" in value["name"] for value in row["paths"])
            ),
            "first_target_left_nudge": first_matching(
                planning, lambda row: any(
                    "nudge" in tag["decision_fields"]
                    for obstacle in row["target_obstacle_debug"]
                    for tag in obstacle["decision_tags"]
                )
            ),
            "first_speed_fallback": first_matching(
                planning, lambda row: row["trajectory"]["trajectory_type"] == 3
            ),
            "first_negative_init_speed": first_matching(
                planning, lambda row: row["init_point"]["v"] < 0.0
            ),
            "first_leftreverse_only": first_matching(
                planning, lambda row: (
                    any("leftreverse" in value["name"] for value in row["paths"])
                    and not any("regular/self" in value["name"] for value in row["paths"])
                )
            ),
            "first_control_command": first_control_matching(control, lambda _row: True),
            "first_control_target_speed_nonzero": first_control_matching(
                control, lambda row: row["speed"] > 0.01
            ),
            "first_positive_throttle": first_control_matching(
                control, lambda row: row["throttle"] > 0.01 and row["brake"] < 0.01
            ),
        },
        "native_planning_log": log_analysis,
        "bridge_control_telemetry": {
            "available": bridge_telemetry_path.exists(),
            "record_count": len(bridge_telemetry),
            "control_apply_count": len(control_apply),
            "chassis_feedback_count": len(chassis_feedback),
            "first_positive_throttle_apply": first_bridge(
                control_apply,
                lambda row: row["carla_applied"]["throttle"] > 0.0
                and row["carla_applied"]["brake"] == 0.0,
            ),
            "first_drive_gear_feedback": first_bridge(
                chassis_feedback, lambda row: row["carla_actual"]["gear"] > 0
            ),
            "first_moving_feedback": first_bridge(
                chassis_feedback,
                lambda row: row["carla_actual"].get("speed_mps", 0.0) > 0.01,
            ),
        },
    }
    output = args.output or args.run_dir / "debug_analysis.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
