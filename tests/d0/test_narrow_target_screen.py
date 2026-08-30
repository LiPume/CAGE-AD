from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ANALYZER = REPO / "scripts/d0/pr826/analyze_narrow_target_screen.py"


def test_narrow_target_analyzer_handles_null_target(tmp_path: Path) -> None:
    timeline = tmp_path / "timeline.jsonl"
    summary = tmp_path / "summary.json"
    output = tmp_path / "audit.json"
    events = [
        {"event": "observation_start", "simulation_elapsed_seconds": 10.0},
        {
            "event": "planning_raw",
            "clock_s": 10.1,
            "paths": [{"name": "candidate_path_regular/lane_change"}],
            "latest_channel_inputs": {"prediction": {"target": None}},
        },
        {
            "event": "planning_raw",
            "clock_s": 12.0,
            "paths": [{"name": "candidate_path_regular/lane_change"}],
            "latest_channel_inputs": {
                "prediction": {"target": {"trajectory_count": 1}}
            },
        },
    ]
    timeline.write_text("".join(json.dumps(event) + "\n" for event in events))
    summary.write_text(json.dumps({
        "determinism": {
            "actors_at_runtime_start": {
                "target_npc": {
                    "type_id": "vehicle.micro.microlino",
                    "bounding_box_extent": [1.10365, 0.74046, 0.688],
                }
            },
            "npc_policy": {
                "type": "CARLA_CONSTANT_LOCAL_VELOCITY_LANE_TANGENT",
                "future_ground_truth_used": False,
            },
        },
        "metrics": {"target_prediction_trajectory_coverage": 0.99},
        "samples": [{
            "elapsed_s": 1.0,
            "npc_carla_lane_id": -2,
            "npc_lane_center_distance_m": 0.9,
        }],
    }))
    subprocess.run([
        sys.executable, str(ANALYZER),
        "--timeline", str(timeline),
        "--summary", str(summary),
        "--expected-blueprint", "vehicle.micro.microlino",
        "--expected-lane-id", "-2",
        "--minimum-early-offset-m", "0.8",
        "--early-window-s", "3.5",
        "--maximum-first-lane-change-s", "3.5",
        "--output", str(output),
    ], check=True, cwd=REPO)
    audit = json.loads(output.read_text())
    assert audit["status"] == "PASS"
    assert audit["metrics"]["trajectory_lane_change_overlap_frames"] == 1
    assert audit["metrics"]["first_overlap_elapsed_s"] == 2.0
