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
    interposer_path = tmp_path / "interposer.json"
    interposer_path.write_text(
        json.dumps({"injector_exception": None, "prediction_in": 20, "prediction_out": 20})
    )
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
        "--interposer-stats", str(interposer_path),
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


def test_execution_smoke_prepare_materializes_noop_overrides(tmp_path: Path) -> None:
    run_state = tmp_path / "state"
    run_data = tmp_path / "data"
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/d0/repair/prepare_execution_smoke.py"),
        "--repo-root", str(REPO_ROOT),
        "--run-id", "NO_NPC_FIXTURE",
        "--run-state", str(run_state),
        "--run-data", str(run_data),
    ]

    completed = subprocess.run(command, check=False)

    assert completed.returncode == 0
    planned = json.loads((run_state / "planned.json").read_text())
    assert planned["interaction_actor"] is False
    assert planned["fault_id"] is None
    stage_root = run_data / "apollo_conf/modules/planning/scenarios/lane_follow/conf/lane_follow_stage"
    overrides = sorted(stage_root.glob("*.pb.txt"))
    assert len(overrides) == 11
    assert all(path.read_bytes() == b"" for path in overrides)


def test_execution_smoke_does_not_compare_wall_header_to_carla_clock_for_coverage() -> None:
    source = (
        REPO_ROOT / "src/cage_ad/adapters/apollo_d0/execution_smoke_runtime.py"
    ).read_text()

    assert '"valid_trajectory_frame_coverage": sum(row["valid_planning_available"]' in source
    assert '"planning_header_carla_clock_match_fraction"' in source


def test_control_loop_instrumentation_captures_all_eight_signal_groups() -> None:
    source = (
        REPO_ROOT / "src/cage_ad/adapters/apollo_d0/execution_smoke_runtime.py"
    ).read_text()

    for required in (
        '"target_speed_1s_mps"',
        '"target_acceleration_1s_mps2"',
        '"throttle_percentage"',
        '"brake_percentage"',
        '"gear_location"',
        '"simple_lon_debug"',
        '"longitudinal_mps2"',
        '"linear_acceleration_vrf"',
        '"vehicle_physics"',
    ):
        assert required in source


def test_bridge_control_telemetry_is_opt_in_and_source_only() -> None:
    bridge = Path(
        "/root/autodl_apollo10_g0_bundle/runtime/bridge/apollo-carla/"
        "carla_bridge/actor/ego_vehicle.py"
    ).read_text()
    launcher = (REPO_ROOT / "scripts/g0/manage_carla_bridge.sh").read_text()
    wrapper = (REPO_ROOT / "scripts/d0/repair/run_execution_smoke_once.sh").read_text()

    assert 'os.environ.get("CAGE_BRIDGE_CONTROL_TELEMETRY", "")' in bridge
    assert '"apollo_header_sequence_num"' in bridge
    assert '"carla_applied"' in bridge
    assert "CAGE_BRIDGE_CONTROL_TELEMETRY" in launcher
    assert "BRIDGE_CONTROL_TELEMETRY" in wrapper


def test_carla_step_response_is_isolated_and_keeps_frozen_reference_command() -> None:
    source = (REPO_ROOT / "scripts/d0/repair/carla_lincoln_step_response.py").read_text()

    assert '"CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET"' in source
    assert '"throttle": 0.2355' in source
    assert '"vehicle.lincoln.mkz_2017"' in source
    assert "requires zero existing vehicles" in source
    assert "world.apply_settings(old_settings)" in source


def test_lincoln_mapping_v2_values_are_evidence_derived_and_source_only() -> None:
    patch = (
        REPO_ROOT / "third_party/patches/carla_apollo_bridge_lincoln_mapping_v2.patch"
    ).read_text()

    assert "throttle_gain: 1.910828" in patch
    assert "steering_gain: 0.419643" in patch
    assert "localization_accel_alpha: 1.0" in patch
    assert "soft_estop_brake" not in patch
    assert "runtime_state" not in patch
    assert "private_oracle" not in patch


def test_v3_brake_response_is_isolated_and_preregistered() -> None:
    source = (REPO_ROOT / "scripts/d0/repair/carla_lincoln_brake_response.py").read_text()

    assert '"CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET"' in source
    assert "for brake in (0.00, 0.03, 0.05, 0.10, 0.15)" in source
    assert "isolated brake response requires zero vehicles" in source
    assert "world.apply_settings(old_settings)" in source
    assert "settings.fixed_delta_seconds = 0.05" in source
    assert "max_substep_delta_time" in source


def test_v3_steering_patch_changes_only_the_frozen_steering_mapping() -> None:
    patch = (
        REPO_ROOT / "third_party/patches/carla_apollo_bridge_steering_v3.patch"
    ).read_text()

    assert "steering_gain: 0.419643" in patch
    assert 'steering_gain = conversion.get("steering_gain")' in patch
    assert "throttle_gain: 1.910828" not in patch
    assert "localization_accel_alpha: 1.0" not in patch
    assert "soft_estop_brake" not in patch
    assert "private_oracle" not in patch


def test_source_checkpoint_launcher_does_not_depend_on_old_project() -> None:
    source_launcher = (REPO_ROOT / "scripts/g0/start_carla_offscreen.sh").read_text()

    assert '${CARLA_ROOT}/CarlaUE4.sh' in source_launcher
    assert "Zhijia-Guardian" not in source_launcher
