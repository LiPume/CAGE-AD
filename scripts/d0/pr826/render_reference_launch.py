#!/usr/bin/env python3
"""Render a Town04 stock-Prediction PnC launch without changing global Apollo flags."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(content)
    os.replace(temporary, path)


def component_dag(library: str, class_name: str, name: str, config: str, flags: Path,
                  readers: str = "") -> str:
    return f'''module_config {{
  module_library: "{library}"
  components {{
    class_name: "{class_name}"
    config {{
      name: "{name}"
      config_file_path: "{config}"
      flag_file_path: "{flags}"
{readers}    }}
  }}
}}
'''


def control_timer_dag(flags: Path) -> str:
    """Render Control's timer component with an auditable absolute flag file.

    The packaged stock DAG names its flag file relatively.  In this host-mode runtime that
    relative path resolves to the installed tree even when APOLLO_CONF_PATH is prepended, so a
    configured calibration must use a run-scoped DAG as well as a run-scoped control.conf.
    """
    return f'''module_config {{
  module_library: "modules/control/control_component/libcontrol_component.so"
  timer_components {{
    class_name: "ControlComponent"
    config {{
      name: "control"
      flag_file_path: "{flags}"
      interval: 10
    }}
  }}
}}
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--map-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle_root.resolve()
    repo = args.repo_root.resolve()
    output = args.output_root.resolve()
    map_dir = args.map_dir.resolve()
    manifest = json.loads(args.manifest.read_text())
    candidate = manifest["candidate"]
    fixed = manifest["fixed_environment"]
    determinism = manifest.get("determinism_protocol", {})
    realtime_factor = float(determinism.get("bridge_realtime_factor", 1.0))
    clock_mode = determinism.get("apollo_cyber_clock_mode", "CYBER")
    if clock_mode not in ("CYBER", "MOCK"):
        raise SystemExit(f"unsupported Apollo Cyber clock mode: {clock_mode}")
    if not (map_dir / "base_map.bin").is_file():
        raise SystemExit(f"map is incomplete: {map_dir}")

    # Apollo 10 packages the LaneFollow task defaults in plugin descriptors but still probes
    # user-override paths. Empty textprotos are the stock no-op override used by the accepted
    # G0 Planning runtime; they neither tune the scenario nor change task defaults.
    stage_root = output / "apollo_conf/modules/planning/scenarios/lane_follow/conf/lane_follow_stage"
    for name in (
        "lane_change_path", "lane_follow_path", "lane_borrow_path", "fallback_path",
        "path_decider", "rule_based_stop_decider", "speed_bounds_priori_decider",
        "speed_heuristic_optimizer", "speed_decider", "speed_bounds_final_decider",
        "piecewise_jerk_speed",
    ):
        atomic_text(stage_root / f"{name}.pb.txt", "")

    atomic_text(output / "bridge_settings.yaml", f'''carla:
  host: '127.0.0.1'
  port: 2000
  timeout: 30
  passive: False
  synchronous_mode: True
  synchronous_mode_wait_for_vehicle_control_command: False
  fixed_delta_seconds: {float(fixed["fixed_delta_seconds"])}
  deterministic_reload: True
  substepping: True
  max_substep_delta_time: 0.01
  max_substeps: 10
  determinism_provenance_file: '{output.parent / "bridge_determinism.json"}'
  realtime_factor: {realtime_factor}
  register_all_sensors: False
  town: '{candidate["map"]}'
  ego_vehicle:
    role_name: ["hero", "ego_vehicle"]
  control_conversion:
    throttle_gain: 1.5
    brake_gain: 1.0
    steering_gain: 0.419643
    localization_accel_alpha: 0.15
''')
    spawn = candidate["ego_spawn_carla"]
    # Bridge object poses use Apollo's y/yaw convention and convert them back to CARLA.
    objects = {"objects": [{
        "type": fixed["ego_blueprint"],
        "id": "ego_vehicle",
        "spawn_point": {
            "x": float(spawn["x"]), "y": -float(spawn["y"]),
            "z": float(spawn["z"]) + 0.3, "roll": 0.0, "pitch": 0.0,
            "yaw": -float(spawn["yaw_deg"]),
        },
        "sensors": [],
    }]}
    atomic_text(output / "bridge_objects.json", json.dumps(objects, indent=2) + "\n")

    global_flags = output / "global_flagfile.txt"
    atomic_text(global_flags, f'''--vehicle_config_path=modules/common/data/vehicle_param.pb.txt
--log_dir=data/log
--use_navigation_mode=false
--use_sim_time=true
--use_cyber_time=true
--map_dir={map_dir}
''')

    apollo = bundle / "runtime/apollo/application-pnc/.aem/envroot/apollo"
    control_calibration_variant = candidate.get("control_calibration_variant")
    control_dag_path = "modules/control/control_component/dag/control.dag"
    if control_calibration_variant is not None:
        if control_calibration_variant != "lincoln_carla_v17_low_speed":
            raise SystemExit(
                f"unsupported Control calibration variant: {control_calibration_variant}"
            )
        calibration_source = (
            bundle / "runtime/d0_control_loop_v17_20260811/calibration_table.pb.txt"
        )
        expected_sha = candidate.get("control_calibration_sha256")
        actual_sha = hashlib.sha256(calibration_source.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise SystemExit(
                f"Control calibration checksum mismatch: {actual_sha} != {expected_sha}"
            )
        control_conf_root = (
            output / "apollo_conf/modules/control/control_component/conf"
        )
        calibration_target = control_conf_root / "calibration_table.pb.txt"
        atomic_text(calibration_target, calibration_source.read_text())
        control_conf_source = (
            apollo / "modules/control/control_component/conf/control.conf"
        )
        control_lines = [
            line for line in control_conf_source.read_text().splitlines()
            if "calibration_table_file=" not in line
        ]
        control_lines.append(f"--calibration_table_file={calibration_target}")
        generated_control_conf = control_conf_root / "control.conf"
        atomic_text(generated_control_conf, "\n".join(control_lines) + "\n")
        generated_control_dag = output / "control.dag"
        atomic_text(generated_control_dag, control_timer_dag(generated_control_conf))
        control_dag_path = str(generated_control_dag)
    cyber_source = apollo / "cyber/conf"
    cyber_root = output / "cyber"
    shutil.copytree(cyber_source, cyber_root / "conf")
    cyber_config = cyber_root / "conf/cyber.pb.conf"
    cyber_text = cyber_config.read_text()
    if clock_mode == "MOCK":
        cyber_text = cyber_text.replace("clock_mode: MODE_CYBER", "clock_mode: MODE_MOCK")
    atomic_text(cyber_config, cyber_text)
    def custom_flags(relative: str, name: str) -> Path:
        text = (apollo / relative).read_text()
        text = text.replace("--flagfile=modules/common/data/global_flagfile.txt",
                            f"--flagfile={global_flags}")
        target = output / name
        atomic_text(target, text)
        return target

    routing_flags = custom_flags("modules/routing/conf/routing.conf", "routing.conf")
    planning_flags = custom_flags(
        "modules/planning/planning_component/conf/planning.conf", "planning.conf"
    )
    planning_overrides = candidate.get("planning_overrides", {})
    allowed_planning_overrides = {"static_obstacle_speed_threshold"}
    unknown_overrides = set(planning_overrides) - allowed_planning_overrides
    if unknown_overrides:
        raise SystemExit(f"unsupported Planning overrides: {sorted(unknown_overrides)}")
    if "static_obstacle_speed_threshold" in planning_overrides:
        threshold = float(planning_overrides["static_obstacle_speed_threshold"])
        if not 0.0 < threshold <= 5.0:
            raise SystemExit("static_obstacle_speed_threshold must be in (0, 5]")
        atomic_text(
            planning_flags,
            planning_flags.read_text().rstrip() +
            f"\n--static_obstacle_speed_threshold={threshold:.6f}\n",
        )
    prediction_flags = custom_flags("modules/prediction/conf/prediction.conf", "prediction.conf")

    routing_dag = output / "routing.dag"
    atomic_text(routing_dag, component_dag(
        "modules/routing/librouting_component.so", "RoutingComponent", "routing",
        "modules/routing/conf/routing_config.pb.txt", routing_flags,
        '''      readers: [{
        channel: "/apollo/raw_routing_request"
        qos_profile: { depth: 10 }
      }]
'''))
    old_adapter_dag = output / "old_routing_adapter.dag"
    atomic_text(old_adapter_dag, component_dag(
        "modules/external_command/old_routing_adapter/libold_routing_adapter.so",
        "OldRoutingAdapter", "old_routing_adapter",
        "modules/external_command/old_routing_adapter/conf/config.pb.txt", global_flags
    ))
    external_dag = output / "external_command_process.dag"
    atomic_text(external_dag, component_dag(
        "modules/external_command/process_component/libexternal_command_process_component.so",
        "ExternalCommandProcessComponent", "external_command_process",
        "modules/external_command/process_component/conf/config.pb.txt", global_flags
    ))
    prediction_dag = output / "prediction.dag"
    atomic_text(prediction_dag, component_dag(
        "modules/prediction/libprediction_component.so", "PredictionComponent", "prediction",
        "modules/prediction/conf/prediction_conf.pb.txt", prediction_flags,
        '''      readers: [{
        channel: "/apollo/perception/obstacles"
        qos_profile: { depth: 1 }
      }]
'''))
    planning_dag = output / "planning.dag"
    atomic_text(planning_dag, component_dag(
        "modules/planning/planning_component/libplanning_component.so",
        "PlanningComponent", "planning",
        str(repo / "deploy/autodl_apollo10/d0_planning_config.pb.txt"), planning_flags,
        '''      readers: [
        { channel: "/apollo/prediction" },
        { channel: "/apollo/canbus/chassis" qos_profile: { depth: 15 } pending_queue_size: 50 },
        { channel: "/apollo/localization/pose" qos_profile: { depth: 15 } pending_queue_size: 50 }
      ]
'''))
    launch = output / "reference_pnc.launch"
    atomic_text(launch, f'''<cyber>
  <module><name>routing</name><dag_conf>{routing_dag}</dag_conf><process_name>routing</process_name></module>
  <module><name>old_routing_adapter</name><dag_conf>{old_adapter_dag}</dag_conf><process_name>old_routing_adapter</process_name></module>
  <module><name>prediction</name><dag_conf>{prediction_dag}</dag_conf><process_name>prediction</process_name></module>
  <module><name>planning</name><dag_conf>{external_dag}</dag_conf><dag_conf>{planning_dag}</dag_conf><process_name>planning</process_name></module>
  <module><name>control</name><dag_conf>{control_dag_path}</dag_conf><process_name>control</process_name></module>
</cyber>
''')
    print(launch)


if __name__ == "__main__":
    main()
