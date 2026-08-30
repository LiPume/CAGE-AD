#!/usr/bin/env python3
"""Aggregate three preregistered P4-SENS v2 S0/S1 pair audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--pair-a", type=Path, required=True)
    parser.add_argument("--pair-b", type=Path, required=True)
    parser.add_argument("--pair-c", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_bytes())
    if contract["status"] != "FROZEN_BEFORE_FIRST_V2_RESULT":
        raise SystemExit("v2 contract is not frozen")
    paths = [args.pair_a, args.pair_b, args.pair_c]
    audits = [json.loads(path.read_text()) for path in paths]
    expected_pairs = [
        ("PV0_A", "PV1_A"),
        ("PV0_B", "PV1_B"),
        ("PV0_C", "PV1_C"),
    ]
    checks = []
    for expected, audit in zip(expected_pairs, audits):
        observed = (audit["runs"]["S0"]["run_id"], audit["runs"]["S1"]["run_id"])
        checks.append(
            {
                "expected": expected,
                "observed": observed,
                "run_ids_match": observed == expected,
                "pair_status_pass": audit["status"]
                == "SENSITIVITY_SCREEN_PASS_CONFIRMATION_REQUIRED",
                "signal_observed": audit["sensitivity_signal_observed"] is True,
                "transport_valid": all(
                    all(run["transport_checks"].values())
                    for run in audit["runs"].values()
                ),
                "semantic_valid": all(
                    all(run["semantic_checks"].values())
                    for run in audit["runs"].values()
                ),
                "delta_checks": audit["pair_delta"]["checks"],
                "lane_entry_delay_s": audit["pair_delta"]["lane_minus_1_entry_delay_s"],
                "path_state_delta": audit["pair_delta"][
                    "longest_s0_lane_change_s1_not_interval"
                ],
            }
        )
    stable = all(
        row["run_ids_match"]
        and row["pair_status_pass"]
        and row["signal_observed"]
        and row["transport_valid"]
        and row["semantic_valid"]
        for row in checks
    )
    result = {
        "schema_version": 1,
        "analysis_type": "P4_SENSITIVITY_V2_STABILITY",
        "classification": "NON_ADMISSION_CAUSAL_SENSITIVITY_PROBE",
        "admission_evidence": False,
        "contract_sha256": sha256(args.contract),
        "pair_audit_hashes": [
            {"path": str(path), "sha256": sha256(path)} for path in paths
        ],
        "pair_checks": checks,
        "stable_sensitivity_established": stable,
        "status": "STABLE_PLANNING_SENSITIVITY_PASS" if stable else "SENSITIVITY_NOT_STABLE",
        "next_gate": (
            "PR826_CANDIDATE_TO_EMITTED_TRAJECTORY_NATURAL_CHAIN_AUDIT"
            if stable else "CLOSE_SCENE_OR_INVESTIGATE_REPEAT_DIVERGENCE"
        ),
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
