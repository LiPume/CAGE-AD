#!/usr/bin/env python3
"""Prepare one private, immutable companion run for the first gold candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import yaml

from cage_ad.protocol_v1.loader import load_protocol
from cage_ad.protocol_v1.scenario import scenario_candidate_by_id


STAGE_OVERRIDE_NAMES = (
    "lane_change_path", "lane_follow_path", "lane_borrow_path", "fallback_path",
    "path_decider", "rule_based_stop_decider", "speed_bounds_priori_decider",
    "speed_heuristic_optimizer", "speed_decider", "speed_bounds_final_decider",
    "piecewise_jerk_speed",
)
FAULT_OVERLAY = "follow_min_time_sec: 0.1\n"
CALIBRATION_SHA256 = "2693818651d7799eac5f206b88af0c0fb86f38b34443c1b14b4ccd45ffe482aa"


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _atomic_text(path: Path, value: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(value)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: dict, mode: int = 0o600) -> None:
    _atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n", mode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--candidate-contract", type=Path, required=True)
    parser.add_argument("--calibration-table", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--variant", choices=("reference", "faulty"), required=True)
    parser.add_argument("--repeat-index", type=int, choices=(0, 1, 2), required=True)
    args = parser.parse_args()

    if not re.fullmatch(r"hgv1-[0-9a-f]{8}", args.run_id):
        raise SystemExit("run ID must be an opaque hgv1-XXXXXXXX identifier")
    if not _inside(args.raw_root, args.runtime_root / "raw"):
        raise SystemExit("raw root must be under runtime/raw")
    if _inside(args.raw_root, args.runtime_root / "runs"):
        raise SystemExit("private raw data cannot be diagnosis-visible")
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=args.repo_root, check=True,
        text=True, capture_output=True,
    ).stdout
    if status:
        raise SystemExit("repository must be clean before freezing a run")
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=args.repo_root, check=True,
        text=True, capture_output=True,
    ).stdout.strip()

    contract = yaml.safe_load(args.candidate_contract.read_text())
    if contract["candidate_id"] != "HGV1-P01-LBC0":
        raise SystemExit("unsupported gold candidate contract")
    if contract["scene"] != {
        "scenario_id": "lead_brake_close",
        "candidate_id": "LBC0",
        "seed": 1101,
        "repeat_order": [0, 1, 2],
        "source": "benchmarks/apollo_d0/protocol_v1/scenario_recipes.yaml",
    }:
        raise SystemExit("scene contract changed after pre-registration")
    fault = contract["fault"]
    expected_fault = {
        "responsibility_domain": "motion_planning",
        "mechanism_family": "incorrect_threshold_value",
        "native_component": "speed_decider",
        "semantic_source_config": "modules/planning/tasks/speed_decider/conf/default_conf.pb.txt",
        "runtime_overlay_config": "modules/planning/scenarios/lane_follow/conf/lane_follow_stage/speed_decider.pb.txt",
        "field": "follow_min_time_sec",
        "reference_value": 2.0,
        "faulty_value": 0.1,
        "mutation_scope": "run_scoped_APOLLO_CONF_PATH_overlay",
        "forbidden_changes": [
            "stop_follow_distance", "follow_distance_scheduler", "scenario_parameters",
            "bridge_calibration", "failure_oracle",
        ],
    }
    if fault != expected_fault:
        raise SystemExit("fault contract changed after pre-registration")

    bundle = load_protocol(args.repo_root)
    candidate = scenario_candidate_by_id(bundle, "lead_brake_close", "LBC0")
    calibration = args.calibration_table.resolve()
    if _sha(calibration) != CALIBRATION_SHA256:
        raise SystemExit("frozen V17 control calibration SHA256 mismatch")
    vendor_default = (
        args.runtime_root / "apollo/application-pnc/.aem/envroot/apollo/"
        "modules/planning/tasks/speed_decider/conf/default_conf.pb.txt"
    )
    vendor_text = vendor_default.read_text()
    if not re.search(r"(?m)^follow_min_time_sec:\s*2(?:\.0+)?\s*$", vendor_text):
        raise SystemExit("Apollo vendor follow_min_time_sec default is not 2.0")

    run_state = args.state_root / "runs" / args.run_id
    raw_run = args.raw_root / args.run_id
    private = raw_run / "private"
    capture = raw_run / "capture"
    apollo_conf = raw_run / "apollo_conf"
    if (run_state / "finished.json").exists():
        raise SystemExit("run already finished")

    scenario = {
        "protocol_version": bundle.episodes["protocol_version"],
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "scenario_id": "lead_brake_close",
        "candidate_id": "LBC0",
        "seed": 1101,
    }
    interposer = {
        **scenario,
        "fault_id": None,
        "dose": None,
        "probe_domain": None,
        "trigger_window": list(candidate.trigger_window),
    }
    capture_config = {
        **scenario,
        "run_id": args.run_id,
        "duration_s": 32.0,
        "capture_purpose": "benchmark_construction",
        "benchmark_construction_candidate": True,
        "source_commit": source_commit,
        "calibration_table_sha256": CALIBRATION_SHA256,
    }

    stage_root = apollo_conf / "modules/planning/scenarios/lane_follow/conf/lane_follow_stage"
    for name in STAGE_OVERRIDE_NAMES:
        content = FAULT_OVERLAY if name == "speed_decider" and args.variant == "faulty" else ""
        _atomic_text(stage_root / f"{name}.pb.txt", content)
    destination = apollo_conf / "modules/control/control_component/conf/calibration_table.pb.txt"
    _atomic_text(destination, calibration.read_text())
    base_flags = (
        args.runtime_root / "apollo/application-pnc/.aem/envroot/opt/apollo/neo/share/"
        "modules/control/control_component/conf/control.conf"
    )
    filtered_flags = [
        line for line in base_flags.read_text().splitlines()
        if not line.lstrip("-").startswith("calibration_table_file=")
    ]
    filtered_flags.append(f"--calibration_table_file={destination.resolve()}")
    _atomic_text(
        apollo_conf / "modules/control/control_component/conf/control.conf",
        "\n".join(filtered_flags) + "\n",
    )

    fault_sha = _sha_bytes(FAULT_OVERLAY.encode())
    applied_overlay = stage_root / "speed_decider.pb.txt"
    planned = {
        "schema_version": 1,
        "status": "PLANNED",
        "capture_label": "BENCHMARK_CONSTRUCTION_CANDIDATE",
        "candidate_id": contract["candidate_id"],
        "run_id": args.run_id,
        "variant": args.variant,
        "repeat_index": args.repeat_index,
        "seed": 1101,
        "duration_s": 32.0,
        "source_commit": source_commit,
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "calibration_table_sha256": CALIBRATION_SHA256,
        "vendor_default_sha256": _sha(vendor_default),
        "fault_implementation_sha256": fault_sha,
        "applied_overlay_sha256": _sha(applied_overlay),
        "raw_run_root": str(raw_run),
    }
    planned_path = run_state / "planned.json"
    if planned_path.exists() and json.loads(planned_path.read_text()) != planned:
        raise SystemExit("existing immutable run plan differs")
    _atomic_json(planned_path, planned)
    _atomic_json(private / "scenario.json", scenario)
    _atomic_json(private / "interposer.json", interposer)
    _atomic_json(private / "capture.json", capture_config)
    _atomic_json(private / "mutation_manifest.json", {
        "candidate_id": contract["candidate_id"],
        "variant": args.variant,
        "field": fault["field"],
        "reference_value": fault["reference_value"],
        "faulty_value": fault["faulty_value"],
        "fault_implementation_sha256": fault_sha,
        "applied_overlay_sha256": _sha(applied_overlay),
        "vendor_default_sha256": _sha(vendor_default),
    })
    config_manifest = {
        "schema_version": 1,
        "files": {
            str(path.relative_to(raw_run)): _sha(path)
            for path in sorted(apollo_conf.rglob("*")) if path.is_file()
        },
    }
    _atomic_json(raw_run / "apollo_conf_manifest.json", config_manifest)
    capture.mkdir(parents=True, exist_ok=True)
    os.chmod(raw_run, 0o700)
    os.chmod(private, 0o700)
    os.chmod(capture, 0o700)
    print(json.dumps(planned, sort_keys=True))


if __name__ == "__main__":
    main()
