#!/usr/bin/env python3
"""Version-independent audit core for persistent Prediction semantic probes.

Contract adapters normalize frozen v4/v5 schemas. This module measures runs and
applies normalized gates without selecting thresholds from observed results.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LEGACY_MEASURE_PATH = Path(__file__).with_name("analyze_p4_sensitivity.py")
SPEC = importlib.util.spec_from_file_location("p4_sensitivity_legacy_measure", LEGACY_MEASURE_PATH)
LEGACY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(LEGACY)


@dataclass(frozen=True)
class NormalizedContract:
    version: str
    classification: str
    target_id: int
    active_start_s: float
    active_end_s: float
    fixed_delta_s: float
    transport_gates: dict[str, Any]
    semantic_gates: dict[str, Any]
    screen_gate: dict[str, Any]
    expected_pairs: tuple[tuple[str, str], ...]
    allowed_pair_manifest_deltas: frozenset[str]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapt_contract(contract: dict[str, Any]) -> NormalizedContract:
    version = contract.get("contract_version")
    allowed_versions = {
        "p4-sens-boundary-v4-persistent-screen",
        "p4-sens-boundary-v5-persistent-confirmation",
    }
    if version not in allowed_versions:
        raise ValueError(f"unsupported persistent sensitivity contract: {version}")
    if not str(contract.get("status", "")).startswith("FROZEN_BEFORE_FIRST_V"):
        raise ValueError("contract is not frozen")
    if contract.get("classification") != "NON_ADMISSION_CAUSAL_SENSITIVITY_PROBE":
        raise ValueError("unexpected classification")
    if contract.get("admission_evidence") is not False:
        raise ValueError("persistent sensitivity contract cannot be admission evidence")
    if version.endswith("v4-persistent-screen"):
        schedule = contract["run_schedule"]["initial_screen_ids"]
        expected_pairs = ((schedule["S0_STRAIGHT"], schedule["S1_LEFT_MERGE_OCCUPANCY"]),)
    else:
        expected_pairs = tuple(
            (str(pair[0]), str(pair[1]))
            for pair in contract["stable_confirmation"]["expected_pairs"]
        )
    return NormalizedContract(
        version=version,
        classification=contract["classification"],
        target_id=int(contract["target"]["obstacle_id"]),
        active_start_s=float(contract["target"]["active_elapsed_s"][0]),
        active_end_s=float(contract["target"]["active_elapsed_s"][1]),
        fixed_delta_s=0.05,
        transport_gates=dict(contract["transport_gates"]),
        semantic_gates=dict(contract["semantic_gates"]),
        screen_gate=dict(contract["screen_gate"]),
        expected_pairs=expected_pairs,
        allowed_pair_manifest_deltas=frozenset(
            {
                "created_at",
                "screening_id",
                "p4_sensitivity_probe.semantic",
                "p4_sensitivity_probe.lateral_offset_m",
                "p4_sensitivity_probe.relative_start_s",
                "p4_sensitivity_probe.relative_end_s",
            }
        ),
    )


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            result.update(flatten(child, path))
        return result
    return {prefix: value}


def pair_manifest_delta(s0_path: Path, s1_path: Path, allowed: frozenset[str]) -> dict:
    s0 = flatten(json.loads(s0_path.read_text()))
    s1 = flatten(json.loads(s1_path.read_text()))
    observed = frozenset(key for key in set(s0) | set(s1) if s0.get(key) != s1.get(key))
    return {
        "observed": sorted(observed),
        "allowed": sorted(allowed),
        "pass": observed == allowed,
    }


def normalized_repeat_manifest_sha256(path: Path) -> str:
    """Hash scientific run configuration while excluding repeat/contract bookkeeping."""
    value = json.loads(path.read_text())
    value.pop("created_at", None)
    value.pop("screening_id", None)
    probe = value["p4_sensitivity_probe"]
    probe.pop("contract_path", None)
    probe.pop("contract_sha256", None)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def telemetry_extent(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    elapsed = [float(row["elapsed_s"]) for row in rows]
    return {
        "rows": len(rows),
        "first_elapsed_s": min(elapsed) if elapsed else None,
        "last_elapsed_s": max(elapsed) if elapsed else None,
    }


def measure_run(run_dir: Path, normalized: NormalizedContract) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.json"
    stats_path = run_dir / "private_p4_sensitivity_stats.json"
    telemetry_path = run_dir / "private_p4_sensitivity_telemetry.jsonl"
    timeline_path = run_dir / "planning_input_timeline.jsonl"
    manifest = json.loads(manifest_path.read_text())
    summary = json.loads(summary_path.read_text())
    stats = json.loads(stats_path.read_text())
    metrics = summary["metrics"]
    extent = telemetry_extent(telemetry_path)
    legacy = LEGACY.read_run(
        run_dir,
        {
            "transport_gates": normalized.transport_gates,
            "semantic_gates": normalized.semantic_gates,
        },
    )
    states = legacy.pop("states")
    runtime_checks = {
        "runtime_exception_absent": metrics["runtime_exception"] is None,
        "interposer_exception_absent": stats["exception"] is None,
    }
    transport_checks = {
        "route_accepted": metrics["route"]["accepted"] is True,
        "raw_prediction_messages": stats["raw_messages"]
        >= normalized.transport_gates["target_raw_prediction_messages_min"],
        "interposer_output_coverage": stats["output_messages"] / max(1, stats["raw_messages"])
        >= normalized.transport_gates["interposer_output_coverage_min"],
        "planning_channel_coverage": metrics["planning_channel_coverage"]
        >= normalized.transport_gates["planning_channel_coverage_min"],
        "control_channel_coverage": metrics["control_channel_coverage"]
        >= normalized.transport_gates["control_channel_coverage_min"],
    }
    safety_checks = {
        "collision_free": metrics["collision_count"]
        <= normalized.transport_gates["collision_count_max"],
        "illegal_lane_invasion_free": metrics["illegal_lane_invasion_count"]
        <= normalized.transport_gates["illegal_lane_invasion_count_max"],
    }
    semantic = stats["semantic"]
    semantic_checks = {
        "active_target_present": stats["active_target_messages"] > 0,
        "field_preservation": stats["preservation_mismatches"] == 0,
        "persistent_window_start": extent["first_elapsed_s"] is not None
        and extent["first_elapsed_s"]
        <= normalized.active_start_s + normalized.fixed_delta_s + 1e-6,
        "persistent_window_end": extent["last_elapsed_s"] is not None
        and extent["last_elapsed_s"]
        >= normalized.active_end_s - normalized.fixed_delta_s - 1e-6,
        "planning_consumed_active_prediction": legacy["first_active_prediction_consumed_s"]
        is not None,
    }
    if semantic == "S0_STRAIGHT":
        semantic_checks["identity"] = stats["identity_mismatches"] <= normalized.semantic_gates[
            "s0_identity_mismatch_max"
        ]
    elif semantic == "S1_LEFT_MERGE_OCCUPANCY":
        semantic_checks.update(
            {
                "transformed": stats["transformed_messages"] > 0,
                "endpoint_min": stats["endpoint_delta_m_min"]
                >= normalized.semantic_gates["s1_minimum_lateral_endpoint_delta_m"],
                "endpoint_max": stats["endpoint_delta_m_max"]
                <= normalized.semantic_gates["s1_maximum_lateral_endpoint_delta_m"],
            }
        )
    else:
        semantic_checks["expected_semantic"] = False
    if semantic == "S0_STRAIGHT":
        behavior_checks = {
            "expected_overtake": metrics["overtake_success"]
            is normalized.screen_gate["s0_overtake_success_required"],
            **safety_checks,
        }
    else:
        behavior_checks = {
            "expected_overtake_cancellation": metrics["overtake_success"]
            is normalized.screen_gate["s1_overtake_success_required"],
            "pass_margin_within_gate": metrics["max_pass_margin_m"]
            < normalized.screen_gate["s1_maximum_pass_margin_m"],
            **safety_checks,
        }
    validity = {
        "runtime_valid": all(runtime_checks.values()),
        "transport_valid": all(runtime_checks.values()) and all(transport_checks.values()),
        "semantic_valid": all(semantic_checks.values()),
        "behavior_valid": all(behavior_checks.values()),
        "admission_valid": False,
    }
    return {
        "run_id": manifest["screening_id"],
        "semantic": semantic,
        "files": {
            "manifest_sha256": sha256(manifest_path),
            "normalized_repeat_manifest_sha256": normalized_repeat_manifest_sha256(manifest_path),
            "summary_sha256": sha256(summary_path),
            "stats_sha256": sha256(stats_path),
            "telemetry_sha256": sha256(telemetry_path),
            "timeline_sha256": sha256(timeline_path),
        },
        "validity": validity,
        "runtime_checks": runtime_checks,
        "transport_checks": transport_checks,
        "semantic_checks": semantic_checks,
        "behavior_checks": behavior_checks,
        "legacy_infrastructure_valid": metrics["infrastructure_valid"],
        "response_metrics": {
            "planning_valid_ratio": metrics["planning_valid_ratio"],
            "prediction_trajectory_coverage": metrics["target_prediction_trajectory_coverage"],
        },
        "outcome": {
            "overtake_success": metrics["overtake_success"],
            "success_region_reached": metrics["success_region_reached"],
            "max_pass_margin_m": metrics["max_pass_margin_m"],
            "lane_minus_1_entry_s": legacy["lane_minus_1_entry_s"],
            "pass_margin_6m_s": legacy["pass_margin_6m_s"],
        },
        "telemetry_extent": extent,
        "first_active_prediction_consumed_s": legacy["first_active_prediction_consumed_s"],
        "_states": states,
    }


def first_planning_delta(s0: dict[str, Any], s1: dict[str, Any], normalized: NormalizedContract):
    states0, states1 = s0["_states"], s1["_states"]
    common = sorted(
        time
        for time in set(states0) & set(states1)
        if normalized.active_start_s <= time <= normalized.active_end_s
    )
    return next(
        (
            {
                "elapsed_s": time,
                "s0_valid": states0[time]["valid"],
                "s1_valid": states1[time]["valid"],
                "s0_lane_change_path": states0[time]["lane_change_path"],
                "s1_lane_change_path": states1[time]["lane_change_path"],
                "s0_planned_horizon_m": states0[time]["planned_horizon_m"],
                "s1_planned_horizon_m": states1[time]["planned_horizon_m"],
            }
            for time in common
            if (
                states0[time]["valid"],
                states0[time]["lane_change_path"],
                round(states0[time]["planned_horizon_m"], 3),
            )
            != (
                states1[time]["valid"],
                states1[time]["lane_change_path"],
                round(states1[time]["planned_horizon_m"], 3),
            )
        ),
        None,
    )


def audit_pair(contract: dict[str, Any], contract_path: Path, s0_dir: Path, s1_dir: Path) -> dict:
    normalized = adapt_contract(contract)
    s0 = measure_run(s0_dir, normalized)
    s1 = measure_run(s1_dir, normalized)
    delta = first_planning_delta(s0, s1, normalized)
    manifest = pair_manifest_delta(
        s0_dir / "manifest.json", s1_dir / "manifest.json", normalized.allowed_pair_manifest_deltas
    )
    for run in (s0, s1):
        run.pop("_states")
    checks = {
        "manifest_allowed_delta": manifest["pass"],
        "s0_runtime_valid": s0["validity"]["runtime_valid"],
        "s0_transport_valid": s0["validity"]["transport_valid"],
        "s0_semantic_valid": s0["validity"]["semantic_valid"],
        "s0_behavior_valid": s0["validity"]["behavior_valid"],
        "s1_runtime_valid": s1["validity"]["runtime_valid"],
        "s1_transport_valid": s1["validity"]["transport_valid"],
        "s1_semantic_valid": s1["validity"]["semantic_valid"],
        "s1_behavior_valid": s1["validity"]["behavior_valid"],
        "planning_delta_observed": delta is not None,
    }
    passed = all(checks.values())
    return {
        "schema_version": 2,
        "analysis_type": "P4_SENS_PERSISTENT_PAIR_COMMON_CORE",
        "contract_version": normalized.version,
        "contract_sha256": sha256(contract_path),
        "classification": normalized.classification,
        "admission_evidence": False,
        "validity_model": {
            "runtime_valid": "process/runtime and interposer exception checks",
            "transport_valid": "runtime plus route and channel/relay coverage",
            "semantic_valid": "target transform, preservation, persistence and Planning consumption",
            "behavior_valid": "arm-specific frozen outcome plus collision/lane-safety checks",
            "admission_valid": "always false for privileged sensitivity probes",
        },
        "checks": checks,
        "manifest_delta": manifest,
        "first_planning_delta": delta,
        "runs": {"S0": s0, "S1": s1},
        "persistent_s1_cancels_overtake": passed,
        "status": "PERSISTENT_INTERFACE_PAIR_PASS" if passed else "PERSISTENT_INTERFACE_PAIR_REJECTED",
        "non_claims": [
            "Not a natural PR826 fault run.",
            "Not admission evidence.",
            "Legacy infrastructure_valid is compatibility telemetry, not the common validity decision.",
        ],
    }
