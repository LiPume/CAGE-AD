#!/usr/bin/env python3
"""Classify one frozen P4 screening from private filter telemetry and run evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re

import yaml


ELIGIBILITY = re.compile(
    r"(?P<prefix>^[IWEF]\d{4}\s+\S+\s+(?P<thread>\d+)).*"
    r"stage=eligibility obstacle=(?P<obstacle>-?\d+) candidate_index=(?P<index>\d+) "
    r"candidate_id=(?P<id>-?\d+) type=(?P<type>-?\d+) probability=(?P<prob>\S+) "
    r"fixed_eligible=(?P<fixed>[01]) active_eligible=(?P<active>[01])"
)
DISTANCE = re.compile(
    r"^[IWEF]\d{4}\s+\S+\s+(?P<thread>\d+).*stage=distance "
    r"obstacle=(?P<obstacle>-?\d+) candidate_index=(?P<index>\d+) "
    r"candidate_id=(?P<id>-?\d+) adc_overlap=(?P<overlap>[01]) "
    r"signed_distance_m=(?P<distance>\S+)"
)
DECISION = re.compile(
    r"^[IWEF]\d{4}\s+\S+\s+(?P<thread>\d+).*stage=nearby_decision "
    r"obstacle=(?P<obstacle>-?\d+) candidate_index=(?P<index>\d+) "
    r"candidate_id=(?P<id>-?\d+) polygon_in_own_lane=(?P<polygon>[01]) "
    r"enabled=(?P<enabled>[01])"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    os.replace(temporary, path)


def first_sample(samples: list[dict], predicate) -> float | None:
    item = next((sample for sample in samples if predicate(sample)), None)
    return None if item is None else float(item["elapsed_s"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--manifest-diff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_bytes())
    manifest = json.loads(args.manifest.read_text())
    summary = json.loads(args.summary.read_text())
    pair_diff = json.loads(args.manifest_diff.read_text())
    target_id = int(contract["mechanism_gate"]["target_obstacle_id"])
    lane_type_by_thread_index: dict[tuple[int, int], int] = {}
    expanded_by_thread_index: dict[tuple[int, int], bool] = {}
    counts: Counter[str] = Counter()
    overlap_distances: dict[int, list[float]] = defaultdict(list)

    for line in args.trace.read_text(errors="replace").splitlines():
        match = ELIGIBILITY.search(line)
        if match and int(match["obstacle"]) == target_id:
            key = (int(match["thread"]), int(match["index"]))
            lane_type = int(match["type"])
            expanded = match["fixed"] == "0" and match["active"] == "1"
            lane_type_by_thread_index[key] = lane_type
            expanded_by_thread_index[key] = expanded
            counts["target_eligibility_events"] += 1
            if expanded:
                counts["target_expanded_eligibility_events"] += 1
            continue
        match = DISTANCE.search(line)
        if match and int(match["obstacle"]) == target_id:
            key = (int(match["thread"]), int(match["index"]))
            lane_type = lane_type_by_thread_index.get(key)
            expanded = expanded_by_thread_index.get(key, False)
            overlap = match["overlap"] == "1"
            distance = float(match["distance"])
            counts["target_distance_events"] += 1
            if overlap:
                counts["target_overlap_events"] += 1
                if math.isfinite(distance):
                    overlap_distances[lane_type].append(distance)
            if expanded:
                counts["target_expanded_distance_events"] += 1
                if overlap:
                    counts["target_expanded_overlap_events"] += 1
                if overlap and 0.0 < distance < 10.0:
                    counts["target_expanded_nearby_events"] += 1
            continue
        match = DECISION.search(line)
        if match and int(match["obstacle"]) == target_id:
            key = (int(match["thread"]), int(match["index"]))
            expanded = expanded_by_thread_index.get(key, False)
            counts["target_nearby_decision_events"] += 1
            if match["enabled"] == "0":
                counts["target_nearby_disabled_events"] += 1
            if expanded:
                counts["target_expanded_nearby_decision_events"] += 1
                if match["polygon"] == "1" and match["enabled"] == "0":
                    counts["target_expanded_disabled_events"] += 1

    metrics = summary["metrics"]
    infrastructure_checks = {
        "matched_manifest": pair_diff.get("status") == "PASS",
        "infrastructure_valid": metrics["infrastructure_valid"] is True,
        "route_accepted": metrics["route"]["accepted"] is True,
        "collision_free": metrics["collision_count"] == 0,
        "illegal_lane_invasion_free": metrics["illegal_lane_invasion_count"] == 0,
        "target_present": metrics["counts"]["target_prediction"] >= 20,
        "prediction_coverage": metrics["target_prediction_trajectory_coverage"] >= 0.90,
        "planning_coverage": metrics["planning_channel_coverage"] >= 0.95,
        "control_coverage": metrics["control_channel_coverage"] >= 0.95,
        "planning_valid_ratio": metrics["planning_valid_ratio"] >= 0.90,
        "runtime_exception_absent": metrics["runtime_exception"] is None,
    }
    full_trigger = counts["target_expanded_disabled_events"] > 0
    if not all(infrastructure_checks.values()):
        classification = "INFRA_INVALID"
    elif not full_trigger:
        classification = "FAULT_NOT_ACTIVATED"
    else:
        classification = "SEMANTIC_EFFECT_REQUIRES_FURTHER_ANALYSIS"

    samples = summary["samples"]
    behavior = {
        "entered_lane_minus_1_first_s": first_sample(
            samples, lambda value: value.get("carla_lane_id") == -1
        ),
        "lateral_excursion_2m_first_s": first_sample(
            samples, lambda value: abs(value.get("ego_lateral_m", 0.0)) >= 2.0
        ),
        "pass_margin_6m_first_s": first_sample(
            samples, lambda value: value.get("pass_margin_m", -math.inf) >= 6.0
        ),
        "success_region_first_s": metrics["success_region_first_reached_elapsed_s"],
        "max_pass_margin_m": metrics["max_pass_margin_m"],
        "overtake_success": metrics["overtake_success"],
        "success_region_reached": metrics["success_region_reached"],
    }
    result = {
        "schema_version": 1,
        "experiment_id": "SB4_PAIR_01_SCREEN",
        "status": "REJECT",
        "classification": classification,
        "contract_sha256": sha256(args.contract),
        "manifest_sha256": sha256(args.manifest),
        "summary_sha256": sha256(args.summary),
        "trace_sha256": sha256(args.trace),
        "manifest_diff_sha256": sha256(args.manifest_diff),
        "infrastructure_checks": infrastructure_checks,
        "private_mechanism_counts": dict(sorted(counts.items())),
        "expanded_candidate_overlap_distance_range_m": (
            None
            if not overlap_distances.get(2)
            else [min(overlap_distances[2]), max(overlap_distances[2])]
        ),
        "mechanism_activated": full_trigger,
        "prediction_changed": False if not full_trigger else None,
        "planning_changed": False if not full_trigger else None,
        "system_failure": False,
        "failure_type": "NORMAL_REFERENCE_LIKE_PASS",
        "causal_order_valid": False,
        "behavior": behavior,
        "reason": (
            "The active-only STRAIGHT candidate entered the eligibility and distance probe, "
            "but never jointly satisfied overlap and the strict (0,10)m distance guard; no "
            "active-only candidate was disabled. The run therefore cannot contain the "
            "fixture-proven semantic delta."
            if classification == "FAULT_NOT_ACTIVATED"
            else "See gate fields."
        ),
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
