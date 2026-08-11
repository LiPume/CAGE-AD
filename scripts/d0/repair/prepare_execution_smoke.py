#!/usr/bin/env python3
"""Prepare isolated nominal interposer/config inputs for one execution smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from cage_ad.protocol_v1.loader import load_protocol
from cage_ad.protocol_v1.scenario import scenario_candidate_by_id


STAGE_OVERRIDE_NAMES = (
    "lane_change_path",
    "lane_follow_path",
    "lane_borrow_path",
    "fallback_path",
    "path_decider",
    "rule_based_stop_decider",
    "speed_bounds_priori_decider",
    "speed_heuristic_optimizer",
    "speed_decider",
    "speed_bounds_final_decider",
    "piecewise_jerk_speed",
)


def _atomic_text(path: Path, value: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(value)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-state", type=Path, required=True)
    parser.add_argument("--run-data", type=Path, required=True)
    args = parser.parse_args()
    if not args.run_id.startswith("NO_NPC_"):
        raise SystemExit("invalid execution smoke run id")
    bundle = load_protocol(args.repo_root)
    candidate = scenario_candidate_by_id(bundle, "lead_brake_moderate", "LBM0")
    interposer = {
        "protocol_version": bundle.episodes["protocol_version"],
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "scenario_id": "lead_brake_moderate",
        "candidate_id": "LBM0",
        "seed": 1101,
        "fault_id": None,
        "dose": None,
        "probe_domain": None,
        "trigger_window": list(candidate.trigger_window),
        "execution_smoke_no_npc": True,
    }
    private_root = args.run_data / "private"
    _atomic_json(private_root / "interposer.json", interposer)
    stage_root = (
        args.run_data
        / "apollo_conf/modules/planning/scenarios/lane_follow/conf/lane_follow_stage"
    )
    for name in STAGE_OVERRIDE_NAMES:
        # An empty textproto is a valid no-op user override. Plugin defaults remain
        # authoritative, while Apollo no longer logs an absent optional path.
        _atomic_text(stage_root / f"{name}.pb.txt", "")
    calibration_override = os.environ.get("CAGE_APOLLO_CALIBRATION_OVERRIDE")
    if calibration_override:
        source = Path(calibration_override).resolve()
        if not source.is_file():
            raise SystemExit(f"calibration override is not a file: {source}")
        _atomic_text(
            args.run_data
            / "apollo_conf/modules/control/control_component/conf/calibration_table.pb.txt",
            source.read_text(),
        )
    config_root = args.run_data / "apollo_conf"
    config_manifest = {
        "schema_version": 1,
        "purpose": (
            "v15 reversible calibration candidate plus planning no-op overrides"
            if calibration_override
            else "explicit empty Apollo 10 user overrides; plugin defaults unchanged"
        ),
        "files": {
            str(path.relative_to(args.run_data)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(config_root.rglob("*.pb.txt"))
        },
    }
    _atomic_json(args.run_data / "apollo_conf_manifest.json", config_manifest)
    planned = {
        "schema_version": 1,
        "label": "RUNTIME_REPAIR_SMOKE_NOT_DATASET",
        "run_id": args.run_id,
        "interaction_actor": False,
        "fault_id": None,
        "formal_seed": False,
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "interposer_config_sha256": hashlib.sha256(
            json.dumps(interposer, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "apollo_conf_manifest_sha256": hashlib.sha256(
            json.dumps(config_manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    _atomic_json(args.run_state / "planned.json", planned)
    print(json.dumps(planned, sort_keys=True))


if __name__ == "__main__":
    main()
