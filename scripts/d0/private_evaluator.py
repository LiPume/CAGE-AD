#!/usr/bin/env python3
"""Evaluator-only process entry point.

This file is never imported by the diagnosis package. The caller must run it only
after the diagnosis process exits and must provide an evaluator-private oracle path.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnosis-result", type=Path, required=True)
    parser.add_argument("--private-oracle", type=Path, required=True)
    parser.add_argument("--diagnosis-exited-marker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.diagnosis_exited_marker.is_file():
        raise RuntimeError("evaluator cannot run before diagnosis exit is recorded")
    diagnosis = json.loads(args.diagnosis_result.read_text())
    oracle = json.loads(args.private_oracle.read_text())
    predicted = set(diagnosis["prediction_set"])
    expected = oracle["responsibility_domain"]
    atomic_json(
        args.output,
        {
            "schema_version": 1,
            "episode_id": diagnosis["episode_id"],
            "correct": expected in predicted,
            "prediction_set_size": len(predicted),
            "evaluated_after_diagnosis_exit": True,
        },
    )


if __name__ == "__main__":
    main()
