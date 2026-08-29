#!/usr/bin/env python3
"""Prepare an append-only P2B normal-only screening with the port disabled."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml


def canonical_sha(value: object) -> str:
    return hashlib.sha256(
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--screening-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()
    contract_bytes = args.contract.read_bytes()
    contract = yaml.safe_load(contract_bytes)
    if contract.get("status") != "FROZEN_BEFORE_SCREENING_RESULT":
        raise SystemExit("P2B contract is not frozen")
    if contract.get("screening_id") != args.screening_id:
        raise SystemExit("screening id is not preregistered")
    registry = yaml.safe_load(args.registry.read_bytes())
    candidates = [
        candidate
        for candidate in registry["candidates"]
        if candidate["candidate_id"] == args.candidate_id
    ]
    if len(candidates) != 1:
        raise SystemExit("candidate must exist exactly once")
    candidate = candidates[0]
    if not candidate.get("p2b_normal_only_before_new_active_run"):
        raise SystemExit("candidate is not marked P2B normal-only")
    hashes = contract["frozen_hashes"]
    checks = {
        "registry": file_sha(args.registry) == hashes["registry_sha256"],
        "candidate": canonical_sha(candidate) == hashes["candidate_canonical_sha256"],
        "fixed_environment": canonical_sha(registry["fixed_environment"])
        == hashes["fixed_environment_canonical_sha256"],
    }
    runtime = contract["prediction_runtime"]
    for name in ("component", "behavior"):
        checks[name] = file_sha(Path(runtime[f"{name}_library"])) == runtime[
            f"{name}_sha256"
        ]
    if not all(checks.values()):
        raise SystemExit(f"P2B preflight failed: {checks}")

    manifest = {
        "schema_version": 1,
        "protocol_version": registry["protocol_version"],
        "screening_id": args.screening_id,
        "phase": "P2B_NORMAL_ONLY_SCREENING",
        "arm": "A",
        "admission_evidence": False,
        "fault_patch_exists": True,
        "fault_result_seen_for_this_geometry": False,
        "candidate": candidate,
        "fixed_environment": registry["fixed_environment"],
        "registry_path": str(args.registry.resolve()),
        "registry_sha256": file_sha(args.registry),
        "p2b_contract": {
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
            "domain_active": False,
            "trace_active": True,
        },
        "created_at": args.timestamp,
    }
    manifest_path = args.run_dir / "manifest.json"
    existing = [
        json.loads(line) for line in args.ledger.read_text().splitlines() if line.strip()
    ] if args.ledger.exists() else []
    if manifest_path.exists() or any(
        row.get("screening_id") == args.screening_id for row in existing
    ):
        raise SystemExit("append-only policy forbids replacing this screening")
    atomic_json(manifest_path, manifest)
    append_jsonl(
        args.ledger,
        {
            "event": "PLANNED",
            "timestamp": args.timestamp,
            "screening_id": args.screening_id,
            "candidate_id": args.candidate_id,
            "manifest_path": str(manifest_path),
            "manifest_sha256": file_sha(manifest_path),
            "domain_active": False,
            "fault_result_seen_for_this_geometry": False,
            "status": "INCONCLUSIVE",
        },
    )
    print(manifest_path)


if __name__ == "__main__":
    main()
