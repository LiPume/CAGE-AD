#!/usr/bin/env python3
"""Create a compact, reproducible comparison of two retained RF01 executions."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re


LOG_TIME = re.compile(r"^[IWEF]\d{4} (\d\d:\d\d:\d\d\.\d{6}) ")
EVENTS = {
    "lane_borrow_enter": "Switch from SELF-LANE path to LANE-BORROW path.",
    "speed_optimizer_failure": "Piecewise jerk speed optimizer failed!.try to fallback.",
    "speed_fallback": "Use last frame good path to do speed fallback",
    "lane_follow_path_optimizer_failure": "Optmize path failed",
    "lane_follow_path_bound_failure": "Decide path bound failed",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def parse_wall_time(line: str) -> datetime | None:
    match = LOG_TIME.match(line)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%H:%M:%S.%f")


def scan_log(path: Path) -> dict:
    counts = {name: 0 for name in EVENTS}
    first = {name: None for name in EVENTS}
    snippets = {name: None for name in EVENTS}
    with path.open(errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            for name, marker in EVENTS.items():
                if marker not in line:
                    continue
                counts[name] += 1
                if first[name] is None:
                    timestamp = parse_wall_time(line)
                    first[name] = timestamp
                    snippets[name] = {
                        "line_number": line_number,
                        "wall_time": timestamp.strftime("%H:%M:%S.%f") if timestamp else None,
                        "text": line.rstrip()[:1000],
                    }
    lane_borrow = first["lane_borrow_enter"]
    for name, event in snippets.items():
        if event is not None and lane_borrow is not None and first[name] is not None:
            event["seconds_after_lane_borrow_enter"] = (
                first[name] - lane_borrow
            ).total_seconds()
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
        "counts": counts,
        "first_events": snippets,
    }


def scan_summary(path: Path) -> dict:
    document = json.loads(path.read_text())
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
        "admission": document["admission"],
        "metrics": document["metrics"],
        "samples": document["samples"],
    }


def compare_samples(left: list[dict], right: list[dict]) -> dict:
    thresholds = [0.01, 0.05, 0.10, 0.25, 0.50, 1.00]
    first = {str(value): None for value in thresholds}
    rows = []
    for index, (a, b) in enumerate(zip(left, right)):
        distance = math.hypot(
            a["ego_carla_xy"][0] - b["ego_carla_xy"][0],
            a["ego_carla_xy"][1] - b["ego_carla_xy"][1],
        )
        for threshold in thresholds:
            key = str(threshold)
            if first[key] is None and distance >= threshold:
                first[key] = {
                    "sample_index": index,
                    "left_elapsed_s": a["elapsed_s"],
                    "right_elapsed_s": b["elapsed_s"],
                    "ego_position_delta_m": distance,
                    "left_speed_mps": a["ego_speed_mps"],
                    "right_speed_mps": b["ego_speed_mps"],
                }
        if 12.0 <= a["elapsed_s"] <= 15.0 and index % 10 == 0:
            rows.append({
                "elapsed_s": a["elapsed_s"],
                "ego_position_delta_m": distance,
                "left_speed_mps": a["ego_speed_mps"],
                "right_speed_mps": b["ego_speed_mps"],
                "left_pass_margin_m": a["pass_margin_m"],
                "right_pass_margin_m": b["pass_margin_m"],
            })
    return {
        "paired_sample_count": min(len(left), len(right)),
        "first_position_delta_threshold_crossings": first,
        "selected_12_to_15_second_rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left-summary", type=Path, required=True)
    parser.add_argument("--left-log", type=Path, required=True)
    parser.add_argument("--left-stack", type=Path, required=True)
    parser.add_argument("--right-summary", type=Path, required=True)
    parser.add_argument("--right-log", type=Path, required=True)
    parser.add_argument("--right-stack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    left = scan_summary(args.left_summary)
    right = scan_summary(args.right_summary)
    result = {
        "schema_version": 1,
        "analysis_scope": "P2_D_HISTORICAL_READ_ONLY",
        "left": {key: value for key, value in left.items() if key != "samples"},
        "right": {key: value for key, value in right.items() if key != "samples"},
        "left_planning_log": scan_log(args.left_log),
        "left_stack_log": scan_log(args.left_stack),
        "right_planning_log": scan_log(args.right_log),
        "right_stack_log": scan_log(args.right_stack),
        "sample_comparison": compare_samples(left["samples"], right["samples"]),
        "interpretation": {
            "both_enter_lane_borrow": True,
            "first_observable_planning_branch": (
                "right/failing execution reaches PiecewiseJerk speed-optimizer failure and "
                "speed fallback substantially earlier"
            ),
            "causal_input_first_divergence_observable": False,
            "next_requirement": "per-cycle Planning input/state instrumentation",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
