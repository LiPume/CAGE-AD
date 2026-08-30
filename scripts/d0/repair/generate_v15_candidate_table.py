#!/usr/bin/env python3
"""Generate a reversible low-speed positive-acceleration calibration candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


LOW_SPEED_MAX_MPS = 1.2
ACCELERATION_GRID = (0.0, 0.03, 0.06, 0.10, 0.20, 0.30, 0.40, 0.60, 0.80, 1.00, 1.15, 1.50, 2.00)
ANCHORS = (
    (0.0, 19.2861978383206),
    (0.02865492488189002, 20.0),
    (0.05983491466339212, 23.333333333333332),
    (0.3069009941090719, 26.666666666666668),
    (1.1557528153709564, 33.333333333333336),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path: Path) -> list[dict]:
    entries = []
    for block in re.findall(r"calibration\s*\{(.*?)\}", path.read_text(), re.S):
        fields = {
            key: float(value)
            for key, value in re.findall(
                r"(speed|acceleration|command):\s*([-+0-9.eE]+)", block
            )
        }
        if len(fields) == 3:
            entries.append(fields)
    if not entries:
        raise SystemExit("no calibration entries parsed")
    return entries


def candidate_command(acceleration: float) -> float:
    if acceleration <= ANCHORS[0][0]:
        return ANCHORS[0][1]
    if acceleration >= ANCHORS[-1][0]:
        return ANCHORS[-1][1]
    for (left_a, left_c), (right_a, right_c) in zip(ANCHORS, ANCHORS[1:]):
        if acceleration <= right_a:
            ratio = (acceleration - left_a) / (right_a - left_a)
            return left_c + ratio * (right_c - left_c)
    raise AssertionError("unreachable interpolation branch")


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(value)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    original = parse(args.base)
    speeds = sorted({entry["speed"] for entry in original})
    retained = [
        dict(entry) for entry in original
        if entry["speed"] > LOW_SPEED_MAX_MPS or entry["acceleration"] < 0.0
    ]
    replacements = [
        {
            "speed": speed,
            "acceleration": acceleration,
            "command": candidate_command(acceleration),
        }
        for speed in speeds if speed <= LOW_SPEED_MAX_MPS
        for acceleration in ACCELERATION_GRID
    ]
    candidate = sorted(
        retained + replacements,
        key=lambda entry: (entry["speed"], entry["acceleration"]),
    )
    text = "".join(
        "calibration {\n"
        f"  speed: {entry['speed']:.17g}\n"
        f"  acceleration: {entry['acceleration']:.17g}\n"
        f"  command: {entry['command']:.17g}\n"
        "}\n"
        for entry in candidate
    )
    atomic_text(args.output, text)

    reparsed = parse(args.output)
    original_negative = sorted(
        (entry["speed"], entry["acceleration"], entry["command"])
        for entry in original if entry["acceleration"] < 0.0
    )
    candidate_negative = sorted(
        (entry["speed"], entry["acceleration"], entry["command"])
        for entry in reparsed if entry["acceleration"] < 0.0
    )
    original_high_speed = sorted(
        (entry["speed"], entry["acceleration"], entry["command"])
        for entry in original if entry["speed"] > LOW_SPEED_MAX_MPS
    )
    candidate_high_speed = sorted(
        (entry["speed"], entry["acceleration"], entry["command"])
        for entry in reparsed if entry["speed"] > LOW_SPEED_MAX_MPS
    )
    checks = {
        "all_negative_entries_preserved": original_negative == candidate_negative,
        "all_high_speed_entries_preserved": original_high_speed == candidate_high_speed,
        "low_speed_positive_grid_complete": all(
            sum(
                entry["speed"] == speed and entry["acceleration"] >= 0.0
                for entry in reparsed
            ) == len(ACCELERATION_GRID)
            for speed in speeds if speed <= LOW_SPEED_MAX_MPS
        ),
        "candidate_commands_bounded": all(
            19.2861978383 <= candidate_command(value) <= 33.3333333334
            for value in ACCELERATION_GRID
        ),
    }
    manifest = {
        "schema_version": 1,
        "label": "RUNTIME_REPAIR_CANDIDATE_NOT_DATASET",
        "base_sha256": sha256(args.base),
        "candidate_sha256": sha256(args.output),
        "low_speed_max_mps": LOW_SPEED_MAX_MPS,
        "acceleration_grid_mps2": list(ACCELERATION_GRID),
        "anchors_acceleration_to_apollo_command_percent": [list(value) for value in ANCHORS],
        "base_entry_count": len(original),
        "candidate_entry_count": len(reparsed),
        "checks": checks,
        "passed": all(checks.values()),
    }
    atomic_text(args.manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))
    raise SystemExit(0 if manifest["passed"] else 2)


if __name__ == "__main__":
    main()
