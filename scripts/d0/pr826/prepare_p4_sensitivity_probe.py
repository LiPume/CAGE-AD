#!/usr/bin/env python3
"""Prepare one append-only non-admission P4-SENS run from a frozen source manifest."""

from __future__ import annotations

import argparse
import copy
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


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--semantic", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_bytes())
    if contract["status"] != "FROZEN_BEFORE_FIRST_RESULT":
        raise SystemExit("P4-SENS contract is not frozen")
    if contract["classification"] != "NON_ADMISSION_CAUSAL_SENSITIVITY_PROBE":
        raise SystemExit("P4-SENS classification mismatch")
    if args.semantic not in contract["semantics"]:
        raise SystemExit("semantic is not declared by the contract")
    declared_ids = {
        *contract["run_schedule"]["initial_screen_ids"].values(),
        *contract["run_schedule"]["conditional_confirmation_ids"]["S0_STRAIGHT"],
        *contract["run_schedule"]["conditional_confirmation_ids"]["S1_LEFT_MERGE_OCCUPANCY"],
    }
    if args.run_id not in declared_ids:
        raise SystemExit("run id is not preregistered")
    if args.run_dir.exists():
        raise SystemExit("append-only run directory already exists")
    if args.ledger.exists() and any(
        json.loads(line).get("run_id") == args.run_id
        for line in args.ledger.read_text().splitlines()
        if line.strip()
    ):
        raise SystemExit("append-only run id already exists")
    expected_source_sha = contract["frozen_hashes"]["source_manifest_sha256"]
    if sha256(args.source_manifest) != expected_source_sha:
        raise SystemExit("source manifest checksum mismatch")
    for artifact in contract["frozen_artifacts"]:
        path = Path(artifact["path"])
        if sha256(path) != artifact["sha256"]:
            raise SystemExit(f"frozen artifact checksum mismatch: {path}")

    source = json.loads(args.source_manifest.read_text())
    manifest = copy.deepcopy(source)
    manifest.update(
        {
            "screening_id": args.run_id,
            "phase": "P4_SENSITIVITY_PROBE_NON_ADMISSION",
            "admission_evidence": False,
            "created_at": args.timestamp,
            "source_manifest": {
                "path": str(args.source_manifest.resolve()),
                "sha256": expected_source_sha,
            },
            "p4_sensitivity_probe": {
                "classification": contract["classification"],
                "semantic": args.semantic,
                "target_obstacle_id": contract["target"]["obstacle_id"],
                "active_elapsed_s": contract["target"]["active_elapsed_s"],
                **{
                    key: value
                    for key, value in contract["semantics"][args.semantic].items()
                    if key in {"lateral_offset_m", "relative_start_s", "relative_end_s"}
                },
                "contract_path": str(args.contract.resolve()),
                "contract_sha256": sha256(args.contract),
            },
        }
    )
    args.run_dir.mkdir(parents=True)
    manifest_path = args.run_dir / "manifest.json"
    atomic_json(manifest_path, manifest)
    append_jsonl(
        args.ledger,
        {
            "timestamp": args.timestamp,
            "event": "PLANNED",
            "run_id": args.run_id,
            "semantic": args.semantic,
            "classification": contract["classification"],
            "admission_evidence": False,
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256(manifest_path),
        },
    )
    print(manifest_path)


if __name__ == "__main__":
    main()
