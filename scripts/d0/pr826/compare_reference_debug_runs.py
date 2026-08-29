#!/usr/bin/env python3
"""Compare multiple P2-D repeats and verify normalized protocol equivalence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def normalized_manifest(path: Path) -> dict:
    value = json.loads(path.read_text())
    for key in ("screening_id", "created_at"):
        value.pop(key, None)
    return value


def normalized_generated(run_dir: Path) -> dict:
    result = {}
    token = str(run_dir.resolve())
    for path in sorted((run_dir / "generated").glob("**/*")):
        if not path.is_file():
            continue
        content = path.read_text(errors="replace").replace(token, "<RUN_DIR>")
        result[str(path.relative_to(run_dir / "generated"))] = hashlib.sha256(
            content.encode()
        ).hexdigest()
    return result


def event_offset(timeline: dict, name: str, origin: str) -> float | None:
    event = timeline.get(name)
    start = timeline.get(origin)
    if not event or not start:
        return None
    return event["clock_s"] - start["clock_s"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runs = []
    for run_dir in args.run_dir:
        analysis = json.loads((run_dir / "debug_analysis.json").read_text())
        summary = json.loads((run_dir / "summary.json").read_text())
        timeline = analysis["timeline"]
        metrics = summary["metrics"]
        runs.append({
            "run_id": analysis["run_id"],
            "manifest_sha256": hashlib.sha256((run_dir / "manifest.json").read_bytes()).hexdigest(),
            "normalized_manifest_sha256": digest(normalized_manifest(run_dir / "manifest.json")),
            "normalized_generated_hashes": normalized_generated(run_dir),
            "bridge_determinism": json.loads((run_dir / "bridge_determinism.json").read_text()),
            "infrastructure_valid": metrics["infrastructure_valid"],
            "overtake_success": metrics["overtake_success"],
            "collision_count": metrics["collision_count"],
            "lane_invasions": summary["lane_invasions"],
            "max_pass_margin_m": metrics["max_pass_margin_m"],
            "max_abs_lateral_excursion_m": metrics["max_abs_lateral_excursion_m"],
            "planning_valid": metrics["counts"]["planning_valid"],
            "planning_raw": metrics["counts"]["planning_raw"],
            "target_prediction": metrics["counts"]["target_prediction"],
            "target_prediction_with_trajectory": metrics["counts"][
                "target_prediction_with_trajectory"
            ],
            "first_leftreverse_sequence": (
                timeline["first_leftreverse_candidate"] or {}
            ).get("sequence_num"),
            "speed_fallback_after_leftreverse_s": event_offset(
                timeline, "first_speed_fallback", "first_leftreverse_candidate"
            ),
            "leftreverse_only_after_leftreverse_s": event_offset(
                timeline, "first_leftreverse_only", "first_leftreverse_candidate"
            ),
            "speed_fallback_init_point": (
                timeline["first_speed_fallback"] or {}
            ).get("init_point"),
            "native_event_counts": analysis["native_planning_log"].get("counts"),
            "native_first_events": analysis["native_planning_log"].get("first_events"),
            "input_age_stats_s": timeline["input_age_stats_s"],
        })
    manifest_hashes = {run["normalized_manifest_sha256"] for run in runs}
    generated_hashes = {digest(run["normalized_generated_hashes"]) for run in runs}
    pass_margins = [run["max_pass_margin_m"] for run in runs]
    fallbacks = [run["speed_fallback_after_leftreverse_s"] for run in runs
                 if run["speed_fallback_after_leftreverse_s"] is not None]
    result = {
        "schema_version": 1,
        "scope": "P2_D_DEBUG_ONLY_NOT_ADMISSION",
        "runs": runs,
        "equivalence": {
            "normalized_manifest_identical": len(manifest_hashes) == 1,
            "normalized_generated_artifacts_identical": len(generated_hashes) == 1,
            "normalized_manifest_hashes": sorted(manifest_hashes),
            "normalized_generated_artifact_set_hashes": sorted(generated_hashes),
        },
        "aggregate": {
            "run_count": len(runs),
            "infrastructure_valid_count": sum(run["infrastructure_valid"] for run in runs),
            "overtake_success_count": sum(run["overtake_success"] for run in runs),
            "target_trajectory_nonzero_run_count": sum(
                run["target_prediction_with_trajectory"] > 0 for run in runs
            ),
            "pass_margin_m": {
                "min": min(pass_margins),
                "mean": statistics.mean(pass_margins),
                "max": max(pass_margins),
                "population_stdev": statistics.pstdev(pass_margins),
            },
            "speed_fallback_after_leftreverse_s": {
                "min": min(fallbacks),
                "mean": statistics.mean(fallbacks),
                "max": max(fallbacks),
                "population_stdev": statistics.pstdev(fallbacks),
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
