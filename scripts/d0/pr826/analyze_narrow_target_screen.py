#!/usr/bin/env python3
"""Audit the fixed narrow-target timing/geometry gate without changing runtime state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def target_trajectory_count(event: dict) -> int:
    inputs = event.get("latest_channel_inputs") or {}
    prediction = inputs.get("prediction") or {}
    target = prediction.get("target") or {}
    return int(target.get("trajectory_count", 0) or 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-blueprint", required=True)
    parser.add_argument("--expected-lane-id", type=int, required=True)
    parser.add_argument("--minimum-early-offset-m", type=float, required=True)
    parser.add_argument("--early-window-s", type=float, required=True)
    parser.add_argument("--maximum-first-lane-change-s", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    events = [json.loads(line) for line in args.timeline.read_text().splitlines() if line.strip()]
    summary = json.loads(args.summary.read_text())
    observation_clock = float(next(
        event["simulation_elapsed_seconds"]
        for event in events
        if event.get("event") == "observation_start"
    ))
    planning = [event for event in events if event.get("event") == "planning_raw"]
    lane_change = [
        event for event in planning
        if any("lane_change" in path["name"] for path in event.get("paths", []))
    ]
    overlap = [event for event in lane_change if target_trajectory_count(event) > 0]
    overlap_elapsed = [float(event["clock_s"]) - observation_clock for event in overlap]
    samples = summary["samples"]
    early = [
        sample for sample in samples
        if float(sample["elapsed_s"]) <= args.early_window_s
    ]
    actor = summary["determinism"]["actors_at_runtime_start"]["target_npc"]
    extent = actor["bounding_box_extent"]
    full_length = 2.0 * float(extent[0])
    full_width = 2.0 * float(extent[1])
    policy = summary["determinism"]["npc_policy"]
    metrics = summary["metrics"]
    lane_ids = sorted({int(sample["npc_carla_lane_id"]) for sample in samples})
    minimum_early_offset = min(
        float(sample["npc_lane_center_distance_m"]) for sample in early
    ) if early else None
    first_overlap = min(overlap_elapsed) if overlap_elapsed else None
    checks = {
        "actor_blueprint": actor["type_id"] == args.expected_blueprint,
        "actor_width_1_47_to_1_49_m": 1.47 <= full_width <= 1.49,
        "actor_length_2_19_to_2_22_m": 2.19 <= full_length <= 2.22,
        "continuous_lane_tangent_policy": policy["type"]
        == "CARLA_CONSTANT_LOCAL_VELOCITY_LANE_TANGENT",
        "no_future_ground_truth_used": policy["future_ground_truth_used"] is False,
        "target_lane_stable": lane_ids == [args.expected_lane_id],
        "early_offset": minimum_early_offset is not None
        and minimum_early_offset >= args.minimum_early_offset_m,
        "first_trajectory_lane_change_overlap": first_overlap is not None
        and first_overlap <= args.maximum_first_lane_change_s,
        "prediction_trajectory_coverage": float(
            metrics["target_prediction_trajectory_coverage"]
        ) >= 0.90,
    }
    result = {
        "schema_version": 1,
        "analysis_type": "NARROW_TARGET_FIXED_SCREEN",
        "inputs": {
            "timeline": str(args.timeline),
            "timeline_sha256": sha256(args.timeline),
            "summary": str(args.summary),
            "summary_sha256": sha256(args.summary),
        },
        "frozen_gate": {
            "expected_blueprint": args.expected_blueprint,
            "expected_lane_id": args.expected_lane_id,
            "minimum_early_offset_m": args.minimum_early_offset_m,
            "early_window_s": args.early_window_s,
            "maximum_first_lane_change_s": args.maximum_first_lane_change_s,
        },
        "metrics": {
            "full_length_m": full_length,
            "full_width_m": full_width,
            "lane_ids": lane_ids,
            "minimum_early_offset_m": minimum_early_offset,
            "lane_change_planning_frames": len(lane_change),
            "trajectory_lane_change_overlap_frames": len(overlap),
            "first_overlap_elapsed_s": first_overlap,
            "last_overlap_elapsed_s": max(overlap_elapsed) if overlap_elapsed else None,
            "prediction_trajectory_coverage": metrics[
                "target_prediction_trajectory_coverage"
            ],
        },
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "REJECT",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
