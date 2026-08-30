#!/usr/bin/env python3
"""Aggregate compact common-core pair audits under the frozen v5 contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from p4_sensitivity_audit_core import adapt_contract, sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--pair", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_bytes())
    normalized = adapt_contract(contract)
    audits = [json.loads(path.read_text()) for path in args.pair]
    if len(audits) != len(normalized.expected_pairs):
        raise SystemExit("pair audit count does not match frozen expected_pairs")
    checks = []
    for expected, path, audit in zip(normalized.expected_pairs, args.pair, audits):
        observed = (audit["runs"]["S0"]["run_id"], audit["runs"]["S1"]["run_id"])
        checks.append(
            {
                "expected": list(expected),
                "observed": list(observed),
                "run_ids_match": observed == expected,
                "pair_audit_sha256": sha256(path),
                "pair_pass": audit["status"] == "PERSISTENT_INTERFACE_PAIR_PASS",
                "all_pair_checks_pass": all(audit["checks"].values()),
            }
        )
    s0_hashes = [
        audit["runs"]["S0"]["files"]["normalized_repeat_manifest_sha256"]
        for audit in audits
    ]
    s1_hashes = [
        audit["runs"]["S1"]["files"]["normalized_repeat_manifest_sha256"]
        for audit in audits
    ]
    repeat_matching = {
        "s0_normalized_manifests_equal": len(set(s0_hashes)) == 1,
        "s1_normalized_manifests_equal": len(set(s1_hashes)) == 1,
        "s0_hashes": s0_hashes,
        "s1_hashes": s1_hashes,
    }
    stable = (
        all(
            row["run_ids_match"] and row["pair_pass"] and row["all_pair_checks_pass"]
            for row in checks
        )
        and repeat_matching["s0_normalized_manifests_equal"]
        and repeat_matching["s1_normalized_manifests_equal"]
    )
    result = {
        "schema_version": 2,
        "analysis_type": "P4_PERSISTENT_SENSITIVITY_COMMON_AGGREGATE",
        "classification": normalized.classification,
        "admission_evidence": False,
        "contract_sha256": sha256(args.contract),
        "pair_checks": checks,
        "repeat_matching": repeat_matching,
        "stable_persistent_s1_cancellation": stable,
        "status": (
            "STABLE_PERSISTENT_S1_CANCELLATION_3_OF_3"
            if stable
            else "PERSISTENT_S1_CANCELLATION_NOT_STABLE"
        ),
        "claim_if_pass": (
            "Persistent Prediction semantic occupancy is a reproducible system-level failure amplifier in this configured scenario."
            if stable
            else None
        ),
        "non_claim": "This does not establish that PR826 naturally produces the same phenotype.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
