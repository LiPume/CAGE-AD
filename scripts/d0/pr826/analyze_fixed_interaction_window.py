#!/usr/bin/env python3
"""Measure fixed-arm overlap between target trajectories and lane-change Planning paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--minimum-overlap-frames", type=int, default=10)
    parser.add_argument("--maximum-first-overlap-elapsed-s", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    events = [json.loads(line) for line in args.timeline.read_text().splitlines() if line.strip()]
    summary = json.loads(args.summary.read_text())
    observation_clock = float(next(
        event["simulation_elapsed_seconds"]
        for event in events
        if event.get("event") == "observation_start"
    ))
    policy = summary["determinism"]["npc_policy"]
    release_elapsed = float(policy["release_command_elapsed_s"])
    planning = [event for event in events if event.get("event") == "planning_raw"]
    lane_change_frames = [
        event
        for event in planning
        if any("lane_change" in path["name"] for path in event.get("paths", []))
    ]
    trajectory_frames = [
        event
        for event in planning
        if event.get("latest_channel_inputs", {})
        .get("prediction", {})
        .get("target", {})
        .get("trajectory_count", 0)
        > 0
    ]
    overlap = [
        event
        for event in lane_change_frames
        if event.get("latest_channel_inputs", {})
        .get("prediction", {})
        .get("target", {})
        .get("trajectory_count", 0)
        > 0
    ]
    overlap_elapsed = [float(event["clock_s"]) - observation_clock for event in overlap]
    samples = summary["samples"]
    held_samples = [sample for sample in samples if float(sample["elapsed_s"]) < release_elapsed]
    moving_samples = [
        sample
        for sample in samples
        if release_elapsed + 1.0 <= float(sample["elapsed_s"]) <= release_elapsed + 5.0
    ]
    checks = {
        "policy_type": policy["type"]
        == "CARLA_HOLD_THEN_CONSTANT_LOCAL_VELOCITY_LANE_TANGENT",
        "release_trigger_simulation_time": policy["release_trigger"]
        == "SIMULATION_ELAPSED_SINCE_OBSERVATION_START",
        "no_apollo_output_used": policy["apollo_output_used"] is False,
        "no_future_ground_truth_used": policy["future_ground_truth_used"] is False,
        "held_speed_max_at_most_0_10_mps": bool(held_samples)
        and max(float(sample["npc_speed_mps"]) for sample in held_samples) <= 0.10,
        "moving_speed_median_in_1_05_to_1_15_mps": bool(moving_samples)
        and 1.05
        <= statistics.median(float(sample["npc_speed_mps"]) for sample in moving_samples)
        <= 1.15,
        "trajectory_lane_change_overlap_frames": len(overlap) >= args.minimum_overlap_frames,
        "first_overlap_within_window": bool(overlap_elapsed)
        and min(overlap_elapsed) <= args.maximum_first_overlap_elapsed_s,
    }
    result = {
        "schema_version": 1,
        "analysis_type": "FIXED_ARM_INTERACTION_WINDOW",
        "inputs": {
            "timeline": str(args.timeline),
            "timeline_sha256": sha256(args.timeline),
            "summary": str(args.summary),
            "summary_sha256": sha256(args.summary),
        },
        "policy": policy,
        "metrics": {
            "release_command_elapsed_s": release_elapsed,
            "lane_change_planning_frames": len(lane_change_frames),
            "trajectory_bearing_planning_frames": len(trajectory_frames),
            "trajectory_lane_change_overlap_frames": len(overlap),
            "first_overlap_elapsed_s": None if not overlap_elapsed else min(overlap_elapsed),
            "last_overlap_elapsed_s": None if not overlap_elapsed else max(overlap_elapsed),
            "held_speed_max_mps": None
            if not held_samples
            else max(float(sample["npc_speed_mps"]) for sample in held_samples),
            "moving_speed_median_mps": None
            if not moving_samples
            else statistics.median(float(sample["npc_speed_mps"]) for sample in moving_samples),
        },
        "frozen_gate": {
            "minimum_overlap_frames": args.minimum_overlap_frames,
            "maximum_first_overlap_elapsed_s": args.maximum_first_overlap_elapsed_s,
        },
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "REJECT",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
