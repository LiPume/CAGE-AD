#!/usr/bin/env python3
"""Audit three normal-only repeats before authorizing a native fault arm."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def normalized_manifest(path: Path) -> str:
    value = json.loads(path.read_text())
    value.pop("screening_id", None)
    value.pop("created_at", None)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--run", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_text())
    expected = [item["run_id"] for item in contract["repeat_schedule"]]
    if len(args.run) != len(expected):
        raise SystemExit("run count mismatch")
    gate = contract["normal_gate"]
    rows = []
    for expected_id, run in zip(expected, args.run):
        manifest_path, summary_path = run / "manifest.json", run / "summary.json"
        manifest = json.loads(manifest_path.read_text())
        metrics = json.loads(summary_path.read_text())["metrics"]
        checks = {
            "run_id": manifest["screening_id"] == expected_id,
            "domain_inactive": manifest["private_prediction_runtime"]["domain_active"] is False,
            "runtime_exception_absent": metrics["runtime_exception"] is None,
            "route_accepted": metrics["route"]["accepted"] is True,
            "collision_free": metrics["collision_count"] <= gate["collision_count_max"],
            "illegal_lane_invasion_free": metrics["illegal_lane_invasion_count"]
            <= gate["illegal_lane_invasion_count_max"],
            "prediction_coverage": metrics["target_prediction_trajectory_coverage"]
            >= gate["prediction_trajectory_coverage_min"],
            "planning_coverage": metrics["planning_channel_coverage"]
            >= gate["planning_channel_coverage_min"],
            "control_coverage": metrics["control_channel_coverage"]
            >= gate["control_channel_coverage_min"],
            "overtake_success": metrics["overtake_success"] is True,
            "pass_margin": metrics["max_pass_margin_m"] >= gate["maximum_pass_margin_m_min"],
            "success_region": metrics["success_region_reached"] is True,
        }
        rows.append(
            {
                "run_id": expected_id,
                "status": "PASS" if all(checks.values()) else "REJECT",
                "checks": checks,
                "manifest_sha256": sha256(manifest_path),
                "normalized_manifest_sha256": normalized_manifest(manifest_path),
                "summary_sha256": sha256(summary_path),
                "metrics": {
                    "max_pass_margin_m": metrics["max_pass_margin_m"],
                    "planning_valid_ratio": metrics["planning_valid_ratio"],
                    "prediction_trajectory_coverage": metrics[
                        "target_prediction_trajectory_coverage"
                    ],
                    "planning_channel_coverage": metrics["planning_channel_coverage"],
                    "control_channel_coverage": metrics["control_channel_coverage"],
                },
            }
        )
    stable = all(row["status"] == "PASS" for row in rows) and len(
        {row["normalized_manifest_sha256"] for row in rows}
    ) == 1
    result = {
        "schema_version": 1,
        "analysis_type": "P4B_NORMAL_ONLY_FORMAL_REPEAT_AUDIT",
        "contract_sha256": sha256(args.contract),
        "runs": rows,
        "stable_reference": stable,
        "active_fault_run_authorized": stable,
        "status": "STABLE_NORMAL_REFERENCE_3_OF_3" if stable else "NORMAL_REFERENCE_NOT_STABLE",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
