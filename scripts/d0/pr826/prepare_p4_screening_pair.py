#!/usr/bin/env python3
"""Prepare a private matched P4 screening pair before either outcome is observed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--fixed-id", required=True)
    parser.add_argument("--active-id", required=True)
    parser.add_argument("--fixed-manifest", type=Path, required=True)
    parser.add_argument("--active-run-dir", type=Path, required=True)
    parser.add_argument("--pair-audit", type=Path, required=True)
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()

    contract_bytes = args.contract.read_bytes()
    contract = yaml.safe_load(contract_bytes)
    if contract.get("status") != "FROZEN_BEFORE_SCREENING_RESULTS":
        raise SystemExit("P4 screening contract is not frozen")
    if contract.get("screening_pair", {}).get("pair_id") != args.pair_id:
        raise SystemExit("pair id is not preregistered")
    if contract["screening_pair"].get("fixed_id") != args.fixed_id:
        raise SystemExit("fixed id is not preregistered")
    if contract["screening_pair"].get("active_id") != args.active_id:
        raise SystemExit("active id is not preregistered")

    registry_bytes = args.registry.read_bytes()
    registry = yaml.safe_load(registry_bytes)
    candidates = [
        value
        for value in registry["candidates"]
        if value["candidate_id"] == args.candidate_id
    ]
    if len(candidates) != 1:
        raise SystemExit("candidate must exist exactly once")
    candidate = candidates[0]
    fixed_environment = registry["fixed_environment"]
    hashes = contract["frozen_hashes"]
    checks = {
        "registry": file_sha(args.registry) == hashes["registry_sha256"],
        "candidate": canonical_sha(candidate) == hashes["candidate_canonical_sha256"],
        "fixed_environment": canonical_sha(fixed_environment)
        == hashes["fixed_environment_canonical_sha256"],
        "component": file_sha(Path(contract["prediction_runtime"]["component_library"]))
        == contract["prediction_runtime"]["component_sha256"],
        "behavior": file_sha(Path(contract["prediction_runtime"]["behavior_library"]))
        == contract["prediction_runtime"]["behavior_sha256"],
    }
    if not all(checks.values()):
        raise SystemExit(f"P4 frozen preflight failed: {checks}")

    runtime = contract["prediction_runtime"]

    def manifest(screening_id: str, arm: str, active: bool) -> dict:
        return {
            "schema_version": 1,
            "protocol_version": registry["protocol_version"],
            "screening_id": screening_id,
            "phase": "P4_PRIVATE_MATCHED_SCREENING",
            "pair_id": args.pair_id,
            "arm": arm,
            "fault_patch_exists": True,
            "fault_result_seen": False,
            "candidate": candidate,
            "fixed_environment": fixed_environment,
            "registry_path": str(args.registry.resolve()),
            "registry_sha256": file_sha(args.registry),
            "p4_contract": {
                "path": str(args.contract.resolve()),
                "sha256": hashlib.sha256(contract_bytes).hexdigest(),
                "contract_version": contract["contract_version"],
            },
            "private_prediction_runtime": {
                "component_library": runtime["component_library"],
                "component_sha256": runtime["component_sha256"],
                "behavior_library": runtime["behavior_library"],
                "behavior_sha256": runtime["behavior_sha256"],
                "library_dir": runtime["library_dir"],
                "domain_active": active,
                "trace_active": True,
            },
            "created_at": args.timestamp,
        }

    fixed = manifest(args.fixed_id, "A", False)
    active = manifest(args.active_id, "B", True)
    if args.fixed_manifest.exists() or (args.active_run_dir / "manifest.json").exists():
        raise SystemExit("append-only policy forbids replacing a P4 manifest")
    atomic_json(args.fixed_manifest, fixed)
    atomic_json(args.active_run_dir / "manifest.json", active)
    audit = {
        "schema_version": 1,
        "status": "PLANNED_NOT_RUN",
        "pair_id": args.pair_id,
        "fixed_manifest": str(args.fixed_manifest),
        "active_manifest": str(args.active_run_dir / "manifest.json"),
        "fixed_manifest_sha256": file_sha(args.fixed_manifest),
        "active_manifest_sha256": file_sha(args.active_run_dir / "manifest.json"),
        "preflight_checks": checks,
    }
    atomic_json(args.pair_audit, audit)
    print(json.dumps(audit, sort_keys=True))


if __name__ == "__main__":
    main()
