#!/usr/bin/env python3
"""Check P4-SENS pair and repeat manifest matching."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def differences(left: object, right: object, path: str = "") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        result = []
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


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pair_expected = sorted(
        [
            "p4_sensitivity_probe.lateral_offset_m",
            "p4_sensitivity_probe.relative_end_s",
            "p4_sensitivity_probe.relative_start_s",
            "p4_sensitivity_probe.semantic",
            "screening_id",
        ]
    )
    repeat_expected = ["created_at", "screening_id"]
    pair_rows = []
    repeat_rows = []
    for suffix in "ABC":
        s0 = json.loads((args.run_root / f"PW0_{suffix}/manifest.json").read_text())
        s1 = json.loads((args.run_root / f"PW1_{suffix}/manifest.json").read_text())
        found = sorted(differences(s0, s1))
        pair_rows.append(
            {"pair": suffix, "observed": found, "expected": pair_expected, "pass": found == pair_expected}
        )
    for prefix in ("PW0", "PW1"):
        baseline = json.loads((args.run_root / f"{prefix}_A/manifest.json").read_text())
        for suffix in "BC":
            repeat = json.loads((args.run_root / f"{prefix}_{suffix}/manifest.json").read_text())
            found = sorted(differences(baseline, repeat))
            repeat_rows.append(
                {"semantic_prefix": prefix, "repeat": suffix, "observed": found, "expected": repeat_expected, "pass": found == repeat_expected}
            )
    passed = all(row["pass"] for row in pair_rows + repeat_rows)
    result = {
        "schema_version": 1,
        "analysis_type": "P4_SENS_MATCHED_MANIFEST",
        "admission_evidence": False,
        "pair_checks": pair_rows,
        "repeat_checks": repeat_rows,
        "status": "PASS" if passed else "INFRA_INVALID",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
