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


def test_v6_loader_is_one_shot_actor_free_and_offscreen() -> None:
    launcher = (REPO_ROOT / "scripts/g0/start_carla_offscreen.sh").read_text()
    loader = (REPO_ROOT / "scripts/d0/repair/load_carla_world_once.py").read_text()

    assert "-RenderOffScreen" in launcher
    assert loader.count('client.load_world("Town01")') == 1
    assert "spawn_actor" not in loader
    assert "try_spawn_actor" not in loader
    assert '"load_world_calls": 1' in loader


def test_v6_smoke_loads_town01_before_bridge_and_keeps_steering_only() -> None:
    wrapper = (REPO_ROOT / "scripts/d0/repair/run_execution_smoke_once.sh").read_text()
    loader_call = wrapper.index("load_carla_world_once.py")
    bridge_call = wrapper.index("manage_carla_bridge.sh\" start")
    patch = (
        REPO_ROOT / "third_party/patches/carla_apollo_bridge_steering_v3.patch"
    ).read_text()

    assert loader_call < bridge_call
    assert "steering_gain: 0.419643" in patch
    assert "throttle_gain: 1.910828" not in patch
    assert "localization_accel_alpha: 1.0" not in patch


def test_v7_patch_changes_only_the_frozen_acceleration_alpha() -> None:
    patch = (
        REPO_ROOT / "third_party/patches/carla_apollo_bridge_accel_filter_v7.patch"
    ).read_text()

    assert "localization_accel_alpha: 0.15" in patch
    assert "throttle_gain: 1.5" in patch
    assert "brake_gain: 1.0" in patch
    assert "steering_gain: 0.419643" in patch
    assert "throttle_gain: 1.910828" not in patch
    assert "localization_accel_alpha: 1.0" not in patch


def test_v8_throttle_characterization_is_frozen_and_actor_isolated() -> None:
    source = (
        REPO_ROOT / "scripts/d0/repair/carla_lincoln_throttle_characterization.py"
    ).read_text()

    assert "LEVELS = (0.15, 0.20, 0.2355, 0.30, 0.40)" in source
    assert "for step in range(160)" in source
    assert "CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET" in source
    assert "requires zero vehicles" in source
    assert "world.apply_settings(old_settings)" in source
    assert "endpoint_speed_strictly_monotonic" in source


def test_v9_actual_gear_observation_is_non_behavioral() -> None:
    patch = (
        REPO_ROOT / "third_party/patches/carla_bridge_actual_gear_telemetry_v9.patch"
    ).read_text()
    runtime = (
        REPO_ROOT / "src/cage_ad/adapters/apollo_d0/execution_smoke_runtime.py"
    ).read_text()

    assert "actual_gear" in patch
    assert "actual_manual_gear_shift" in patch
    assert "manual_gear_shift =" not in patch
    assert "vehicle_control.gear =" not in patch
    assert '"carla_actual_gear_zero_frames"' in runtime
    assert '"apollo_drive_but_carla_not_gear_one_frames"' in runtime


def test_v10_actual_gear_feedback_patch_changes_feedback_only() -> None:
    patch = (
        REPO_ROOT / "third_party/patches/carla_bridge_actual_gear_feedback_v10.patch"
    ).read_text()
    verifier = (
        REPO_ROOT / "scripts/d0/repair/verify_bridge_gear_mapping.py"
    ).read_text()
    runtime = (
        REPO_ROOT / "src/cage_ad/adapters/apollo_d0/execution_smoke_runtime.py"
    ).read_text()

    assert "carla_control.gear == 0" in patch
    assert "GEAR_NEUTRAL" in patch
    assert "carla_control.gear < 0" in patch
    assert "apply_control" not in patch
    assert "manual_gear_shift =" not in patch
    assert '"neutral": _published_gear(neutral)' in verifier
    assert '"actual_gear_feedback_mismatch_frames"' in runtime


def test_v11_paired_gear_telemetry_is_observation_only() -> None:
    patch = (
        REPO_ROOT / "third_party/patches/carla_bridge_paired_gear_telemetry_v11.patch"
    ).read_text()
    summarizer = (
        REPO_ROOT / "scripts/d0/repair/summarize_paired_gear_feedback.py"
    ).read_text()

    assert '"record_type": "chassis_feedback"' in patch
    assert '"carla_actual"' in patch
    assert '"apollo_published"' in patch
    assert "apply_control(" not in patch
    assert "manual_gear_shift =" not in patch
    assert '"mapping_mismatch_records"' in summarizer
    assert '"false_drive_feedback_records"' in summarizer


def test_v12_longitudinal_audit_is_read_only_and_checks_frozen_gain() -> None:
    source = (
        REPO_ROOT / "scripts/d0/repair/analyze_longitudinal_chain.py"
    ).read_text()

    assert '"OFFLINE_CONTROL_LOOP_AUDIT_NOT_DATASET"' in source
    assert '"expected_gain": 1.5' in source
    assert '"positive_acceleration_lookup_with_negative_calibration_frames"' in source
    assert "apply_control(" not in source
    assert "carla.Client(" not in source


def test_v13_calibration_uses_common_gear_one_precondition() -> None:
    source = (
        REPO_ROOT / "scripts/d0/repair/carla_gear_one_conditioned_calibration.py"
    ).read_text()

    assert "LEVELS = (0.20, 0.2355, 0.2575, 0.30, 0.35, 0.40, 0.50)" in source
    assert "REPEATS = 3" in source
    assert "PRECONDITION_THROTTLE = 0.40" in source
    assert "control.gear == 1 and speed(actor) >= 1.0" in source
    assert '"all_start_speeds_in_range"' in source
    assert '"repeat_speed_slope_ranges_at_most_0_20"' in source
    assert '"CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET"' in source
    assert "manual_gear_shift =" not in source
    assert "apply_physics_control" not in source


def test_v14_uses_frozen_ordinary_least_squares_speed_slope() -> None:
    source = (
        REPO_ROOT / "scripts/d0/repair/carla_gear_one_conditioned_calibration.py"
    ).read_text()

    assert "def speed_slope(rows: list[dict]) -> float:" in source
    assert "(sample_time - mean_time) * (sample_speed - mean_speed)" in source
    assert '"evaluation_speed_slope_mps2"' in source
    assert '"speed_slope_nondecreasing_with_0_05_tolerance"' in source


def test_v15_candidate_is_low_speed_positive_and_reversible() -> None:
    generator = (
        REPO_ROOT / "scripts/d0/repair/generate_v15_candidate_table.py"
    ).read_text()
    prepare = (REPO_ROOT / "scripts/d0/repair/prepare_execution_smoke.py").read_text()

    assert "LOW_SPEED_MAX_MPS = 1.2" in generator
    assert "entry[\"speed\"] > LOW_SPEED_MAX_MPS or entry[\"acceleration\"] < 0.0" in generator
    assert '"all_negative_entries_preserved"' in generator
    assert '"all_high_speed_entries_preserved"' in generator
    assert "33.333333333333336" in generator
    assert "CAGE_APOLLO_CALIBRATION_OVERRIDE" in prepare
    assert "calibration_table.pb.txt" in prepare


def test_v15_loader_uses_run_specific_control_flag_and_dag() -> None:
    prepare = (REPO_ROOT / "scripts/d0/repair/prepare_execution_smoke.py").read_text()
    renderer = (REPO_ROOT / "scripts/d0/render_apollo_runtime.py").read_text()
    wrapper = (REPO_ROOT / "scripts/d0/repair/run_execution_smoke_once.sh").read_text()
    template = (REPO_ROOT / "deploy/autodl_apollo10/d0_pnc.launch.in").read_text()

    assert "--calibration_table_file=" in prepare
    assert 'line.lstrip("-").startswith("calibration_table_file=")' in prepare
    assert "--control-flag-file" in renderer
    assert 'flag_file_path: "{control_flag_file}"' in renderer
    assert "__CAGE_CONTROL_DAG__" in template
    assert "CONTROL_RENDER_ARGS" in wrapper


def test_v16_calibration_freezes_three_start_speeds() -> None:
    source = (REPO_ROOT / "scripts/d0/repair/carla_multi_speed_calibration.py").read_text()

    assert "TARGET_SPEEDS = (1.0, 1.5, 2.0)" in source
    assert "LEVELS = (0.30, 0.35, 0.40, 0.45, 0.50)" in source
    assert "REPEATS = 3" in source
    assert "PRECONDITION_THROTTLE = 0.50" in source
    assert "def speed_slope(rows: list[dict]) -> float:" in source
    assert '"all_45_samples_present"' in source
    assert '"CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET"' in source
    assert "manual_gear_shift =" not in source
    assert "apply_physics_control" not in source


def test_v16a_full_throttle_audit_is_read_only_and_preregistered() -> None:
    source = (
        REPO_ROOT / "scripts/d0/repair/carla_full_throttle_physics_audit.py"
    ).read_text()

    assert "MEASUREMENT_STEPS = 200" in source
    assert "REQUESTED_THROTTLE = 1.0" in source
    assert "HEALTHY_FINAL_SPEED_MPS = 10.0" in source
    assert "DEFINITELY_WEAK_FINAL_SPEED_MPS = 3.0" in source
    assert '"use_sweep_wheel_collision"' in source
    assert '"damping_rate_zero_throttle_clutch_engaged"' in source
    assert '"requested_control"' in source
    assert '"actual_control"' in source
    assert '"CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET"' in source
    assert "apply_physics_control" not in source
    assert "set_autopilot" not in source
    assert "enable_constant_velocity" not in source
    assert "set_target_velocity" not in source


def test_v17_candidate_inverts_frozen_multi_speed_responses() -> None:
    source = (REPO_ROOT / "scripts/d0/repair/generate_v17_candidate_table.py").read_text()

    assert "SPEED_MAX_MPS = 2.0" in source
    assert "SPEED_ANCHORS = (1.0, 1.5, 2.0)" in source
    assert "CARLA_THROTTLES = (0.30, 0.35, 0.40, 0.45, 0.50)" in source
    assert "def inverse_command(speed: float, acceleration: float) -> float:" in source
    assert '"all_negative_entries_preserved"' in source
    assert '"all_high_speed_entries_preserved"' in source


def test_v17_evaluator_uses_frozen_contract_and_is_offline() -> None:
    source = (REPO_ROOT / "scripts/d0/repair/evaluate_v17_candidate.py").read_text()

    assert '"tracking_ratio_at_least_0_70"' in source
    assert '"max_lateral_deviation_at_most_0_20_m"' in source
    assert '"carla_throttle_at_most_0_50"' in source
    assert '"false_drive_feedback_zero"' in source
    assert '"candidate_internal_lookup_active"' in source
    assert '"legacy_only_failed_check"' in source
    assert "carla.Client(" not in source
    assert "apply_control(" not in source


def test_v18_diagnostic_binds_v17_table_without_touching_install_tree() -> None:
    prepare = (REPO_ROOT / "scripts/d0/diagnostics/prepare_ttc_diagnostic.py").read_text()
    wrapper = (REPO_ROOT / "scripts/d0/diagnostics/run_ttc_diagnostic_once.sh").read_text()

    assert "--expected-calibration-sha256" in prepare
    assert "--calibration_table_file=" in prepare
    assert 'line.lstrip("-").startswith("calibration_table_file=")' in prepare
    assert "apollo_conf_manifest.json" in prepare
    assert "--control-flag-file" in wrapper
    assert "APOLLO_CONF_PATH" in wrapper
    assert wrapper.index("load_carla_world_once.py") < wrapper.index('manage_carla_bridge.sh" start')
    assert "CAGE_BRIDGE_CONTROL_TELEMETRY" in wrapper


def test_v18_evaluator_freezes_interaction_and_ttc_gates_offline() -> None:
    source = (
        REPO_ROOT / "scripts/d0/diagnostics/evaluate_v18_interaction_smoke.py"
    ).read_text()

    assert '"production_ttc_is_not_all_null"' in source
    assert '"independent_ttc_is_not_all_null"' in source
    assert '"production_ttc_enters_2_5_to_6_second_band"' in source
    assert '"ego_pre_conflict_speed_median_at_least_1_8_mps"' in source
    assert '"frozen_v17_table_is_bound_to_run"' in source
    assert '"apollo_conf/modules/control/control_component/conf/calibration_table.pb.txt"' in source
    assert "carla.Client(" not in source
    assert "apply_control(" not in source
