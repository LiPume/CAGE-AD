#!/usr/bin/env python3
"""Close one diagnostic-only replay and hash its isolated outputs."""

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
    if planned.get("label") != "DIAGNOSTIC_ONLY_NOT_DATASET" or planned.get("seed") != 1101:
        raise SystemExit("invalid diagnostic plan")
    outputs = {}
    trace_frames = None
    if args.trace.is_file():
        outputs[str(args.trace)] = _sha(args.trace)
        trace_frames = sum(1 for line in args.trace.read_text().splitlines() if line.strip())
    if args.summary.is_file():
        outputs[str(args.summary)] = _sha(args.summary)
        summary = json.loads(args.summary.read_text())
        if trace_frames != summary.get("trace_frames"):
            raise SystemExit("trace line count does not match summary.trace_frames")
    status = "COMPLETED" if args.runtime_exit == 0 and len(outputs) == 2 else "FAILED"
    document = {
        "schema_version": 1,
        "status": status,
        "label": "DIAGNOSTIC_ONLY_NOT_DATASET",
        "run_id": planned["run_id"],
        "seed": planned["seed"],
        "runtime_exit": args.runtime_exit,
        "powered_on_seconds": args.powered_on_seconds,
        "trace_frames": trace_frames,
        "output_sha256": outputs,
    }
    if args.finished.exists():
        raise SystemExit("diagnostic finished.json already exists")
    _atomic(args.finished, document)
    print(json.dumps(document, sort_keys=True))


if __name__ == "__main__":
    main()
