from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ANALYZER = REPO / "scripts/d0/pr826/analyze_scene_fault_compatibility.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def prediction(sequence: int, clock: float, terminal_x: float) -> dict:
    return {
        "event": "prediction",
        "clock_s": clock,
        "header": {"sequence_num": sequence},
        "target": {
            "trajectories": [
                {
                    "first_point": {"x": 9.0},
                    "last_point": {"x": terminal_x},
                }
            ]
        },
    }


def test_scene_fault_compatibility_detects_temporal_mismatch(tmp_path: Path) -> None:
    fixed = tmp_path / "fixed.jsonl"
    active = tmp_path / "active.jsonl"
    summary = tmp_path / "summary.json"
    output = tmp_path / "audit.json"
    write_jsonl(fixed, [prediction(1, 10.0, 8.8)])
    write_jsonl(
        active,
        [
            {"event": "observation_start", "simulation_elapsed_seconds": 10.0},
            prediction(1, 10.0, 5.5),
            {
                "event": "planning_raw",
                "clock_s": 10.05,
                "embedded_inputs": {"prediction_header": {"sequence_num": 1}},
                "init_point": {"v": 0.1},
                "trajectory": {
                    "main_decision_fields": ["cruise"],
                    "total_path_length": 5.0,
                },
                "paths": [{"name": "candidate_path_regular/self"}],
                "target_obstacle_debug": [],
            },
            {
                "event": "planning_raw",
                "clock_s": 12.0,
                "embedded_inputs": {"prediction_header": {"sequence_num": 2}},
                "init_point": {"v": 1.0},
                "trajectory": {
                    "main_decision_fields": ["cruise"],
                    "total_path_length": 8.0,
                },
                "paths": [{"name": "candidate_path_regular/lane_change"}],
                "target_obstacle_debug": [],
            },
        ],
    )
    summary.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "elapsed_s": 0.0,
                        "ego_speed_mps": 0.1,
                        "carla_lane_id": -2,
                        "ego_lateral_m": 0.0,
                    },
                    {
                        "elapsed_s": 5.0,
                        "ego_speed_mps": 2.0,
                        "carla_lane_id": -1,
                        "ego_lateral_m": 3.5,
                    },
                ]
            }
        )
    )
    subprocess.run(
        [
            sys.executable,
            str(ANALYZER),
            "--fixed-timeline",
            str(fixed),
            "--active-timeline",
            str(active),
            "--active-summary",
            str(summary),
            "--output",
            str(output),
        ],
        check=True,
        cwd=REPO,
    )
    audit = json.loads(output.read_text())
    assert audit["classification"] == "TEMPORAL_AND_SELECTED_PATH_MISMATCH"
    assert audit["altered_output_signature"]["fixed"]["altered_signature_frames"] == 0
    assert audit["altered_output_signature"]["active"]["altered_signature_frames"] == 1
    assert audit["planning_consumption"]["altered_sequences_consumed"] == 1
    assert audit["vehicle_overlap_window"]["first_lane_change_path_elapsed_s"] == 2.0
    assert audit["vehicle_overlap_window"]["last_altered_output_to_lane_change_path_gap_s"] == 2.0
    assert audit["vehicle_overlap_window"]["last_altered_output_to_lane_entry_gap_s"] == 5.0
