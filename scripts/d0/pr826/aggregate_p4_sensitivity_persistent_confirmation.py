#!/usr/bin/env python3
"""Aggregate one frozen screen pair plus two prospective persistent confirmations."""

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


def normalized_manifest(path: Path) -> dict:
    value = json.loads(path.read_text())
    value.pop("created_at", None)
    value.pop("screening_id", None)
    probe = value["p4_sensitivity_probe"]
    probe.pop("contract_path", None)
    probe.pop("contract_sha256", None)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--pair-a", type=Path, required=True)
    parser.add_argument("--pair-b", type=Path, required=True)
    parser.add_argument("--pair-c", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_bytes())
    if contract["contract_version"] != "p4-sens-boundary-v5-persistent-confirmation":
        raise SystemExit("unexpected contract version")
    if contract["status"] != "FROZEN_BEFORE_FIRST_V5_RESULT":
        raise SystemExit("contract not frozen")
    paths = [args.pair_a, args.pair_b, args.pair_c]
    audits = [json.loads(path.read_text()) for path in paths]
    expected = contract["stable_confirmation"]["expected_pairs"]
    pair_checks = []
    for expected_pair, path, audit in zip(expected, paths, audits):
        observed = [audit["runs"]["S0"]["run_id"], audit["runs"]["S1"]["run_id"]]
        pair_checks.append(
            {
                "expected": expected_pair,
                "observed": observed,
                "run_ids_match": observed == expected_pair,
                "audit_sha256": sha256(path),
                "persistent_system_kill": audit["persistent_s1_cancels_overtake"] is True,
                "all_checks_pass": all(audit["checks"].values()),
                "s0_overtake": audit["runs"]["S0"]["overtake_success"],
                "s1_overtake": audit["runs"]["S1"]["overtake_success"],
            }
        )
    cross_repeat = []
    for arm, ids in (
        ("S0", [pair[0] for pair in expected]),
        ("S1", [pair[1] for pair in expected]),
    ):
        manifests = [normalized_manifest(args.run_root / rid / "manifest.json") for rid in ids]
        cross_repeat.append(
            {
                "arm": arm,
                "run_ids": ids,
                "normalized_manifests_equal": manifests[0] == manifests[1] == manifests[2],
            }
        )
    stable = (
        all(
            row["run_ids_match"]
            and row["persistent_system_kill"]
            and row["all_checks_pass"]
            and row["s0_overtake"] is True
            and row["s1_overtake"] is False
            for row in pair_checks
        )
        and all(row["normalized_manifests_equal"] for row in cross_repeat)
    )
    result = {
        "schema_version": 1,
        "analysis_type": "P4_SENS_PERSISTENT_CONFIRMATION",
        "classification": "NON_ADMISSION_CAUSAL_SENSITIVITY_PROBE",
        "admission_evidence": False,
        "contract_sha256": sha256(args.contract),
        "pair_checks": pair_checks,
        "cross_repeat_manifest_checks": cross_repeat,
        "stable_persistent_s1_cancellation": stable,
        "status": (
            "STABLE_PERSISTENT_S1_CANCELLATION_3_OF_3"
            if stable
            else "PERSISTENT_S1_CANCELLATION_NOT_STABLE"
        ),
        "next_gate": (
            "NATURAL_PR826_CANDIDATE_TO_OUTPUT_CHAIN_SCREEN"
            if stable
            else "CLOSE_SCENE_NO_NATURAL_PR826_RUN"
        ),
        "limitations": [
            "These are privileged interface probes, not natural PR826 fault runs.",
            "This result authorizes only candidate-to-output mechanism screening, not golden-case admission.",
        ],
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
