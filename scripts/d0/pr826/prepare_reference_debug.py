#!/usr/bin/env python3
"""Freeze one P2-D debug-only repeat derived from the retained RF01 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def canonical_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--debug-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--apollo-clock-mode", choices=("CYBER", "MOCK"), default="CYBER")
    parser.add_argument("--realtime-factor", type=float, default=1.0)
    args = parser.parse_args()
    baseline_bytes = args.baseline_manifest.read_bytes()
    manifest = json.loads(baseline_bytes)
    manifest.update({
        "screening_id": args.debug_id,
        "phase": "P2_D_REFERENCE_REPEATABILITY_DEBUG",
        "admission_evidence": False,
        "created_at": args.timestamp,
        "derived_from_manifest": str(args.baseline_manifest.resolve()),
        "derived_from_manifest_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "determinism_protocol": {
            "synchronous_mode_before_reload": True,
            "reload_world_each_run": True,
            "fixed_delta_seconds": manifest["fixed_environment"]["fixed_delta_seconds"],
            "substepping": True,
            "max_substep_delta_time": 0.01,
            "max_substeps": 10,
            "traffic_manager_used": False,
            "bridge_realtime_factor": args.realtime_factor,
            "apollo_cyber_clock_mode": args.apollo_clock_mode,
            "apollo_cyber_run_mode": "REALITY",
            "spawn_order": ["ego", "target_npc", "collision_sensor", "lane_invasion_sensor"],
        },
        "instrumentation": {
            "planning_input_timeline": True,
            "carla_settings_and_spawn_provenance": True,
            "native_planning_log_index": True,
        },
    })
    args.run_dir.mkdir(parents=True, exist_ok=False)
    payload = canonical_bytes(manifest)
    manifest_path = args.run_dir / "manifest.json"
    temporary = manifest_path.with_suffix(f".tmp.{os.getpid()}")
    temporary.write_bytes(payload)
    os.replace(temporary, manifest_path)
    ledger_entry = {
        "timestamp": args.timestamp,
        "event": "P2_D_DEBUG_PLANNED",
        "debug_id": args.debug_id,
        "candidate_id": manifest["candidate"]["candidate_id"],
        "admission_evidence": False,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "derived_from_manifest_sha256": manifest["derived_from_manifest_sha256"],
        "apollo_cyber_clock_mode": args.apollo_clock_mode,
        "apollo_cyber_run_mode": "REALITY",
        "bridge_realtime_factor": args.realtime_factor,
    }
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger_entry, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(manifest_path)


if __name__ == "__main__":
    main()
