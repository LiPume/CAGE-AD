#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cage_ad.benchmark_construction.admission import AdmissionPolicy, evaluate_candidate


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-repeats", type=int, default=3)
    parser.add_argument("--faulty-repeats", type=int, default=3)
    parser.add_argument("--max-latency-s", type=float, default=5.0)
    args = parser.parse_args()
    candidate = json.loads(args.candidate.read_text())
    result = evaluate_candidate(
        candidate,
        AdmissionPolicy(
            reference_repeats=args.reference_repeats,
            faulty_repeats=args.faulty_repeats,
            max_activation_to_failure_seconds=args.max_latency_s,
        ),
    )
    atomic_json(args.output, result)
    print(
        f"benchmark_admission={result['benchmark_admission']} "
        f"failed_gates={','.join(result['failed_gates']) or 'none'}"
    )
    raise SystemExit(0 if result["benchmark_admission"] == "RETAINED_GOLD" else 1)


if __name__ == "__main__":
    main()
