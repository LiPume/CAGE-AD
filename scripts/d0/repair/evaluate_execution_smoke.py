#!/usr/bin/env python3
"""Apply the frozen Stage-B gate and persist a resumable result."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runtime-summary", type=Path, required=True)
    parser.add_argument("--stack-log", type=Path, required=True)
    parser.add_argument("--empty-road-stats", type=Path, required=True)
    parser.add_argument("--runtime-exit", type=int, required=True)
    parser.add_argument("--powered-on-seconds", type=float, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads(args.runtime_summary.read_text()) if args.runtime_summary.exists() else None
    heartbeat = json.loads(args.empty_road_stats.read_text()) if args.empty_road_stats.exists() else None
    stack_text = args.stack_log.read_text(errors="replace") if args.stack_log.exists() else ""
    missing_lines = sorted(
        {line.strip() for line in stack_text.splitlines() if "lane_follow_stage" in line and "is not found" in line}
    )
    checks = {
        "runtime_exit_zero": args.runtime_exit == 0,
        "summary_present": summary is not None,
        "empty_road_runtime_present": heartbeat is not None,
        "no_frame_gap": bool(summary and summary["non_unit_frame_gaps"] == 0),
        "duration_complete": bool(summary and summary["sim_duration_s"] >= 19.9),
        "no_npc": bool(summary and summary["npc_vehicle_count"] == 0),
        "route_accepted": bool(summary and summary["route"]["route_accepted"]),
        "gear_mismatch_at_most_3": bool(summary and summary["drive_gear_mismatch_frames"] <= 3),
        "valid_trajectory_coverage_at_least_0_95": bool(summary and summary["valid_trajectory_frame_coverage"] >= 0.95),
        "control_topic_guarded": bool(summary and summary["control_topic"] == "/apollo/control_guarded"),
        "tracking_window_pass": bool(summary and summary["tracking_window"].get("passed")),
        "progress_at_least_10m": bool(summary and summary["progress_m"] >= 10.0),
        "no_lane_follow_config_missing": not missing_lines,
    }
    passed = all(checks.values())
    result = {
        "schema_version": 1,
        "label": "RUNTIME_REPAIR_SMOKE_NOT_DATASET",
        "run_id": args.run_id,
        "result": "PASS" if passed else "FAIL",
        "checks": checks,
        "runtime_exit": args.runtime_exit,
        "powered_on_seconds": args.powered_on_seconds,
        "source_commit": args.source_commit,
        "runtime_summary": summary,
        "empty_road_stats": heartbeat,
        "lane_follow_config_missing_lines": missing_lines,
    }
    _atomic_json(args.output, result)
    print(json.dumps({"result": result["result"], "checks": checks}, sort_keys=True))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
