#!/usr/bin/env python3
"""Append an immutable result event for one preplanned reference screening."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    summary = json.loads(args.summary.read_text())
    screening_id = manifest["screening_id"]
    existing = [json.loads(line) for line in args.ledger.read_text().splitlines() if line.strip()]
    if sum(row.get("screening_id") == screening_id and row.get("event") == "PLANNED"
           for row in existing) != 1:
        raise SystemExit("exactly one PLANNED event is required")
    if any(row.get("screening_id") == screening_id and row.get("event") == "RESULT"
           for row in existing):
        raise SystemExit("RESULT already exists; append-only policy forbids replacement")
    result = summary.get("admission", {})
    append_jsonl(args.ledger, {
        "timestamp": args.timestamp,
        "event": "RESULT",
        "screening_id": screening_id,
        "candidate_id": manifest["candidate"]["candidate_id"],
        "status": result.get("status", "REJECT"),
        "reject_code": result.get("reject_code"),
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "summary_path": str(args.summary),
        "summary_sha256": hashlib.sha256(args.summary.read_bytes()).hexdigest(),
        "metrics": summary.get("metrics", {}),
        "fault_patch_exists": False,
    })


if __name__ == "__main__":
    main()
