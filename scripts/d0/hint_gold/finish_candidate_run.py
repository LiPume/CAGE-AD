#!/usr/bin/env python3
"""Fail-closed closure and hashing for one benchmark-construction capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planned", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--finished", type=Path, required=True)
    parser.add_argument("--powered-on-seconds", type=float, required=True)
    parser.add_argument("--runtime-exit", type=int, required=True)
    args = parser.parse_args()
    planned = json.loads(args.planned.read_text())
    if planned.get("capture_label") != "BENCHMARK_CONSTRUCTION_CANDIDATE":
        raise SystemExit("invalid benchmark-construction plan")
    outputs: dict[str, str] = {}
    trace_frames = None
    if args.trace.is_file():
        outputs["trace.jsonl"] = _sha(args.trace)
        trace_frames = sum(1 for line in args.trace.read_text().splitlines() if line.strip())
    if args.summary.is_file():
        summary = json.loads(args.summary.read_text())
        if summary.get("label") != "BENCHMARK_CONSTRUCTION_CANDIDATE":
            raise SystemExit("capture summary has the wrong purpose label")
        if trace_frames != summary.get("trace_frames"):
            raise SystemExit("trace line count does not match summary.trace_frames")
        outputs["summary.json"] = _sha(args.summary)
    document = {
        "schema_version": 1,
        "status": "COMPLETED" if args.runtime_exit == 0 and len(outputs) == 2 else "FAILED",
        "run_id": planned["run_id"],
        "variant": planned["variant"],
        "repeat_index": planned["repeat_index"],
        "runtime_exit": args.runtime_exit,
        "powered_on_seconds": args.powered_on_seconds,
        "trace_frames": trace_frames,
        "output_sha256": outputs,
    }
    if args.finished.exists():
        raise SystemExit("finished.json already exists")
    _atomic(args.finished, document)
    print(json.dumps(document, sort_keys=True))


if __name__ == "__main__":
    main()
