#!/usr/bin/env python3
"""Audit a fixed time-separated adjacent-lane merge scene."""

from __future__ import annotations

import argparse, hashlib, json, os, statistics
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def trajectories(event: dict) -> int:
    prediction = ((event.get("latest_channel_inputs") or {}).get("prediction") or {})
    target = prediction.get("target") or {}
    return int(target.get("trajectory_count", 0) or 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--source-lane", type=int, required=True)
    parser.add_argument("--target-lane", type=int, required=True)
    parser.add_argument("--merge-start-s", type=float, required=True)
    parser.add_argument("--merge-end-s", type=float, required=True)
    parser.add_argument("--minimum-post-merge-overlap-frames", type=int, required=True)
    parser.add_argument(
        "--expected-policy-type",
        default="CARLA_TIMED_ADJACENT_LANE_MERGE_LOCAL_VELOCITY",
    )
    parser.add_argument("--require-target-lane-before-pass-margin-m", type=float)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    events = [json.loads(line) for line in args.timeline.read_text().splitlines() if line.strip()]
    summary = json.loads(args.summary.read_text())
    observation_clock = float(next(
        event["simulation_elapsed_seconds"] for event in events
        if event.get("event") == "observation_start"
    ))
    samples = summary["samples"]
    before = [s for s in samples if float(s["elapsed_s"]) <= args.merge_start_s - 0.5]
    after = [s for s in samples if args.merge_end_s + 0.5 <= float(s["elapsed_s"]) <= args.merge_end_s + 5.0]
    moving = [s for s in samples if 1.0 <= float(s["elapsed_s"]) <= args.merge_end_s + 5.0]
    planning = [event for event in events if event.get("event") == "planning_raw"]
    overlap = []
    for event in planning:
        elapsed = float(event["clock_s"]) - observation_clock
        if not (args.merge_end_s <= elapsed <= args.merge_end_s + 7.0):
            continue
        if trajectories(event) <= 0:
            continue
        if not any("lane_change" in path["name"] for path in event.get("paths", [])):
            continue
        overlap.append(elapsed)
    policy = summary["determinism"]["npc_policy"]
    before_lanes = sorted({int(s["npc_carla_lane_id"]) for s in before})
    after_lanes = sorted({int(s["npc_carla_lane_id"]) for s in after})
    median_speed = statistics.median(float(s["npc_speed_mps"]) for s in moving)
    first_target_lane_s = next(
        (float(s["elapsed_s"]) for s in samples if int(s["npc_carla_lane_id"]) == args.target_lane),
        None,
    )
    first_pass_margin_s = None
    if args.require_target_lane_before_pass_margin_m is not None:
        first_pass_margin_s = next(
            (
                float(s["elapsed_s"])
                for s in samples
                if float(s["pass_margin_m"])
                >= args.require_target_lane_before_pass_margin_m
            ),
            None,
        )
    trigger = policy.get("trigger", policy.get("release_trigger"))
    ackermann_expected = args.expected_policy_type == "CARLA_TIMED_ACKERMANN_LANE_MERGE"
    checks = {
        "policy_type": policy["type"] == args.expected_policy_type,
        "simulation_time_trigger": trigger == "SIMULATION_ELAPSED_SINCE_OBSERVATION_START",
        "no_apollo_output": policy["apollo_output_used"] is False,
        "no_ego_state": policy["ego_state_used"] is False,
        "no_future_ground_truth": policy["future_ground_truth_used"] is False,
        "no_pose_or_velocity_override": policy.get("pose_or_velocity_override_used", False) is False,
        "physical_ackermann_transport": (
            policy.get("command_transport") == "VEHICLE_APPLY_ACKERMANN_CONTROL"
            if ackermann_expected else True
        ),
        "source_lane_before_merge": bool(before) and before_lanes == [args.source_lane],
        "target_lane_after_merge": bool(after) and after_lanes == [args.target_lane],
        "continuous_speed": 1.05 <= median_speed <= 1.15,
        "post_merge_trajectory_lane_change_overlap": len(overlap)
        >= args.minimum_post_merge_overlap_frames,
        "prediction_coverage": summary["metrics"]["target_prediction_trajectory_coverage"] >= 0.90,
    }
    if args.require_target_lane_before_pass_margin_m is not None:
        checks["target_lane_entry_precedes_pass_outcome"] = (
            first_target_lane_s is not None
            and first_pass_margin_s is not None
            and first_target_lane_s < first_pass_margin_s
        )
    result = {
        "schema_version": 1,
        "analysis_type": "TIMED_MERGE_FIXED_SCREEN",
        "inputs": {"timeline": str(args.timeline), "timeline_sha256": sha256(args.timeline), "summary": str(args.summary), "summary_sha256": sha256(args.summary)},
        "frozen_gate": {"source_lane": args.source_lane, "target_lane": args.target_lane, "merge_start_s": args.merge_start_s, "merge_end_s": args.merge_end_s, "minimum_post_merge_overlap_frames": args.minimum_post_merge_overlap_frames, "expected_policy_type": args.expected_policy_type, "require_target_lane_before_pass_margin_m": args.require_target_lane_before_pass_margin_m},
        "metrics": {"before_lanes": before_lanes, "after_lanes": after_lanes, "median_speed_mps": median_speed, "post_merge_overlap_frames": len(overlap), "first_post_merge_overlap_s": min(overlap) if overlap else None, "last_post_merge_overlap_s": max(overlap) if overlap else None, "prediction_trajectory_coverage": summary["metrics"]["target_prediction_trajectory_coverage"], "first_target_lane_s": first_target_lane_s, "first_pass_margin_s": first_pass_margin_s},
        "policy": policy,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "REJECT",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
