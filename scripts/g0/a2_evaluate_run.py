#!/usr/bin/env python3
"""Evaluator-only A2 verification and per-run manifest generation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

import yaml


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--isolation", type=Path, required=True)
    parser.add_argument("--injector-stats", type=Path, required=True)
    parser.add_argument("--versions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = json.loads(args.result.read_text())
    oracle = json.loads(args.oracle.read_text())
    isolation = json.loads(args.isolation.read_text())
    stats = json.loads(args.injector_stats.read_text())
    versions = yaml.safe_load(args.versions.read_text())
    action_path = args.result.parents[3] / "runtime" / "runs" / "a2" / run["run_id"] / "visible" / "i2_action.json"
    query_path = action_path.with_name("o1_tracking_window.json")
    checks = {
        "run_pass": run["result"] == "PASS",
        "scenario_match": oracle["scenario_id"] == run["scenario_id"],
        "oracle_hidden_flag": oracle["oracle"]["visible_to_diagnosis"] is False,
        "fault_effect_matches_oracle": oracle["oracle"]["fault_type"]
        == "control_delay"
        and run["observed"]["control_target_response_lag_seconds"] >= 1.5,
        "injector_operated": stats["released_delayed_targets"] > 0,
        "intervention_operated": stats["probe_requests"] == 1
        and stats["probe_publications"] > 1,
        "oracle_isolation": isolation["result"] == "PASS",
    }
    manifest = {
        "schema_version": "run_manifest_v0",
        "scenario_id": run["scenario_id"],
        "seed": int(run["run_id"]),
        "fault": {
            "type": oracle["oracle"]["fault_type"],
            "responsibility_domain": oracle["oracle"]["root_module"],
            "start_time": oracle["oracle"]["fault_start_time"],
            "private_during_diagnosis": True,
        },
        "versions": {
            "apollo": versions["apollo_release"],
            "application_pnc_commit": versions["application_pnc_commit"],
            "carla": versions["carla_release"],
            "bridge_commit": versions["bridge_commit"],
            "bundle_revision": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=args.result.parents[3],
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
            or "uncommitted_bundle",
            "python": platform.python_version(),
        },
        "permissions": {
            "observation": "L1",
            "intervention": "R2_non_GT_semantic_replacement",
            "diagnosis_uid": 1001,
            "oracle_uid": 0,
        },
        "artifacts": {
            "run_result": {"sha256": digest(args.result), "bytes": args.result.stat().st_size},
            "observation": {"sha256": digest(query_path), "bytes": query_path.stat().st_size},
            "action": {"sha256": digest(action_path), "bytes": action_path.stat().st_size},
            "isolation": {"sha256": digest(args.isolation), "bytes": args.isolation.stat().st_size},
            "injector_stats": {
                "sha256": digest(args.injector_stats),
                "bytes": args.injector_stats.stat().st_size,
                "evaluator_only": True,
            },
        },
        "checks": checks,
        "result": "PASS" if all(checks.values()) else "FAIL",
    }
    atomic_json(args.output, manifest)
    print(json.dumps(manifest, sort_keys=True))
    raise SystemExit(0 if manifest["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
