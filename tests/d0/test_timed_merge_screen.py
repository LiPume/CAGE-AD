from __future__ import annotations

import json, subprocess, sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ANALYZER = REPO / "scripts/d0/pr826/analyze_timed_merge_screen.py"


def test_timed_merge_gate(tmp_path: Path) -> None:
    timeline, summary, output = (tmp_path / name for name in ("t.jsonl", "s.json", "a.json"))
    events = [{"event": "observation_start", "simulation_elapsed_seconds": 10.0}]
    events += [{"event": "planning_raw", "clock_s": 18.0 + i / 10, "paths": [{"name": "candidate_path_regular/lane_change"}], "latest_channel_inputs": {"prediction": {"target": {"trajectory_count": 1}}}} for i in range(10)]
    timeline.write_text("".join(json.dumps(e) + "\n" for e in events))
    summary.write_text(json.dumps({"determinism": {"npc_policy": {"type": "CARLA_TIMED_ADJACENT_LANE_MERGE_LOCAL_VELOCITY", "release_trigger": "SIMULATION_ELAPSED_SINCE_OBSERVATION_START", "apollo_output_used": False, "ego_state_used": False, "future_ground_truth_used": False}}, "metrics": {"target_prediction_trajectory_coverage": 0.99}, "samples": [{"elapsed_s": 1.0, "npc_carla_lane_id": -3, "npc_speed_mps": 1.1}, {"elapsed_s": 9.0, "npc_carla_lane_id": -2, "npc_speed_mps": 1.1}] }))
    subprocess.run([sys.executable, str(ANALYZER), "--timeline", str(timeline), "--summary", str(summary), "--source-lane=-3", "--target-lane=-2", "--merge-start-s", "6", "--merge-end-s", "8", "--minimum-post-merge-overlap-frames", "10", "--output", str(output)], check=True, cwd=REPO)
    assert json.loads(output.read_text())["status"] == "PASS"
