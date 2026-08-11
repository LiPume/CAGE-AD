#!/usr/bin/env python3
"""Summarize same-call CARLA-to-Apollo chassis gear telemetry."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path


def expected_gear(actual: dict) -> int:
    if actual["hand_brake"]:
        return 3
    if actual["reverse"] or actual["gear"] < 0:
        return 2
    if actual["gear"] == 0:
        return 0
    return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records = []
    control_apply_count = 0
    for line in args.telemetry.read_text().splitlines():
        record = json.loads(line)
        if record.get("record_type") == "chassis_feedback":
            records.append(record)
        elif record.get("record_type") == "control_apply":
            control_apply_count += 1

    mismatches = [
        record for record in records
        if record["apollo_published"]["gear_location"]
        != expected_gear(record["carla_actual"])
    ]
    actual_counts = Counter(record["carla_actual"]["gear"] for record in records)
    summary = {
        "schema_version": 1,
        "label": "RUNTIME_REPAIR_SMOKE_NOT_DATASET",
        "paired_chassis_feedback_records": len(records),
        "control_apply_records": control_apply_count,
        "actual_gear_counts": {str(key): value for key, value in sorted(actual_counts.items())},
        "manual_gear_shift_true_records": sum(
            record["carla_actual"]["manual_gear_shift"] for record in records
        ),
        "mapping_mismatch_records": len(mismatches),
        "false_drive_feedback_records": sum(
            record["apollo_published"]["gear_location"] == 1
            and record["carla_actual"]["gear"] != 1
            for record in records
        ),
        "first_mismatches": mismatches[:10],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, args.output)
    print(json.dumps(summary, sort_keys=True))
    passed = (
        records
        and not mismatches
        and actual_counts[0] > 0
        and actual_counts[1] > 0
        and summary["manual_gear_shift_true_records"] == 0
    )
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
