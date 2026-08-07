#!/usr/bin/env python3
"""Prepare one isolated diagnostic-only replay without touching calibration state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from cage_ad.protocol_v1.loader import load_protocol
from cage_ad.protocol_v1.scenario import scenario_candidate_by_id


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _atomic(path: Path, value: dict, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--calibration-state-root", type=Path, required=True)
    parser.add_argument("--calibration-data-root", type=Path, required=True)
    parser.add_argument("--calibration-private-root", type=Path, required=True)
    parser.add_argument("--diagnostic-state-root", type=Path, required=True)
    parser.add_argument("--diagnostic-data-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--seed", type=int, default=1101)
    args = parser.parse_args()
    if args.seed != 1101:
        raise SystemExit("diagnostic replay must use calibration seed 1101")
    if args.duration_s not in {32.0, 60.0}:
        raise SystemExit("diagnostic duration must be exactly 32 or 60 seconds")
    state = args.diagnostic_state_root.resolve()
    data = args.diagnostic_data_root.resolve()
    forbidden = [
        (args.calibration_state_root / "calibration").resolve(),
        (args.calibration_state_root / "ledger").resolve(),
        args.calibration_data_root.resolve(),
        args.calibration_private_root.resolve(),
    ]
    if any(_inside(state, item) or _inside(data, item) or _inside(item, state) or _inside(item, data) for item in forbidden):
        raise SystemExit("diagnostic target overlaps calibration state/data")
    bundle = load_protocol(args.repo_root)
    candidate = scenario_candidate_by_id(bundle, args.scenario_id, args.candidate_id)
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=args.repo_root, check=True, text=True, capture_output=True
    ).stdout.strip()
    run_state = state / "runs" / args.run_id
    private = data / args.run_id / "private"
    retained = data / args.run_id / "retained"
    scenario = {
        "protocol_version": bundle.episodes["protocol_version"],
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "scenario_id": args.scenario_id,
        "candidate_id": args.candidate_id,
        "seed": args.seed,
    }
    interposer = {
        **scenario,
        "fault_id": None,
        "dose": None,
        "probe_domain": None,
        "trigger_window": list(candidate.trigger_window),
    }
    diagnostic = {
        **scenario,
        "run_id": args.run_id,
        "duration_s": args.duration_s,
        "diagnostic_only_not_dataset": True,
        "source_commit": source_commit,
    }
    config_hash = hashlib.sha256(
        json.dumps(diagnostic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    planned = {
        "schema_version": 1,
        "status": "PLANNED",
        "label": "DIAGNOSTIC_ONLY_NOT_DATASET",
        "run_id": args.run_id,
        "seed": args.seed,
        "scenario_id": args.scenario_id,
        "candidate_id": args.candidate_id,
        "duration_s": args.duration_s,
        "source_commit": source_commit,
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "config_sha256": config_hash,
        "private_root": str(private),
        "retained_root": str(retained),
    }
    planned_path = run_state / "planned.json"
    if planned_path.exists():
        if json.loads(planned_path.read_text()) != planned:
            raise SystemExit("existing diagnostic plan differs")
    else:
        _atomic(planned_path, planned)
    _atomic(private / "scenario.json", scenario)
    _atomic(private / "interposer.json", interposer)
    _atomic(private / "diagnostic.json", diagnostic)
    retained.mkdir(parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    os.chmod(retained, 0o700)
    print(json.dumps(planned, sort_keys=True))


if __name__ == "__main__":
    main()
