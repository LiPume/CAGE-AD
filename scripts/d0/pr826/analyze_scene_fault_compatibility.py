#!/usr/bin/env python3
"""Audit whether a captured Prediction delta overlaps Planning's selected maneuver.

This is a read-only post-screening analyzer.  It does not define a failure oracle and it
does not alter either experiment arm.  The lateral-displacement threshold is only a robust
signature for the already observed active output mode: fixed trajectories stay below 0.8 m
while the activated alternate trajectory shifts by about 3.5 m.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def trajectory_lateral_delta(prediction: dict) -> float | None:
    trajectories = prediction.get("target", {}).get("trajectories", [])
    if not trajectories:
        return None
    trajectory = trajectories[0]
    return float(trajectory["last_point"]["x"] - trajectory["first_point"]["x"])


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def summarize_prediction(events: list[dict], threshold_m: float) -> dict:
    predictions = [event for event in events if event.get("event") == "prediction"]
    with_trajectory = [event for event in predictions if trajectory_lateral_delta(event) is not None]
    altered = [
        event
        for event in with_trajectory
        if abs(trajectory_lateral_delta(event) or 0.0) >= threshold_m
    ]
    deltas = [abs(trajectory_lateral_delta(event) or 0.0) for event in with_trajectory]
    return {
        "prediction_frames": len(predictions),
        "trajectory_frames": len(with_trajectory),
        "altered_signature_frames": len(altered),
        "maximum_abs_terminal_lateral_delta_m": max(deltas) if deltas else None,
        "altered_sequence_numbers": [event["header"]["sequence_num"] for event in altered],
        "altered_clock_range_s": (
            None if not altered else [min(event["clock_s"] for event in altered), max(event["clock_s"] for event in altered)]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed-timeline", type=Path, required=True)
    parser.add_argument("--active-timeline", type=Path, required=True)
    parser.add_argument("--active-summary", type=Path, required=True)
    parser.add_argument("--lateral-signature-threshold-m", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixed_events = read_jsonl(args.fixed_timeline)
    active_events = read_jsonl(args.active_timeline)
    active_summary = json.loads(args.active_summary.read_text())
    threshold = args.lateral_signature_threshold_m
    fixed_prediction = summarize_prediction(fixed_events, threshold)
    active_prediction = summarize_prediction(active_events, threshold)
    changed_sequences = set(active_prediction["altered_sequence_numbers"])
    observation = next(event for event in active_events if event.get("event") == "observation_start")
    observation_clock = float(observation["simulation_elapsed_seconds"])
    active_predictions = {
        event["header"]["sequence_num"]: event
        for event in active_events
        if event.get("event") == "prediction"
    }
    consumed = [
        event
        for event in active_events
        if event.get("event") == "planning_raw"
        and event.get("embedded_inputs", {}).get("prediction_header", {}).get("sequence_num")
        in changed_sequences
    ]
    consumed_sequences = {
        event["embedded_inputs"]["prediction_header"]["sequence_num"] for event in consumed
    }
    consumed_clock = [float(event["clock_s"]) for event in consumed]
    planning_paths = Counter(
        tuple(path["name"] for path in event.get("paths", [])) for event in consumed
    )
    decisions = Counter(
        tuple(event.get("trajectory", {}).get("main_decision_fields", [])) for event in consumed
    )
    changed_prediction_clock = [
        float(active_predictions[sequence]["clock_s"])
        for sequence in changed_sequences
        if sequence in active_predictions
    ]
    changed_elapsed_range = (
        None
        if not changed_prediction_clock
        else [
            min(changed_prediction_clock) - observation_clock,
            max(changed_prediction_clock) - observation_clock,
        ]
    )
    samples = active_summary["samples"]
    interval_samples = (
        []
        if changed_elapsed_range is None
        else [
            sample
            for sample in samples
            if changed_elapsed_range[0] <= float(sample["elapsed_s"]) <= changed_elapsed_range[1]
        ]
    )
    lane_entry = next(
        (float(sample["elapsed_s"]) for sample in samples if sample.get("carla_lane_id") == -1),
        None,
    )
    planning_frames = [event for event in active_events if event.get("event") == "planning_raw"]
    first_lane_change_path = next(
        (
            float(event["clock_s"]) - observation_clock
            for event in planning_frames
            if any("lane_change" in path["name"] for path in event.get("paths", []))
        ),
        None,
    )
    altered_end = None if changed_elapsed_range is None else changed_elapsed_range[1]
    result = {
        "schema_version": 1,
        "analysis_type": "READ_ONLY_SCENE_FAULT_COMPATIBILITY",
        "inputs": {
            "fixed_timeline": str(args.fixed_timeline),
            "fixed_timeline_sha256": sha256(args.fixed_timeline),
            "active_timeline": str(args.active_timeline),
            "active_timeline_sha256": sha256(args.active_timeline),
            "active_summary": str(args.active_summary),
            "active_summary_sha256": sha256(args.active_summary),
        },
        "altered_output_signature": {
            "definition": "abs(first published target trajectory terminal_x - initial_x) >= threshold",
            "threshold_m": threshold,
            "admission_or_failure_gate": False,
            "fixed": fixed_prediction,
            "active": active_prediction,
        },
        "planning_consumption": {
            "altered_prediction_frames": len(changed_sequences),
            "altered_sequences_consumed": len(consumed_sequences),
            "planning_frames_consuming_altered_output": len(consumed),
            "consumed_clock_range_s": None if not consumed_clock else [min(consumed_clock), max(consumed_clock)],
            "initial_speed_range_mps": (
                None
                if not consumed
                else [
                    min(float(event["init_point"]["v"]) for event in consumed),
                    max(float(event["init_point"]["v"]) for event in consumed),
                ]
            ),
            "planning_trajectory_length_range_m": (
                None
                if not consumed
                else [
                    min(float(event["trajectory"]["total_path_length"]) for event in consumed),
                    max(float(event["trajectory"]["total_path_length"]) for event in consumed),
                ]
            ),
            "main_decision_counts": {"|".join(key): value for key, value in decisions.items()},
            "path_name_set_counts": {"|".join(key): value for key, value in planning_paths.items()},
            "frames_with_target_obstacle_debug": sum(bool(event.get("target_obstacle_debug")) for event in consumed),
        },
        "vehicle_overlap_window": {
            "altered_output_elapsed_range_s": changed_elapsed_range,
            "sample_count": len(interval_samples),
            "ego_speed_range_mps": (
                None
                if not interval_samples
                else [
                    min(float(sample["ego_speed_mps"]) for sample in interval_samples),
                    max(float(sample["ego_speed_mps"]) for sample in interval_samples),
                ]
            ),
            "ego_lane_ids": sorted({sample["carla_lane_id"] for sample in interval_samples}),
            "ego_lateral_excursion_range_m": (
                None
                if not interval_samples
                else [
                    min(float(sample["ego_lateral_m"]) for sample in interval_samples),
                    max(float(sample["ego_lateral_m"]) for sample in interval_samples),
                ]
            ),
            "first_lane_minus_1_entry_elapsed_s": lane_entry,
            "first_lane_change_path_elapsed_s": first_lane_change_path,
            "last_altered_output_to_lane_change_path_gap_s": (
                None
                if first_lane_change_path is None or altered_end is None
                else first_lane_change_path - altered_end
            ),
            "last_altered_output_to_lane_entry_gap_s": (
                None if lane_entry is None or altered_end is None else lane_entry - altered_end
            ),
        },
        "classification": "TEMPORAL_AND_SELECTED_PATH_MISMATCH",
        "interpretation": (
            "The frozen Prediction fault changed published output and Planning consumed it, but "
            "the delta ended while ego was still in lane -2 and Planning exposed only regular/self "
            "paths. Planning first exposed a lane-change path only after the delta ended and the "
            "physical lane -1 entry occurred much later, so this scene cannot test whether the "
            "erroneous lane-change trajectory blocks that maneuver."
        ),
        "next_scene_design_constraint": (
            "Without changing fault semantics, make the fixed straight target and erroneous "
            "lane-change target trajectories differ while Planning is already selecting the "
            "adjacent-lane maneuver; freeze and admit the normal-only arm before any active run."
        ),
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
