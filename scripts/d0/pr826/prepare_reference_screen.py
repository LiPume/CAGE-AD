#!/usr/bin/env python3
"""Freeze one normal-only reference attempt and append its PLANNED ledger event."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml


def canonical_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def canonical_sha256(value) -> str:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--screening-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--formal-contract", type=Path)
    args = parser.parse_args()
    registry_bytes = args.registry.read_bytes()
    registry = yaml.safe_load(registry_bytes)
    matches = [c for c in registry["candidates"] if c["candidate_id"] == args.candidate_id]
    if len(matches) != 1:
        raise SystemExit("candidate must exist exactly once")
    candidate = matches[0]
    if not candidate.get("execution_allowed"):
        raise SystemExit("candidate is topology-only and cannot be executed")
    formal_contract_record = None
    if args.formal_contract is not None:
        contract_bytes = args.formal_contract.read_bytes()
        contract = yaml.safe_load(contract_bytes)
        if contract.get("status") != "FROZEN_BEFORE_FORMAL_RESULTS":
            raise SystemExit("formal contract is not in a frozen pre-result state")
        if args.screening_id not in contract.get("required_repeat_ids", []):
            raise SystemExit("screening id is not preregistered in formal contract")
        if contract.get("candidate_id") != args.candidate_id:
            raise SystemExit("formal contract candidate mismatch")
        if canonical_sha256(candidate) != contract["frozen_hashes"]["candidate_canonical_sha256"]:
            raise SystemExit("formal candidate hash mismatch")
        if canonical_sha256(registry["fixed_environment"]) != (
            contract["frozen_hashes"]["fixed_environment_canonical_sha256"]
        ):
            raise SystemExit("formal fixed-environment hash mismatch")
        for artifact in contract["frozen_artifacts"]:
            path = Path(artifact["path"])
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_sha != artifact["sha256"]:
                raise SystemExit(
                    f"formal artifact hash mismatch for {path}: {actual_sha}"
                )
        formal_contract_record = {
            "path": str(args.formal_contract),
            "sha256": hashlib.sha256(contract_bytes).hexdigest(),
            "contract_version": contract["contract_version"],
            "required_repeat_ids": contract["required_repeat_ids"],
        }
    manifest = {
        "schema_version": 1,
        "protocol_version": registry["protocol_version"],
        "screening_id": args.screening_id,
        "phase": (
            "NORMAL_ONLY_REFERENCE_FORMAL_REPEAT"
            if formal_contract_record is not None else "NORMAL_ONLY_REFERENCE"
        ),
        "fault_patch_exists": False,
        "fault_result_seen": False,
        "candidate": candidate,
        "fixed_environment": registry["fixed_environment"],
        "registry_path": str(args.registry.resolve()),
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "created_at": args.timestamp,
    }
    if formal_contract_record is not None:
        manifest["formal_contract"] = formal_contract_record
    payload = canonical_bytes(manifest)
    manifest_path = args.run_dir / "manifest.json"
    if manifest_path.exists() or any(
        json.loads(line).get("screening_id") == args.screening_id
        for line in args.ledger.read_text().splitlines() if line.strip()
    ):
        raise SystemExit("screening_id or manifest already exists; append-only policy forbids reuse")
    atomic_bytes(manifest_path, payload)
    manifest_sha = hashlib.sha256(payload).hexdigest()
    append_jsonl(args.ledger, {
        "timestamp": args.timestamp,
        "event": "PLANNED",
        "screening_id": args.screening_id,
        "candidate_id": args.candidate_id,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "map": candidate["map"],
        "apollo_map_variant": candidate.get("apollo_map_variant"),
        "route_start_apollo_xy": candidate["route_start_apollo_xy"],
        "route_end_apollo_xy": candidate["route_end_apollo_xy"],
        "route_waypoints_apollo_xy": candidate.get("route_waypoints_apollo_xy"),
        "seed": registry["fixed_environment"]["seed"],
        "fault_patch_exists": False,
    })
    print(manifest_path)


if __name__ == "__main__":
    main()
