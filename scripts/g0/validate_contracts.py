#!/usr/bin/env python3
"""Validate frozen schemas, real A2 artifacts, and the golden diagnostic output."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from jsonschema import Draft202012Validator


def load(path: Path):
    return json.loads(path.read_text())


def validate(schema_path: Path, instance_path: Path) -> None:
    schema = load(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(load(instance_path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.bundle_root.resolve()
    contracts = root / "coordination" / "contracts"
    golden = root / "coordination" / "conformance"
    semantic_schema = contracts / "semantic_slots.schema.json"
    action_schema = contracts / "actions.schema.json"
    manifest_schema = contracts / "run_manifest.schema.json"
    golden_input = golden / "golden_inputs" / "tracking_execution_delayed.json"
    golden_expected = load(
        golden / "golden_expected" / "tracking_execution_delayed.json"
    )["expected"]
    validate(semantic_schema, golden_input)
    for index in (1, 2, 3, 4):
        visible = root / "runtime" / "runs" / "a2" / str(index) / "visible"
        validate(semantic_schema, visible / "o1_tracking_window.json")
        validate(action_schema, visible / "i2_action.json")
        validate(
            manifest_schema,
            root / "runtime_state" / "evidence" / "a2" / f"manifest_{index}.json",
        )

    with tempfile.TemporaryDirectory(prefix="cage_contract_") as temporary:
        output = Path(temporary) / "action.json"
        completed = subprocess.run(
            [
                str(root / "runtime" / "envs" / "guardian-py310" / "bin" / "python"),
                str(root / "scripts" / "a2_l1_diagnose.py"),
                "--input",
                str(golden_input),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)
        validate(action_schema, output)
        action = load(output)
    observed = {
        "evidence_id": action["evidence"][0]["evidence_id"],
        "metric_name": action["evidence"][0]["metric_name"],
        "status": action["evidence"][0]["status"],
        "observed_lag_seconds": action["diagnosis"]["observed_lag_seconds"],
        "prediction_set": action["diagnosis"]["prediction_set"],
        "action_type": action["action_type"],
        "intervention_class": action["intervention_class"],
        "semantic_slot": action["semantic_slot"],
        "uses_ground_truth": action["replacement"]["uses_ground_truth"],
        "brake_pct": action["replacement"]["brake_pct"],
        "duration_seconds": action["replacement"]["duration_seconds"],
    }
    if observed != golden_expected:
        raise AssertionError(f"golden mismatch: {observed} != {golden_expected}")
    print("contract_conformance=PASS schemas=3 real_runs=4 golden=1")


if __name__ == "__main__":
    main()
