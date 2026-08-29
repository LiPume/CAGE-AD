#!/usr/bin/env python3
"""Audit whether a target can satisfy Apollo's long-term LaneBorrow gate.

This analyzer is deliberately read-only.  It uses the captured Planning timeline
to measure consecutive target states and PathDecider blocking decisions; it does
not infer or modify Apollo state.
"""

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


def max_consecutive(values: list[bool]) -> int:
    maximum = 0
    current = 0
    for value in values:
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--long-term-threshold", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    frames: list[dict] = []
    with args.timeline.open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if item.get("event") != "planning_raw":
                continue
            prediction = (item.get("latest_channel_inputs", {}).get("prediction") or {})
            target = prediction.get("target")
            if target is None:
                continue
            obstacle_debug = item.get("target_obstacle_debug") or []
            blocking = any(
                str(obstacle.get("id", "")).split("_", 1)[0] == args.target_id
                and any(
                    tag.get("decider_tag") == "PathDecider/blocking_obstacle"
                    for tag in obstacle.get("decision_tags", [])
                )
                for obstacle in obstacle_debug
            )
            frames.append(
                {
                    "sequence_num": item.get("header", {}).get("sequence_num"),
                    "ego_speed_mps": item.get("init_point", {}).get("v"),
                    "is_static": bool(target.get("is_static")),
                    "trajectory_count": int(target.get("trajectory_count", 0)),
                    "blocking": blocking,
                }
            )

    blocking_values = [frame["blocking"] for frame in frames]
    static_values = [frame["is_static"] for frame in frames]
    dynamic_trajectory_values = [
        not frame["is_static"] and frame["trajectory_count"] > 0 for frame in frames
    ]
    maximum_blocking = max_consecutive(blocking_values)
    result = {
        "schema_version": 1,
        "timeline_path": str(args.timeline),
        "timeline_sha256": sha256(args.timeline),
        "target_id": args.target_id,
        "planning_frames_with_target": len(frames),
        "static_frames": sum(static_values),
        "dynamic_trajectory_frames": sum(dynamic_trajectory_values),
        "blocking_decision_frames": sum(blocking_values),
        "max_consecutive_static_frames": max_consecutive(static_values),
        "max_consecutive_blocking_decision_frames": maximum_blocking,
        "long_term_blocking_obstacle_cycle_threshold": args.long_term_threshold,
        "long_term_gate_reachable_from_observed_blocking_sequence": (
            maximum_blocking >= args.long_term_threshold
        ),
        "blocking_sequence_numbers": [
            frame["sequence_num"] for frame in frames if frame["blocking"]
        ],
        "classification": (
            "LONG_TERM_BLOCKING_GATE_OBSERVED"
            if maximum_blocking >= args.long_term_threshold
            else "LONG_TERM_BLOCKING_GATE_NOT_REACHED"
        ),
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
