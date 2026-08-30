#!/usr/bin/env python3
"""Audit the frozen P4-SENS v4 persistent S0/S1 system-kill screen."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import yaml


FROZEN_ANALYZER = Path(__file__).with_name("analyze_p4_sensitivity.py")
SPEC = importlib.util.spec_from_file_location("frozen_p4_sensitivity_analyzer", FROZEN_ANALYZER)
ANALYZER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ANALYZER)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def flatten(value, prefix="") -> dict:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            result.update(flatten(child, path))
        return result
    if isinstance(value, list):
        return {prefix: value}
    return {prefix: value}


def manifest_delta(s0_path: Path, s1_path: Path) -> dict:
    s0 = flatten(json.loads(s0_path.read_text()))
    s1 = flatten(json.loads(s1_path.read_text()))
    observed = sorted(
        key for key in set(s0) | set(s1) if s0.get(key) != s1.get(key)
    )
    permitted = {
        "created_at",
        "screening_id",
        "p4_sensitivity_probe.semantic",
        "p4_sensitivity_probe.lateral_offset_m",
        "p4_sensitivity_probe.relative_start_s",
        "p4_sensitivity_probe.relative_end_s",
    }
    return {
        "observed": observed,
        "permitted": sorted(permitted),
        "pass": set(observed) == permitted,
    }


def telemetry_extent(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    elapsed = [float(row["elapsed_s"]) for row in rows]
    return {
        "rows": len(rows),
        "first_elapsed_s": min(elapsed) if elapsed else None,
        "last_elapsed_s": max(elapsed) if elapsed else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--s0", type=Path, required=True)
    parser.add_argument("--s1", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_bytes())
    if contract["contract_version"] != "p4-sens-boundary-v4-persistent-screen":
        raise SystemExit("unexpected contract version")
    if contract["status"] != "FROZEN_BEFORE_FIRST_V4_RESULT":
        raise SystemExit("contract is not frozen")
    s0 = ANALYZER.read_run(args.s0, contract)
    s1 = ANALYZER.read_run(args.s1, contract)
    states0, states1 = s0.pop("states"), s1.pop("states")
    common = sorted(
        time for time in set(states0) & set(states1) if 12.0 <= time <= 75.0
    )
    first_planning_delta = next(
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
    matching = manifest_delta(args.s0 / "manifest.json", args.s1 / "manifest.json")
    extents = {
        "S0": telemetry_extent(args.s0 / "private_p4_sensitivity_telemetry.jsonl"),
        "S1": telemetry_extent(args.s1 / "private_p4_sensitivity_telemetry.jsonl"),
    }
    gate = contract["screen_gate"]
    checks = {
        "matched_manifests": matching["pass"],
        "transport_valid": all(
            all(run["transport_checks"].values()) for run in (s0, s1)
        ),
        "semantic_valid": all(
            all(run["semantic_checks"].values()) for run in (s0, s1)
        ),
        "planning_consumed_active_prediction": all(
            run["first_active_prediction_consumed_s"] is not None for run in (s0, s1)
        ),
        "s0_overtake_success": s0["overtake_success"]
        is gate["s0_overtake_success_required"],
        "s1_overtake_cancelled": s1["overtake_success"]
        is gate["s1_overtake_success_required"],
        "s1_pass_margin_within_gate": s1["max_pass_margin_m"]
        < gate["s1_maximum_pass_margin_m"],
        "planning_delta_observed": first_planning_delta is not None,
    }
    passed = all(checks.values())
    result = {
        "schema_version": 1,
        "analysis_type": "P4_SENS_V4_PERSISTENT_SYSTEM_KILL_SCREEN",
        "classification": contract["classification"],
        "admission_evidence": False,
        "contract_sha256": sha256(args.contract),
        "checks": checks,
        "manifest_delta": matching,
        "telemetry_extent": extents,
        "first_planning_delta": first_planning_delta,
        "runs": {"S0": s0, "S1": s1},
        "persistent_s1_cancels_overtake": passed,
        "status": (
            "PERSISTENT_S1_SCREEN_PASS_CONFIRMATION_REQUIRED"
            if passed
            else "PERSISTENT_S1_SCREEN_REJECTED"
        ),
        "next_gate": (
            gate["if_s1_does_not_overtake"]
            if passed
            else gate["if_s1_overtakes"]
        ),
        "limitations": [
            "This is a privileged interface intervention, not a natural PR826 run.",
            "One pair cannot establish stability or golden-case admission.",
            "The generic normal-reference infrastructure flag includes Planning-valid response and is not used as a transport gate.",
        ],
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
