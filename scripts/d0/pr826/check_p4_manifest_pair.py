#!/usr/bin/env python3
"""Assert that a P4 manifest pair has one and only one behavioral difference."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def differences(left: object, right: object, path: str = "") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        result: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(differences(left[key], right[key], child))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [path]
        result = []
        for index, (a, b) in enumerate(zip(left, right)):
            result.extend(differences(a, b, f"{path}[{index}]"))
        return result
    return [] if left == right else [path]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixed = json.loads(args.fixed.read_text())
    active = json.loads(args.active.read_text())
    found = differences(fixed, active)
    expected = sorted(
        ["arm", "private_prediction_runtime.domain_active", "screening_id"]
    )
    checks = {
        "exact_diff_paths": sorted(found) == expected,
        "fixed_switch_disabled": fixed["private_prediction_runtime"]["domain_active"] is False,
        "active_switch_enabled": active["private_prediction_runtime"]["domain_active"] is True,
        "trace_matched": fixed["private_prediction_runtime"]["trace_active"]
        == active["private_prediction_runtime"]["trace_active"],
    }
    result = {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "INFRA_INVALID",
        "checks": checks,
        "observed_diff_paths": sorted(found),
        "expected_diff_paths": expected,
        "only_behavioral_diff_path": "private_prediction_runtime.domain_active",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
