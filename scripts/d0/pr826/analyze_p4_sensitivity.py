#!/usr/bin/env python3
"""Audit the non-admission S0/S1/S2 Prediction-to-Planning sensitivity probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

import yaml


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def first_sample(summary: dict, predicate):
    return next(
        (float(sample["elapsed_s"]) for sample in summary["samples"] if predicate(sample)),
        None,
    )


def planning_states(timeline: list[dict], observation_clock: float) -> dict[float, dict]:
    result = {}
    for event in timeline:
        if event.get("event") != "planning_raw" or event.get("clock_s") is None:
            continue
        elapsed = float(event["clock_s"]) - observation_clock
        bucket = round(elapsed / 0.05) * 0.05
        trajectory = event.get("trajectory") or {}
        paths = event.get("paths") or []
        prediction = ((event.get("latest_channel_inputs") or {}).get("prediction") or {})
        result[bucket] = {
            "elapsed_s": elapsed,
            "prediction_sha256": prediction.get("sha256"),
            "valid": int(trajectory.get("point_count", 0) or 0) > 0,
            "lane_change_path": any(
                "lane_change" in path.get("name", "") for path in paths
            ),
            "path_names": [path.get("name") for path in paths],
            "planned_horizon_m": float(trajectory.get("total_path_length", 0.0) or 0.0),
            "decision_fields": list(trajectory.get("main_decision_fields") or []),
        }
    return result


def longest_contiguous(times: list[float]) -> dict:
    clusters = []
    for value in sorted(set(times)):
        if not clusters or value - clusters[-1][1] > 0.051:
            clusters.append([value, value, 1])
        else:
            clusters[-1][1] = value
            clusters[-1][2] += 1
    if not clusters:
        return {"start_s": None, "end_s": None, "duration_s": 0.0, "bins": 0}
    start, end, count = max(clusters, key=lambda row: (row[1] - row[0], row[2]))
    return {
        "start_s": start,
        "end_s": end,
        "duration_s": end - start,
        "bins": count,
    }


def read_run(path: Path, contract: dict) -> dict:
    manifest_path = path / "manifest.json"
    summary_path = path / "summary.json"
    stats_path = path / "private_p4_sensitivity_stats.json"
    telemetry_path = path / "private_p4_sensitivity_telemetry.jsonl"
    timeline_path = path / "planning_input_timeline.jsonl"
    manifest = json.loads(manifest_path.read_text())
    summary = json.loads(summary_path.read_text())
    stats = json.loads(stats_path.read_text())
    telemetry = [
        json.loads(line) for line in telemetry_path.read_text().splitlines() if line.strip()
    ]
    timeline = [
        json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()
    ]
    observation_clock = float(
        next(
            event["simulation_elapsed_seconds"]
            for event in timeline
            if event.get("event") == "observation_start"
        )
    )
    states = planning_states(timeline, observation_clock)
    active_output_hashes = {row["output_sha256"] for row in telemetry}
    consumed = [
        state for state in states.values()
        if state["prediction_sha256"] in active_output_hashes
    ]
    metrics = summary["metrics"]
    gates = contract.get("probe_gates") or contract["transport_gates"]
    semantic_gates = contract.get("semantic_gates") or gates
    transport_checks = {
        "route_accepted": metrics["route"]["accepted"] is True,
        "runtime_exception_absent": metrics["runtime_exception"] is None,
        "interposer_exception_absent": stats["exception"] is None,
        "raw_prediction_messages": stats["raw_messages"]
        >= gates["target_raw_prediction_messages_min"],
        "interposer_output_coverage": stats["output_messages"]
        / max(1, stats["raw_messages"])
        >= gates["interposer_output_coverage_min"],
        "planning_channel_coverage": metrics["planning_channel_coverage"]
        >= gates["planning_channel_coverage_min"],
        "control_channel_coverage": metrics["control_channel_coverage"]
        >= gates["control_channel_coverage_min"],
        "collision_free": metrics["collision_count"] == 0,
        "illegal_lane_invasion_free": metrics["illegal_lane_invasion_count"] == 0,
    }
    semantic = stats["semantic"]
    semantic_checks = {
        "active_target_present": stats["active_target_messages"] > 0,
        "preservation": stats["preservation_mismatches"] == 0,
    }
    if semantic == "S0_STRAIGHT":
        semantic_checks["identity"] = (
            stats["identity_mismatches"]
            <= semantic_gates["s0_identity_mismatch_max"]
        )
    elif semantic == "S1_LEFT_MERGE_OCCUPANCY":
        semantic_checks.update(
            {
                "transformed": stats["transformed_messages"] > 0,
                "endpoint_min": stats["endpoint_delta_m_min"]
                >= semantic_gates["s1_minimum_lateral_endpoint_delta_m"],
                "endpoint_max": stats["endpoint_delta_m_max"]
                <= semantic_gates["s1_maximum_lateral_endpoint_delta_m"],
            }
        )
    elif semantic == "S2_NO_TRAJECTORY":
        semantic_checks["transformed"] = stats["transformed_messages"] > 0
    return {
        "run_id": manifest["screening_id"],
        "semantic": semantic,
        "files": {
            "manifest_sha256": sha256(manifest_path),
            "summary_sha256": sha256(summary_path),
            "stats_sha256": sha256(stats_path),
            "telemetry_sha256": sha256(telemetry_path),
            "timeline_sha256": sha256(timeline_path),
        },
        "transport_checks": transport_checks,
        "semantic_checks": semantic_checks,
        "summary_infrastructure_valid": metrics["infrastructure_valid"],
        "planning_valid_ratio": metrics["planning_valid_ratio"],
        "prediction_trajectory_coverage": metrics[
            "target_prediction_trajectory_coverage"
        ],
        "overtake_success": metrics["overtake_success"],
        "success_region_reached": metrics["success_region_reached"],
        "max_pass_margin_m": metrics["max_pass_margin_m"],
        "lane_minus_1_entry_s": first_sample(
            summary, lambda sample: int(sample["carla_lane_id"]) == -1
        ),
        "pass_margin_6m_s": first_sample(
            summary, lambda sample: float(sample["pass_margin_m"]) >= 6.0
        ),
        "first_active_prediction_consumed_s": (
            None if not consumed else min(row["elapsed_s"] for row in consumed)
        ),
        "states": states,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--s0", type=Path, required=True)
    parser.add_argument("--s1", type=Path, required=True)
    parser.add_argument("--s2", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_bytes())
    runs = {
        "S0": read_run(args.s0, contract),
        "S1": read_run(args.s1, contract),
    }
    if args.s2 is not None:
        runs["S2"] = read_run(args.s2, contract)
    s0, s1 = runs["S0"], runs["S1"]
    common = sorted(
        time for time in set(s0["states"]) & set(s1["states"])
        if 12.0 <= time <= 40.0
    )
    path_delta = longest_contiguous(
        [
            time for time in common
            if s0["states"][time]["lane_change_path"]
            and not s1["states"][time]["lane_change_path"]
        ]
    )
    validity_delta = longest_contiguous(
        [
            time for time in common
            if s0["states"][time]["valid"] and not s1["states"][time]["valid"]
        ]
    )
    first_state_delta = next(
        (
            {
                "elapsed_s": time,
                "s0": s0["states"][time],
                "s1": s1["states"][time],
            }
            for time in common
            if (
                s0["states"][time]["valid"],
                s0["states"][time]["lane_change_path"],
            )
            != (
                s1["states"][time]["valid"],
                s1["states"][time]["lane_change_path"],
            )
        ),
        None,
    )
    windows = []
    for start in (12.0, 17.0, 22.0, 27.0, 32.0, 37.0):
        times = [time for time in common if start <= time < start + 5.0]
        if not times:
            continue
        s0_values = [s0["states"][time]["planned_horizon_m"] for time in times]
        s1_values = [s1["states"][time]["planned_horizon_m"] for time in times]
        windows.append(
            {
                "start_s": start,
                "end_s": start + 5.0,
                "s0_median_planned_horizon_m": statistics.median(s0_values),
                "s1_median_planned_horizon_m": statistics.median(s1_values),
                "s0_minus_s1_m": statistics.median(s0_values)
                - statistics.median(s1_values),
            }
        )
    lane_delay = (
        None
        if s0["lane_minus_1_entry_s"] is None or s1["lane_minus_1_entry_s"] is None
        else s1["lane_minus_1_entry_s"] - s0["lane_minus_1_entry_s"]
    )
    delta_checks = {
        "continuous_path_state_change": path_delta["duration_s"]
        >= contract["planning_delta_any"]["continuous_path_state_change_min_s"],
        "lane_entry_delay": lane_delay is not None
        and lane_delay
        >= contract["planning_delta_any"]["ego_lane_minus_1_entry_delay_min_s"],
        "lane_entry_absent": s1["lane_minus_1_entry_s"] is None
        or s1["lane_minus_1_entry_s"]
        > contract["planning_delta_any"]["ego_lane_minus_1_absent_deadline_s"],
        "planned_progress_drop": max(
            (window["s0_minus_s1_m"] for window in windows), default=-math.inf
        )
        >= contract["planning_delta_any"]["five_second_planned_progress_drop_min_m"],
    }
    all_transport_valid = all(
        all(run["transport_checks"].values()) for run in runs.values()
    )
    all_semantics_valid = all(
        all(run["semantic_checks"].values()) for run in runs.values()
    )
    is_v1 = contract["contract_version"] == "p4-sens-boundary-v1"
    frozen_v1_infrastructure_gate = (
        all(run["summary_infrastructure_valid"] is True for run in runs.values())
        if is_v1 else None
    )
    signal_observed = any(delta_checks.values())
    if not all_transport_valid or not all_semantics_valid:
        status = "REJECT_PROBE_IMPLEMENTATION_OR_TRANSPORT"
    elif is_v1 and not frozen_v1_infrastructure_gate:
        status = "INCONCLUSIVE_V1_GATE_CONFLATES_PLANNING_RESPONSE_WITH_INFRASTRUCTURE"
    elif not signal_observed:
        status = "SCENE_PLANNING_INSENSITIVE"
    else:
        status = "SENSITIVITY_SCREEN_PASS_CONFIRMATION_REQUIRED"
    for run in runs.values():
        del run["states"]
    result = {
        "schema_version": 1,
        "analysis_type": "P4_SENSITIVITY_NON_ADMISSION",
        "contract_sha256": sha256(args.contract),
        "status": status,
        "admission_evidence": False,
        "runs": runs,
        "pair_delta": {
            "first_planning_state_delta": first_state_delta,
            "longest_s0_lane_change_s1_not_interval": path_delta,
            "longest_s0_valid_s1_invalid_interval": validity_delta,
            "lane_minus_1_entry_delay_s": lane_delay,
            "five_second_planned_horizon_windows": windows,
            "checks": delta_checks,
        },
        "sensitivity_signal_observed": signal_observed,
        "stable_sensitivity_established": False,
        "frozen_v1_infrastructure_gate_pass": frozen_v1_infrastructure_gate,
        "interpretation": (
            (
                "S1 produced a predeclared Planning delta, but the v1 contract imported the normal "
                "reference Planning-valid threshold into its infrastructure gate. Because the "
                "changed Prediction itself caused invalid/fallback Planning cycles, v1 cannot call "
                "this a PASS without circularly rejecting the response it was designed to measure. "
                "Preserve v1 as inconclusive and preregister a corrected non-admission "
                "transport-vs-response gate before any confirmation repeats."
            )
            if is_v1
            else (
                "The v2 non-admission audit treats Planning validity, optimizer failures and "
                "fallback as measured downstream responses while retaining route, channel, relay, "
                "runtime, collision and legality transport gates."
            )
        ),
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
