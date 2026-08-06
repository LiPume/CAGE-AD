#!/usr/bin/env python3
"""Diagnose one L1 semantic window and emit a typed non-GT action.

This entry point intentionally accepts only an observed semantic-window file.
It has no arguments or code paths for injector configuration or oracle labels.
"""

import argparse
import json
import os
from pathlib import Path
import time

def first_time(samples: list[dict], field: str, threshold: float):
    for sample in samples:
        if float(sample[field]) >= threshold:
            return float(sample["t"])
    return None


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    raw_bytes = args.input.read_bytes()
    observed = json.loads(raw_bytes)
    if observed.get("semantic_slot") != "tracking_execution":
        raise ValueError("unsupported semantic slot")
    if set(observed).intersection({"oracle", "fault_type", "injector_state"}):
        raise ValueError("label-bearing field reached diagnosis entry")

    desired_onset = first_time(observed["control_target"], "throttle_pct", 1.0)
    applied_onset = first_time(observed["vehicle_response"], "throttle_pct", 1.0)
    lag = None
    if desired_onset is not None and applied_onset is not None:
        lag = applied_onset - desired_onset
    violation = lag is None or lag > 0.6
    evidence = {
        "evidence_id": "obs_tracking_lag_001",
        "metric_name": "control_target_response_lag",
        "value": "no_response" if lag is None else round(lag, 6),
        "threshold": 0.6,
        "time": desired_onset,
        "status": "violation" if violation else "normal",
        "supports": ["tracking_and_execution"] if violation else [],
        "contradicts": [] if violation else ["tracking_and_execution"],
        "description": "L1 control-target onset compared with vehicle actuator response.",
    }
    action = {
        "schema_version": "diagnostic_action_v0",
        "action_id": "probe_tracking_output_001",
        "proposed_by": "tracking_execution_specialist",
        "target_hypotheses": ["tracking_and_execution"],
        "required_regime": "L1",
        "action_type": "intervention",
        "intervention_class": "I2_semantic_replacement",
        "semantic_slot": "control_target",
        "replacement": {
            "throttle_pct": 0.0,
            "brake_pct": 60.0,
            "steering_pct": 0.0,
            "duration_seconds": 2.0,
            "source": "fixed_safety_probe",
            "uses_ground_truth": False,
        },
        "evidence_ids": [evidence["evidence_id"]],
        "diagnosis": {
            "prediction_set": ["tracking_and_execution"] if violation else [],
            "confidence": 0.9 if violation else 0.2,
            "observed_lag_seconds": lag,
        },
        "measured_query_cost": {
            "access_level": "L1",
            "signals": 1,
            "bytes": len(raw_bytes),
            "runtime_seconds": time.monotonic() - started,
            "human_minutes": 0,
            "risk": 0,
        },
        "evidence": [evidence],
    }
    atomic_json(args.output, action)


if __name__ == "__main__":
    main()
