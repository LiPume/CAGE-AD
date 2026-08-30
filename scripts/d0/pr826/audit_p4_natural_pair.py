#!/usr/bin/env python3
"""Audit one matched native PR826-family pair as explicit L0-L4 evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re

import yaml


ELIGIBILITY = re.compile(
    r"stage=eligibility obstacle=(?P<obstacle>-?\d+) candidate_index=(?P<index>\d+) "
    r"candidate_id=(?P<id>-?\d+) type=(?P<type>-?\d+) probability=(?P<prob>\S+) "
    r"fixed_eligible=(?P<fixed>[01]) active_eligible=(?P<active>[01]) domain=(?P<domain>[01])"
)
DISTANCE = re.compile(
    r"stage=distance obstacle=(?P<obstacle>-?\d+) candidate_index=(?P<index>\d+) "
    r"candidate_id=(?P<id>-?\d+) adc_overlap=(?P<overlap>[01]) "
    r"signed_distance_m=(?P<distance>\S+)"
)
DECISION = re.compile(
    r"stage=nearby_decision obstacle=(?P<obstacle>-?\d+) candidate_index=(?P<index>\d+) "
    r"candidate_id=(?P<id>-?\d+) polygon_in_own_lane=(?P<polygon>[01]) "
    r"enabled=(?P<enabled>[01])"
)
THREAD = re.compile(r"^[IWEF]\d{4}\s+\S+\s+(?P<thread>\d+)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def parse_trace(path: Path, target_id: int) -> dict:
    counts: Counter[str] = Counter()
    expanded: dict[tuple[int, int], bool] = {}
    guard: dict[tuple[int, int], tuple[bool, float]] = {}
    for line in path.read_text(errors="replace").splitlines():
        thread_match = THREAD.search(line)
        thread = -1 if thread_match is None else int(thread_match["thread"])
        match = ELIGIBILITY.search(line)
        if match and int(match["obstacle"]) == target_id:
            key = (thread, int(match["index"]))
            is_expanded = match["fixed"] == "0" and match["active"] == "1"
            expanded[key] = is_expanded
            counts["eligibility_events"] += 1
            counts[f"domain_{match['domain']}_events"] += 1
            if is_expanded:
                counts["expanded_eligibility_events"] += 1
            continue
        match = DISTANCE.search(line)
        if match and int(match["obstacle"]) == target_id:
            key = (thread, int(match["index"]))
            overlap = match["overlap"] == "1"
            distance = float(match["distance"])
            guard[key] = (overlap, distance)
            if expanded.get(key, False) and overlap and math.isfinite(distance):
                counts["expanded_overlap_events"] += 1
                if 0.0 < distance < 10.0:
                    counts["expanded_nearby_events"] += 1
            continue
        match = DECISION.search(line)
        if match and int(match["obstacle"]) == target_id:
            key = (thread, int(match["index"]))
            overlap, distance = guard.get(key, (False, math.inf))
            if (
                expanded.get(key, False)
                and overlap
                and 0.0 < distance < 10.0
                and match["polygon"] == "1"
                and match["enabled"] == "0"
            ):
                counts["expanded_disabled_events"] += 1
    return dict(sorted(counts.items()))


def prediction_signature(events: list[dict], threshold_m: float) -> dict:
    frames = []
    for event in events:
        if event.get("event") != "prediction":
            continue
        target = event.get("target") or {}
        trajectories = target.get("trajectories") or []
        if not trajectories:
            continue
        trajectory = trajectories[0]
        first, last = trajectory.get("first_point"), trajectory.get("last_point")
        if not first or not last:
            continue
        delta = abs(float(last["x"]) - float(first["x"]))
        if delta >= threshold_m:
            frames.append(
                {
                    "sequence_num": event["header"]["sequence_num"],
                    "clock_s": event.get("clock_s"),
                    "delta_m": delta,
                }
            )
    return {
        "frames": len(frames),
        "sequence_numbers": [row["sequence_num"] for row in frames],
        "clock_range_s": None
        if not frames
        else [min(row["clock_s"] for row in frames), max(row["clock_s"] for row in frames)],
        "delta_range_m": None
        if not frames
        else [min(row["delta_m"] for row in frames), max(row["delta_m"] for row in frames)],
    }


def run_validity(run_dir: Path, contract: dict, expected_overtake: bool) -> dict:
    summary = json.loads((run_dir / "summary.json").read_text())
    metrics = summary["metrics"]
    runtime = {"runtime_exception_absent": metrics["runtime_exception"] is None}
    transport = {
        "route_accepted": metrics["route"]["accepted"] is True,
        "prediction_coverage": metrics["target_prediction_trajectory_coverage"]
        >= contract["transport_gates"]["prediction_trajectory_coverage_min"],
        "planning_coverage": metrics["planning_channel_coverage"]
        >= contract["transport_gates"]["planning_channel_coverage_min"],
        "control_coverage": metrics["control_channel_coverage"]
        >= contract["transport_gates"]["control_channel_coverage_min"],
    }
    behavior = {
        "expected_overtake": metrics["overtake_success"] is expected_overtake,
        "collision_free": metrics["collision_count"] == 0,
        "illegal_lane_invasion_free": metrics["illegal_lane_invasion_count"] == 0,
    }
    if not expected_overtake:
        behavior["pass_margin_below_gate"] = (
            metrics["max_pass_margin_m"] < contract["failure_oracle"]["maximum_pass_margin_m"]
        )
        behavior["success_region_not_reached"] = metrics["success_region_reached"] is False
    return {
        "runtime_valid": all(runtime.values()),
        "transport_valid": all(runtime.values()) and all(transport.values()),
        "behavior_valid": all(behavior.values()),
        "runtime_checks": runtime,
        "transport_checks": transport,
        "behavior_checks": behavior,
        "outcome": {
            "overtake_success": metrics["overtake_success"],
            "success_region_reached": metrics["success_region_reached"],
            "max_pass_margin_m": metrics["max_pass_margin_m"],
            "planning_valid_ratio": metrics["planning_valid_ratio"],
            "prediction_trajectory_coverage": metrics[
                "target_prediction_trajectory_coverage"
            ],
        },
    }


def planning_state(row: dict) -> tuple[bool, bool, tuple[str, ...], float]:
    trajectory = row.get("trajectory") or {}
    return (
        int(trajectory.get("point_count", 0) or 0) > 0,
        any("lane_change" in path.get("name", "") for path in row.get("paths", [])),
        tuple(trajectory.get("main_decision_fields") or []),
        float(trajectory.get("total_path_length", 0.0) or 0.0),
    )


def planning_evidence(
    fixed_events: list[dict],
    active_events: list[dict],
    changed_sequences: set[int],
    horizon_delta_m: float,
) -> dict:
    fixed_observation = next(
        row for row in fixed_events if row.get("event") == "observation_start"
    )
    active_observation = next(
        row for row in active_events if row.get("event") == "observation_start"
    )
    fixed_origin = float(fixed_observation["simulation_elapsed_seconds"])
    active_origin = float(active_observation["simulation_elapsed_seconds"])
    fixed_states = {
        round((float(row["clock_s"]) - fixed_origin) / 0.05) * 0.05: planning_state(row)
        for row in fixed_events
        if row.get("event") == "planning_raw" and row.get("clock_s") is not None
    }
    consumed = [
        row
        for row in active_events
        if row.get("event") == "planning_raw"
        and (row.get("embedded_inputs") or {}).get("prediction_header", {}).get("sequence_num")
        in changed_sequences
    ]
    elapsed = [float(row["clock_s"]) - active_origin for row in consumed]
    response_deltas = []
    for row, active_elapsed in zip(consumed, elapsed):
        bucket = round(active_elapsed / 0.05) * 0.05
        fixed_state = fixed_states.get(bucket)
        if fixed_state is None:
            continue
        active_state = planning_state(row)
        categorical_delta = active_state[:3] != fixed_state[:3]
        horizon_delta = abs(active_state[3] - fixed_state[3]) >= horizon_delta_m
        if categorical_delta or horizon_delta:
            response_deltas.append(active_elapsed)
    return {
        "changed_sequences_consumed": len(
            {
                row["embedded_inputs"]["prediction_header"]["sequence_num"] for row in consumed
            }
        ),
        "planning_frames": len(consumed),
        "elapsed_range_s": None if not elapsed else [min(elapsed), max(elapsed)],
        "lane_change_path_frames": sum(
            any("lane_change" in path.get("name", "") for path in row.get("paths", []))
            for row in consumed
        ),
        "target_debug_frames": sum(bool(row.get("target_obstacle_debug")) for row in consumed),
        "response_delta_frames": len(response_deltas),
        "response_delta_elapsed_range_s": None
        if not response_deltas
        else [min(response_deltas), max(response_deltas)],
        "response_delta_definition": (
            "valid/lane-change/main-decision categorical delta or frozen planned-horizon delta"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--manifest-diff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text())
    target_id = int(contract["mechanism_gates"]["target_obstacle_id"])
    threshold = float(contract["native_output_gate"]["terminal_lateral_signature_m"])
    manifest_diff = json.loads(args.manifest_diff.read_text())
    fixed_timeline = read_jsonl(args.fixed / "planning_input_timeline.jsonl")
    active_timeline = read_jsonl(args.active / "planning_input_timeline.jsonl")
    fixed_trace = parse_trace(args.fixed / "stack.log", target_id)
    active_trace = parse_trace(args.active / "stack.log", target_id)
    fixed_signature = prediction_signature(fixed_timeline, threshold)
    active_signature = prediction_signature(active_timeline, threshold)
    changed = set(active_signature["sequence_numbers"])
    planning = planning_evidence(
        fixed_timeline,
        active_timeline,
        changed,
        float(contract["planning_gate"]["planned_horizon_delta_m"]),
    )
    fixed_validity = run_validity(args.fixed, contract, True)
    active_validity = run_validity(args.active, contract, False)

    levels = {
        "L0_fault_activation": active_trace.get("domain_1_events", 0) > 0
        and active_trace.get("expanded_eligibility_events", 0) > 0,
        "L1_candidate_semantic_delta": active_trace.get("expanded_disabled_events", 0)
        >= contract["mechanism_gates"]["minimum_expanded_disabled_events"],
        "L2_native_prediction_phenotype": active_signature["frames"]
        >= fixed_signature["frames"] + contract["native_output_gate"]["minimum_excess_frames"],
        "L3_planning_consumption": planning["changed_sequences_consumed"]
        >= contract["planning_gate"]["minimum_changed_sequences_consumed"],
        "L3_planning_response": planning["response_delta_frames"]
        >= contract["planning_gate"]["minimum_response_delta_frames"],
        "L4_vehicle_failure": active_validity["behavior_valid"]
        and fixed_validity["behavior_valid"],
    }
    base_valid = (
        manifest_diff.get("status") == "PASS"
        and fixed_validity["runtime_valid"]
        and fixed_validity["transport_valid"]
        and active_validity["runtime_valid"]
        and active_validity["transport_valid"]
    )
    if not base_valid:
        classification = "INFRA_INVALID"
    elif not levels["L0_fault_activation"]:
        classification = "FAULT_NOT_ACTIVATED"
    elif not levels["L1_candidate_semantic_delta"]:
        classification = "CANDIDATE_SEMANTIC_DELTA_ABSENT"
    elif not levels["L2_native_prediction_phenotype"]:
        classification = "NATIVE_PREDICTION_PHENOTYPE_ABSENT"
    elif not levels["L3_planning_consumption"]:
        classification = "SEMANTIC_EFFECT_NOT_PROPAGATED"
    elif not levels["L3_planning_response"]:
        classification = "PLANNING_INSENSITIVE_TO_FAULT"
    elif not levels["L4_vehicle_failure"]:
        classification = "SCENE_FAULT_PAIR_NOT_ADMITTED"
    else:
        classification = "NATURAL_PORT_SCREEN_PASS_CONFIRMATION_REQUIRED"
    causal = base_valid and all(levels.values())
    result = {
        "schema_version": 1,
        "analysis_type": "P4_NATURAL_PR826_PORT_L0_L4_SCREEN",
        "contract_sha256": sha256(args.contract),
        "classification": classification,
        "status": "PASS" if causal else "REJECT",
        "admission_evidence": False,
        "matched_manifest": manifest_diff,
        "validity": {"fixed": fixed_validity, "active": active_validity},
        "levels": levels,
        "private_mechanism": {"fixed": fixed_trace, "active": active_trace},
        "native_output": {"fixed": fixed_signature, "active": active_signature},
        "planning": planning,
        "causal_order_valid": causal,
        "non_claim": "One screening PASS requires frozen formal repeats before admission.",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
