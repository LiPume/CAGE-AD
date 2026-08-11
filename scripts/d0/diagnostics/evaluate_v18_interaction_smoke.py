#!/usr/bin/env python3
"""Apply the frozen V18 single-scenario admission gate offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from statistics import median


EXPECTED_TABLE_SHA256 = "2693818651d7799eac5f206b88af0c0fb86f38b34443c1b14b4ccd45ffe482aa"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planned", type=Path, required=True)
    parser.add_argument("--finished", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--config-manifest", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    planned = json.loads(args.planned.read_text())
    finished = json.loads(args.finished.read_text())
    summary = json.loads(args.summary.read_text())
    manifest = json.loads(args.config_manifest.read_text())
    rows = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
    pre_conflict_speeds = [
        (row["ego"]["velocity"]["x"] ** 2 + row["ego"]["velocity"]["y"] ** 2) ** 0.5
        for row in rows if 3.0 <= float(row["sim_time_s"]) <= 6.0
    ]
    separations = [float(row["geometry"]["current_obb_separation_m"]) for row in rows]
    production_ttc = [
        float(row["geometry"]["production_ttc_s"])
        for row in rows if row["geometry"]["production_ttc_s"] is not None
    ]
    interaction_table_relpath = "apollo_conf/modules/control/control_component/conf/calibration_table.pb.txt"
    checks = {
        "run_completed_without_runtime_error": finished.get("status") == "COMPLETED" and finished.get("runtime_exit") == 0,
        "identity_is_exactly_one_ego_and_one_actor": len(summary.get("unique_ego_actor_ids", [])) == 1 and len(summary.get("unique_interaction_actor_ids", [])) == 1,
        "duration_is_32_seconds_with_640_frames": planned.get("duration_s") == 32.0 and summary.get("trace_frames") == 640 and summary.get("sim_duration_s", 0.0) >= 31.9,
        "frame_sequence_has_no_gaps": summary.get("non_unit_frame_gaps") == 0,
        "spawn_offset_error_at_most_0_10_m": summary.get("actor_spawn_offset_error_m", 999.0) <= 0.10,
        "yaw_error_at_most_1_degree": summary.get("actor_yaw_error_deg", 999.0) <= 1.0,
        "actor_velocity_rmse_at_most_0_25_mps": summary.get("actor_velocity_rmse_mps", 999.0) <= 0.25,
        "actor_conflict_timing_error_at_most_0_15_s": summary.get("actor_conflict_timing_error_s") is not None and abs(summary["actor_conflict_timing_error_s"]) <= 0.15,
        "actor_stop_was_observed": summary.get("events", {}).get("actor_stops_s") is not None,
        "ego_pre_conflict_speed_median_at_least_1_8_mps": bool(pre_conflict_speeds) and median(pre_conflict_speeds) >= 1.8,
        "vehicles_really_approached": bool(separations) and min(separations) < separations[0] and summary.get("positive_closing_duration_s", 0.0) > 0.0,
        "production_ttc_is_not_all_null": summary.get("production_finite_ttc_ticks", 0) > 0,
        "independent_ttc_is_not_all_null": summary.get("independent_finite_ttc_ticks", 0) > 0,
        "no_stable_production_independent_null_disagreement": summary.get("stable_finite_null_disagreement_ticks") == 0,
        "production_ttc_enters_2_5_to_6_second_band": any(2.5 < value <= 6.0 for value in production_ttc),
        "frozen_v17_table_is_bound_to_run": planned.get("calibration_table_sha256") == EXPECTED_TABLE_SHA256 and manifest.get("calibration_table_sha256") == EXPECTED_TABLE_SHA256 and interaction_table_relpath in manifest.get("files", {}),
    }
    result = "PASS_INTERACTION_SMOKE" if all(checks.values()) else "STOP_AND_AUDIT"
    document = {
        "schema_version": 1,
        "label": "DIAGNOSTIC_ONLY_NOT_DATASET",
        "run_id": planned.get("run_id"),
        "result": result,
        "checks": checks,
        "metrics": {
            "pre_conflict_speed_median_mps": None if not pre_conflict_speeds else median(pre_conflict_speeds),
            "initial_obb_separation_m": None if not separations else separations[0],
            "minimum_obb_separation_m": None if not separations else min(separations),
            "production_finite_ttc_ticks": summary.get("production_finite_ttc_ticks"),
            "independent_finite_ttc_ticks": summary.get("independent_finite_ttc_ticks"),
            "minimum_positive_production_ttc_s": min((value for value in production_ttc if value > 0.0), default=None),
            "first_production_finite_ttc_elapsed_s": summary.get("first_production_finite_ttc_elapsed_s"),
        },
        "provenance": {
            "source_commit": args.source_commit,
            "planned_sha256": _sha(args.planned),
            "finished_sha256": _sha(args.finished),
            "summary_sha256": _sha(args.summary),
            "trace_sha256": _sha(args.trace),
            "config_manifest_sha256": _sha(args.config_manifest),
        },
    }
    _atomic(args.output, document)
    print(json.dumps(document, sort_keys=True))
    raise SystemExit(0 if result == "PASS_INTERACTION_SMOKE" else 2)


if __name__ == "__main__":
    main()
