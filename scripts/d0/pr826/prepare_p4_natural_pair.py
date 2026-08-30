#!/usr/bin/env python3
"""Prepare one matched fixed/active native PR826-family screening pair."""

from __future__ import annotations

import argparse
import copy
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
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--fixed-run-dir", type=Path, required=True)
    parser.add_argument("--active-run-dir", type=Path, required=True)
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text())
    if contract.get("status") != "FROZEN_BEFORE_SCREENING_RESULTS":
        raise SystemExit("natural-port contract is not frozen")
    source = json.loads(args.source_manifest.read_text())
    frozen = contract["frozen_hashes"]
    checks = {
        "source_manifest": sha256(args.source_manifest) == frozen["source_manifest_sha256"],
        "component": sha256(Path(contract["prediction_runtime"]["component_library"]))
        == contract["prediction_runtime"]["component_sha256"],
        "behavior": sha256(Path(contract["prediction_runtime"]["behavior_library"]))
        == contract["prediction_runtime"]["behavior_sha256"],
    }
    for name in ("renderer", "runner", "pair_checker"):
        item = frozen[name]
        checks[name] = sha256(Path(item["path"])) == item["sha256"]
    if not all(checks.values()):
        raise SystemExit(f"frozen preflight failed: {checks}")

    pair = contract["screening_pair"]
    runtime = contract["prediction_runtime"]

    def build(run_id: str, arm: str, active: bool) -> dict:
        manifest = copy.deepcopy(source)
        manifest.update(
            {
                "screening_id": run_id,
                "phase": "P4_NATURAL_PR826_PORT_MATCHED_SCREENING",
                "pair_id": pair["pair_id"],
                "arm": arm,
                "created_at": args.timestamp,
                "admission_evidence": False,
                "p4_natural_port": {
                    "classification": "PRIVATE_BENCHMARK_BUILDER_ORACLE",
                    "contract_path": str(args.contract.resolve()),
                    "contract_sha256": sha256(args.contract),
                    "semantic_patch_sha256": contract["semantic_fixture"][
                        "semantic_patch_sha256"
                    ],
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
            }
        )
        return manifest

    fixed = build(pair["fixed_id"], "A", False)
    active = build(pair["active_id"], "B", True)
    fixed_path = args.fixed_run_dir / "manifest.json"
    active_path = args.active_run_dir / "manifest.json"
    if fixed_path.exists() or active_path.exists():
        raise SystemExit("append-only run manifest already exists")
    atomic_json(fixed_path, fixed)
    atomic_json(active_path, active)
    print(
        json.dumps(
            {
                "status": "PREPARED",
                "checks": checks,
                "fixed_manifest": str(fixed_path),
                "fixed_manifest_sha256": sha256(fixed_path),
                "active_manifest": str(active_path),
                "active_manifest_sha256": sha256(active_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
