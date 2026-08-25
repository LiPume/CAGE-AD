#!/usr/bin/env python3
"""Extract private case evidence, audit leakage, and run the admission gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any

from cage_ad.benchmark_construction.admission import AdmissionPolicy, evaluate_candidate


FOLLOW_DISTANCE = re.compile(
    r"perception_id:\s*1001.*?object_decision\s*\{.*?follow\s*\{.*?distance_s:\s*(-?[0-9.]+)",
    re.DOTALL,
)
FORBIDDEN_VISIBLE = (
    "fault", "faulty", "reference", "oracle", "collision", "ttc",
    "follow_min_time", "threshold", "mutation", "failure_onset",
)


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic(path: Path, value: dict, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_bytes(_canonical_bytes(value))
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _failure_onset(rows: list[dict]) -> tuple[float | None, str | None]:
    for row in rows:
        ttc = row["geometry"].get("production_ttc_s")
        separation = row["geometry"].get("current_obb_separation_m")
        if (ttc is not None and float(ttc) <= 2.5) or (
            separation is not None and float(separation) <= 0.0
        ):
            return float(row["sim_time_s"]), "collision_or_ttc_below_2_5s"
    return None, None


def _overlay_mechanism_activation(rows: list[dict]) -> tuple[float | None, dict | None]:
    for row in rows:
        planning = row.get("apollo", {}).get("planning") or {}
        if not planning.get("decision_mentions_obstacle_1001"):
            continue
        match = FOLLOW_DISTANCE.search(planning.get("decision_text", ""))
        if match is None:
            continue
        ego_velocity = row["ego"]["velocity"]
        ego_speed = math.hypot(float(ego_velocity["x"]), float(ego_velocity["y"]))
        follow_distance = abs(float(match.group(1)))
        # At >1.25 m/s the 2.0 s vendor threshold requires >2.5 m, whereas
        # the frozen 0.1 s mutation bottoms out at the untouched 2.0 m floor.
        if ego_speed > 1.25 and follow_distance <= 2.25:
            return float(row["sim_time_s"]), {
                "ego_speed_mps": ego_speed,
                "observed_follow_distance_m": follow_distance,
                "decision_mentions_obstacle_1001": True,
            }
    return None, None


def _semantic_mechanism_activation(
    interposer_stats: dict,
) -> tuple[float | None, dict | None]:
    if interposer_stats.get("injector_exception") is not None:
        return None, None
    if int(interposer_stats.get("fault_applications", 0)) < 1:
        return None, None
    for observation in interposer_stats.get("activation_observations", []):
        metric = observation.get("metric_value")
        residual = observation.get("transform_residual")
        if (
            metric is not None
            and abs(float(metric) - 0.6) <= 0.02
            and residual is not None
            and abs(float(residual)) <= 1e-9
        ):
            return float(observation["simulator_time_s"]), {
                "observed_time_scale": float(metric),
                "transform_residual": float(residual),
                "fault_applications": int(interposer_stats["fault_applications"]),
            }
    return None, None


def _infrastructure_checks(finished: dict, summary: dict, rows: list[dict]) -> dict[str, bool]:
    timing_error = summary.get("actor_conflict_timing_error_s")
    return {
        "completed": finished.get("status") == "COMPLETED" and finished.get("runtime_exit") == 0,
        "capture_purpose": summary.get("label") == "BENCHMARK_CONSTRUCTION_CANDIDATE",
        "trace_count": len(rows) == summary.get("trace_frames") == finished.get("trace_frames") == 640,
        "continuous_frames": summary.get("non_unit_frame_gaps") == 0,
        "single_ego": len(summary.get("unique_ego_actor_ids", [])) == 1,
        "single_interaction_actor": len(summary.get("unique_interaction_actor_ids", [])) == 1,
        "duration": float(summary.get("sim_duration_s", -1)) >= 31.9,
        "spawn_geometry": float(summary.get("actor_spawn_offset_error_m", math.inf)) <= 0.10,
        "spawn_yaw": float(summary.get("actor_yaw_error_deg", math.inf)) <= 1.0,
        "actor_velocity": float(summary.get("actor_velocity_rmse_mps", math.inf)) <= 0.50,
        "conflict_timing": timing_error is not None and abs(float(timing_error)) <= 0.25,
    }


def _scan_visible(root: Path) -> list[str]:
    hits: list[str] = []
    if not root.exists():
        return hits
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        haystacks = [relative.lower()]
        if path.is_file():
            try:
                haystacks.append(path.read_text().lower())
            except UnicodeDecodeError:
                pass
        for token in FORBIDDEN_VISIBLE:
            if any(token in value for value in haystacks):
                hits.append(f"{relative}:{token}")
    return sorted(set(hits))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--visible-root", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--admission-output", type=Path, required=True)
    args = parser.parse_args()
    schedule = json.loads(args.schedule.read_text())
    if schedule.get("candidate_id") not in {"HGV1-P01-LBC0", "HGV1-P02-CIE0"} or len(schedule.get("runs", [])) != 6:
        raise SystemExit("invalid frozen six-run schedule")

    reference_runs = []
    faulty_runs = []
    source_commits: set[str] = set()
    implementation_hashes: set[str] = set()
    for scheduled in schedule["runs"]:
        run_id = scheduled["run_id"]
        planned = json.loads((args.state_root / "runs" / run_id / "planned.json").read_text())
        finished = json.loads((args.state_root / "runs" / run_id / "finished.json").read_text())
        raw = args.raw_root / run_id
        summary = json.loads((raw / "capture/summary.json").read_text())
        rows = _read_trace(raw / "capture/trace.jsonl")
        json.loads((raw / "private/semantic_evidence.json").read_text())
        interposer_stats = json.loads((raw / "private/interposer_stats.json").read_text())
        if planned["variant"] != scheduled["variant"] or planned["repeat_index"] != scheduled["repeat_index"]:
            raise SystemExit(f"schedule/plan mismatch for {run_id}")
        source_commits.add(planned["source_commit"])
        implementation_hashes.add(planned["fault_implementation_sha256"])
        infrastructure = _infrastructure_checks(finished, summary, rows)
        failure_onset, failure_rule = _failure_onset(rows)
        if planned["fault_binding"] == "semantic_interposer":
            activation, activation_detail = _semantic_mechanism_activation(interposer_stats)
            private_config = json.loads((raw / "private/interposer.json").read_text())
            binding_confirmed = (
                private_config.get("fault_id") == "planning_unsafe_cost_or_speed_bias"
                and private_config.get("dose") == {"time_scale": 0.6}
            )
        else:
            activation, activation_detail = _overlay_mechanism_activation(rows)
            binding_confirmed = (
                planned["applied_overlay_sha256"]
                == planned["fault_implementation_sha256"]
            )
        mechanism_confirmed = (
            scheduled["variant"] == "faulty"
            and binding_confirmed
            and activation is not None
        )
        private_evidence = {
            "schema_version": 1,
            "run_id": run_id,
            "variant": scheduled["variant"],
            "repeat_index": scheduled["repeat_index"],
            "infrastructure_checks": infrastructure,
            "infrastructure_valid": all(infrastructure.values()),
            "task_failure": failure_onset is not None,
            "failure_onset_s": failure_onset,
            "failure_rule": failure_rule,
            "mechanism_confirmed": mechanism_confirmed,
            "mechanism_activated_at_s": activation,
            "mechanism_detail": activation_detail,
            "minimum_ttc_s": min(
                (float(row["geometry"]["production_ttc_s"]) for row in rows
                 if row["geometry"].get("production_ttc_s") is not None),
                default=None,
            ),
            "minimum_obb_separation_m": min(
                float(row["geometry"]["current_obb_separation_m"]) for row in rows
            ),
            "source_commit": planned["source_commit"],
            "fault_binding": planned["fault_binding"],
            "applied_overlay_sha256": planned["applied_overlay_sha256"],
            "applied_fault_config_sha256": planned["applied_fault_config_sha256"],
        }
        private_path = args.state_root / "evidence/runs" / f"{run_id}.json"
        _atomic(private_path, private_evidence)
        evidence_sha = _sha_bytes(_canonical_bytes(private_evidence))
        common = {
            "run_id": run_id,
            "infrastructure_valid": private_evidence["infrastructure_valid"],
            "task_failure": private_evidence["task_failure"],
            "oracle_hidden_from_diagnosis": True,
            "evidence_sha256": evidence_sha,
        }
        if scheduled["variant"] == "reference":
            reference_runs.append(common)
        else:
            faulty_runs.append({
                **common,
                "mechanism_confirmed": mechanism_confirmed,
                "mechanism_activated_at_s": activation,
                "failure_onset_s": failure_onset,
            })
        _atomic(args.visible_root / run_id / "observation_manifest.json", {
            "schema_version": 1,
            "run_id": run_id,
            "source_commit": planned["source_commit"],
            "available_channels": ["localization", "planning", "control"],
        }, mode=0o644)

    if len(source_commits) != 1 or len(implementation_hashes) != 1:
        raise SystemExit("companion runs do not share one implementation commit/hash")
    leakage_hits = _scan_visible(args.visible_root)
    candidate = {
        "schema_version": 1,
        "candidate_id": schedule["candidate_id"],
        "fault_implementation_sha256": next(iter(implementation_hashes)),
        "reference_runs": sorted(reference_runs, key=lambda row: row["run_id"]),
        "faulty_runs": sorted(faulty_runs, key=lambda row: row["run_id"]),
        "visible_leakage_hits": leakage_hits,
    }
    _atomic(args.candidate_output, candidate)
    result = evaluate_candidate(candidate, AdmissionPolicy())
    result["source_commit"] = next(iter(source_commits))
    _atomic(args.admission_output, result)
    print(json.dumps({
        "benchmark_admission": result["benchmark_admission"],
        "failed_gates": result["failed_gates"],
        "visible_leakage_hits": leakage_hits,
    }, sort_keys=True))
    raise SystemExit(0 if result["benchmark_admission"] == "RETAINED_GOLD" else 1)


if __name__ == "__main__":
    main()
