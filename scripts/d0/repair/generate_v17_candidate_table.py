#!/usr/bin/env python3
"""Generate a reversible multi-speed positive-acceleration table candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


SPEED_MAX_MPS = 2.0
SPEED_ANCHORS = (1.0, 1.5, 2.0)
CARLA_THROTTLES = (0.30, 0.35, 0.40, 0.45, 0.50)
APOLLO_COMMANDS = tuple(value * 100.0 / 1.5 for value in CARLA_THROTTLES)
RESPONSES = {
    1.0: (-0.013414885748961134, 0.05231778066906347, 0.29048434114441996, 0.5973901093887614, 1.0584776281221995),
    1.5: (-0.1937880336446583, 0.013984718041082608, 0.22202846983709396, 0.5844670407064699, 1.1287578115678245),
    2.0: (-0.3478125979349792, -0.14631629757016437, 0.16426008382041898, 0.6583588011690249, 1.231693562406823),
}
ACCELERATION_GRID = (0.0, 0.03, 0.06, 0.10, 0.20, 0.30, 0.40, 0.60, 0.80, 1.00, 1.15, 1.50, 2.00)


def parse(path: Path) -> list[dict]:
    entries = []
    for block in re.findall(r"calibration\s*\{(.*?)\}", path.read_text(), re.S):
        fields = {key: float(value) for key, value in re.findall(
            r"(speed|acceleration|command):\s*([-+0-9.eE]+)", block
        )}
        if len(fields) == 3:
            entries.append(fields)
    if not entries:
        raise SystemExit("no calibration entries parsed")
    return entries


def response_at_speed(speed: float) -> tuple[float, ...]:
    if speed <= SPEED_ANCHORS[0]:
        return RESPONSES[SPEED_ANCHORS[0]]
    if speed >= SPEED_ANCHORS[-1]:
        return RESPONSES[SPEED_ANCHORS[-1]]
    for left, right in zip(SPEED_ANCHORS, SPEED_ANCHORS[1:]):
        if speed <= right:
            ratio = (speed - left) / (right - left)
            return tuple(
                left_value + ratio * (right_value - left_value)
                for left_value, right_value in zip(RESPONSES[left], RESPONSES[right])
            )
    raise AssertionError("unreachable speed interpolation")


def inverse_command(speed: float, acceleration: float) -> float:
    responses = response_at_speed(speed)
    if acceleration <= responses[0]:
        return APOLLO_COMMANDS[0]
    if acceleration >= responses[-1]:
        return APOLLO_COMMANDS[-1]
    for index, (left, right) in enumerate(zip(responses, responses[1:])):
        if acceleration <= right:
            ratio = (acceleration - left) / (right - left)
            return APOLLO_COMMANDS[index] + ratio * (
                APOLLO_COMMANDS[index + 1] - APOLLO_COMMANDS[index]
            )
    raise AssertionError("unreachable response inversion")


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
    retained = [dict(entry) for entry in original if entry["speed"] > SPEED_MAX_MPS or entry["acceleration"] < 0.0]
    replacements = [
        {"speed": speed, "acceleration": acceleration, "command": inverse_command(speed, acceleration)}
        for speed in speeds if speed <= SPEED_MAX_MPS
        for acceleration in ACCELERATION_GRID
    ]
    candidate = sorted(retained + replacements, key=lambda entry: (entry["speed"], entry["acceleration"]))
    atomic_text(args.output, "".join(
        "calibration {\n"
        f"  speed: {entry['speed']:.17g}\n"
        f"  acceleration: {entry['acceleration']:.17g}\n"
        f"  command: {entry['command']:.17g}\n"
        "}\n" for entry in candidate
    ))
    reparsed = parse(args.output)
    original_negative = sorted((x["speed"], x["acceleration"], x["command"]) for x in original if x["acceleration"] < 0.0)
    candidate_negative = sorted((x["speed"], x["acceleration"], x["command"]) for x in reparsed if x["acceleration"] < 0.0)
    original_high = sorted((x["speed"], x["acceleration"], x["command"]) for x in original if x["speed"] > SPEED_MAX_MPS)
    candidate_high = sorted((x["speed"], x["acceleration"], x["command"]) for x in reparsed if x["speed"] > SPEED_MAX_MPS)
    checks = {
        "all_negative_entries_preserved": original_negative == candidate_negative,
        "all_high_speed_entries_preserved": original_high == candidate_high,
        "grid_complete": all(
            sum(x["speed"] == speed and x["acceleration"] >= 0.0 for x in reparsed) == len(ACCELERATION_GRID)
            for speed in speeds if speed <= SPEED_MAX_MPS
        ),
        "commands_bounded": all(20.0 <= inverse_command(speed, acceleration) <= 33.3333333334 for speed in speeds if speed <= SPEED_MAX_MPS for acceleration in ACCELERATION_GRID),
    }
    manifest = {
        "schema_version": 1,
        "label": "RUNTIME_REPAIR_CANDIDATE_NOT_DATASET",
        "base_sha256": hashlib.sha256(args.base.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "speed_max_mps": SPEED_MAX_MPS,
        "speed_anchors_mps": list(SPEED_ANCHORS),
        "carla_throttles": list(CARLA_THROTTLES),
        "acceleration_grid_mps2": list(ACCELERATION_GRID),
        "checks": checks,
        "passed": all(checks.values()),
    }
    atomic_text(args.manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))
    raise SystemExit(0 if manifest["passed"] else 2)


if __name__ == "__main__":
    main()
