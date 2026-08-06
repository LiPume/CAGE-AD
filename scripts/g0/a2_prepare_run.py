#!/usr/bin/env python3
"""Create one A2 run's physically separated visible and evaluator areas."""

import argparse
import json
import os
from pathlib import Path


def write_json(path: Path, value: dict, mode: int) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-index", type=int, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    args = parser.parse_args()
    if args.run_index < 1:
        raise ValueError("run index must be positive")
    run_id = str(args.run_index)
    scenario_id = "g0a2_" + run_id.zfill(6)
    args.run_root.mkdir(parents=True, exist_ok=True, mode=0o711)
    os.chmod(args.run_root, 0o711)
    visible = args.run_root / "visible"
    visible.mkdir(mode=0o700, exist_ok=True)
    os.chown(visible, 1001, 1001)
    os.chmod(visible, 0o700)
    args.private_root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.private_root.parent, 0o700)
    args.private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.private_root, 0o700)
    write_json(
        args.private_root / "injector_config.json",
        {"schema_version": 1, "delay_seconds": 2.0},
        0o600,
    )
    write_json(
        args.private_root / "oracle.json",
        {
            "scenario_id": scenario_id,
            "oracle": {
                "visible_to_diagnosis": False,
                "fault_type": "control_delay",
                "root_module": "tracking_and_execution",
                "fault_start_time": 0.0,
                "fault_segment": [0.0, 15.0],
                "notes": "Closed-loop two-second control-target transport delay.",
            },
        },
        0o600,
    )
    print(scenario_id)


if __name__ == "__main__":
    main()
