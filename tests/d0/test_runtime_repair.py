from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_preflight_module():
    path = REPO_ROOT / "scripts/d0/repair/preflight_apollo10_planning.py"
    spec = importlib.util.spec_from_file_location("planning_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_plugin(neo_root: Path, task_name: str, *, default_config: bool = True) -> None:
    task_root = neo_root / "share/modules/planning/tasks" / task_name.lower()
    task_root.mkdir(parents=True)
    (task_root / "plugins.xml").write_text(
        f'<library path="lib{task_name}.so">'
        f'<class type="apollo::planning::{task_name}" />'
        "</library>\n"
    )
    (neo_root / "lib").mkdir(exist_ok=True)
    (neo_root / "lib" / f"lib{task_name}.so").write_bytes(b"fixture")
    if default_config:
        (task_root / "conf").mkdir()
        (task_root / "conf/default_conf.pb.txt").write_text("# fixture\n")


def test_planning_preflight_accepts_plugin_defaults_without_stage_overrides(tmp_path: Path) -> None:
    neo_root = tmp_path / "neo"
    pipeline = neo_root / "share/modules/planning/scenarios/lane_follow/conf/pipeline.pb.txt"
    pipeline.parent.mkdir(parents=True)
    pipeline.write_text(
        'stage { task { type: "PathBoundsDecider" } }\n'
        '# task { type: "CommentedOutTask" }\n'
    )
    _write_plugin(neo_root, "PathBoundsDecider")
    _write_plugin(neo_root, "FastStopTrajectoryFallback", default_config=False)

    result = _load_preflight_module().inspect(neo_root)

    assert result["result"] == "PASS"
    assert result["task_count"] == 2
    assert result["stage_custom_config_dir_exists"] is False
    assert "optional user overrides" in result["interpretation"]


def test_runtime_repair_patch_is_source_only_and_maps_all_gears() -> None:
    patch_path = REPO_ROOT / "third_party/patches/carla_apollo_bridge_d0_runtime_repair.patch"
    patch = patch_path.read_text()

    assert "GEAR_DRIVE" in patch
    assert "GEAR_REVERSE" in patch
    assert "GEAR_PARKING" in patch
    assert "runtime_state" not in patch
    assert "private_oracle" not in patch


def test_execution_smoke_evaluator_applies_frozen_gate(tmp_path: Path) -> None:
    summary = {
        "non_unit_frame_gaps": 0,
        "sim_duration_s": 19.95,
        "npc_vehicle_count": 0,
        "route": {"route_accepted": True},
        "drive_gear_mismatch_frames": 3,
        "valid_trajectory_frame_coverage": 0.95,
        "control_topic": "/apollo/control_guarded",
        "tracking_window": {"passed": True},
        "progress_m": 10.0,
    }
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary))
    heartbeat_path = tmp_path / "heartbeat.json"
    heartbeat_path.write_text(json.dumps({"label": "RUNTIME_REPAIR_SMOKE_NOT_DATASET"}))
    stack_path = tmp_path / "stack.log"
    stack_path.write_text("healthy\n")
    output = tmp_path / "result.json"
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/d0/repair/evaluate_execution_smoke.py"),
        "--run-id", "NO_NPC_FIXTURE",
        "--runtime-summary", str(summary_path),
        "--stack-log", str(stack_path),
        "--empty-road-stats", str(heartbeat_path),
        "--runtime-exit", "0",
        "--powered-on-seconds", "1.0",
        "--source-commit", "fixture",
        "--output", str(output),
    ]

    completed = subprocess.run(command, check=False)

    assert completed.returncode == 0
    assert json.loads(output.read_text())["result"] == "PASS"

    stack_path.write_text("lane_follow_stage/path_decider.pb.txt is not found\n")
    completed = subprocess.run(command, check=False)
    result = json.loads(output.read_text())
    assert completed.returncode == 2
    assert result["result"] == "FAIL"
    assert result["checks"]["no_lane_follow_config_missing"] is False
