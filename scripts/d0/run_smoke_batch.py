#!/usr/bin/env python3
"""Evaluator-only, append-safe orchestration of all D0-A0 companion runs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def atomic_json(path: Path, value: dict, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--private-oracle-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    private_batch = args.private_oracle_root / args.batch_id
    checkpoint_path = args.state_root / f"{args.batch_id}_execution.json"
    checkpoint = (
        json.loads(checkpoint_path.read_text())
        if checkpoint_path.exists()
        else {"schema_version": 1, "batch_id": args.batch_id, "runs": {}, "status": "RUNNING"}
    )
    env = os.environ.copy()
    env.update(
        CAGE_BUNDLE_ROOT=str(args.bundle_root),
        CAGE_RUNTIME_ROOT=str(args.runtime_root),
        CAGE_STATE_ROOT=str(args.state_root),
        CAGE_DATA_ROOT=str(args.data_root),
        CAGE_PRIVATE_ORACLE_ROOT=str(args.private_oracle_root),
        CAGE_D0_BATCH_ID=args.batch_id,
    )
    start = time.monotonic()
    failures = 0
    oracles = sorted(private_batch.glob("episode_*.json"))
    for oracle_path in oracles:
        oracle = json.loads(oracle_path.read_text())
        for role, run_id in oracle["runs"].items():
            status_path = args.state_root / "runs" / args.batch_id / f"{run_id}.status"
            metrics_path = private_batch / run_id / "run_metrics.json"
            already_pass = (
                status_path.exists()
                and status_path.read_text().splitlines()[0] == "status=PASS"
                and metrics_path.exists()
            )
            if already_pass:
                outcome = "SKIP_ALREADY_PASS"
                returncode = 0
            else:
                command = [
                    str(args.repo_root / "scripts/d0/run_smoke_once.sh"),
                    oracle["episode_id"],
                    run_id,
                ]
                completed = subprocess.run(command, cwd=args.repo_root, env=env, check=False)
                returncode = completed.returncode
                outcome = "PASS" if returncode == 0 else "FAIL"
            checkpoint["runs"][run_id] = {
                "episode_id": oracle["episode_id"],
                "role": role,
                "outcome": outcome,
                "returncode": returncode,
            }
            checkpoint["completed_count"] = sum(
                row["returncode"] == 0 for row in checkpoint["runs"].values()
            )
            checkpoint["failed_count"] = sum(
                row["returncode"] != 0 for row in checkpoint["runs"].values()
            )
            checkpoint["elapsed_powered_hours"] = round((time.monotonic() - start) / 3600, 6)
            atomic_json(checkpoint_path, checkpoint)
            failures += returncode != 0
    subprocess.run([str(args.bundle_root / "scripts/manage_carla_bridge.sh"), "stop"], check=False)
    subprocess.run([str(args.bundle_root / "scripts/manage_carla_server.sh"), "stop"], check=False)
    checkpoint["status"] = "PASS" if failures == 0 else "FAIL"
    atomic_json(checkpoint_path, checkpoint)
    print(f"d0_a0_batch={checkpoint['status']} runs={len(checkpoint['runs'])} failures={failures}")
    raise SystemExit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
