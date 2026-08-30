#!/usr/bin/env python3
"""Prepare frozen normal-only repeat manifests for scene-fault matching."""

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
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_text())
    if contract.get("status") != "FROZEN_BEFORE_FORMAL_REPEAT_RESULTS":
        raise SystemExit("repeat contract is not frozen")
    if sha256(args.source_manifest) != contract["frozen_hashes"]["source_manifest_sha256"]:
        raise SystemExit("source manifest hash mismatch")
    source = json.loads(args.source_manifest.read_text())
    if source["private_prediction_runtime"]["domain_active"] is not False:
        raise SystemExit("normal repeat source must keep native port inactive")
    written = []
    for item in contract["repeat_schedule"]:
        manifest = copy.deepcopy(source)
        manifest["screening_id"] = item["run_id"]
        manifest["created_at"] = item["created_at"]
        manifest["phase"] = "P4B_NORMAL_ONLY_FORMAL_REPEAT"
        manifest["normal_repeat_contract"] = {
            "path": str(args.contract.resolve()),
            "sha256": sha256(args.contract),
        }
        target = args.run_root / item["run_id"] / "manifest.json"
        if target.exists():
            raise SystemExit(f"repeat manifest already exists: {target}")
        atomic_json(target, manifest)
        written.append({"run_id": item["run_id"], "sha256": sha256(target)})
    print(json.dumps({"status": "PREPARED", "manifests": written}, sort_keys=True))


if __name__ == "__main__":
    main()
