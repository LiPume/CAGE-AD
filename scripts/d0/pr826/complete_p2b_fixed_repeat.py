#!/usr/bin/env python3
"""Append one immutable P2B fixed-repeat result to its formal ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    summary = json.loads(args.summary.read_text())
    repeat_id = manifest["repeat_id"]
    rows = [json.loads(line) for line in args.ledger.read_text().splitlines() if line.strip()]
    if sum(row.get("repeat_id") == repeat_id and row.get("event") == "PLANNED" for row in rows) != 1:
        raise SystemExit("exactly one PLANNED event is required")
    if any(row.get("repeat_id") == repeat_id and row.get("event") == "RESULT" for row in rows):
        raise SystemExit("append-only policy forbids replacing a result")
    admission = summary["admission"]
    append_jsonl(args.ledger, {
        "event": "RESULT",
        "timestamp": args.timestamp,
        "repeat_id": repeat_id,
        "candidate_id": manifest["candidate"]["candidate_id"],
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "summary_path": str(args.summary),
        "summary_sha256": hashlib.sha256(args.summary.read_bytes()).hexdigest(),
        "domain_active": False,
        "status": admission["status"],
        "reject_code": admission["reject_code"],
        "metrics": summary["metrics"],
    })


if __name__ == "__main__":
    main()
