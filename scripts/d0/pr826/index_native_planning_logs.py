#!/usr/bin/env python3
"""Index immutable native Planning logs associated with one experiment window."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--started-ns", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for path in sorted(args.log_dir.glob("planning.log.*")):
        stat = path.stat()
        if stat.st_mtime_ns < args.started_ns:
            continue
        records.append({
            "path": str(path.resolve()),
            "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": digest(path),
        })
    args.output.write_text(json.dumps({
        "schema_version": 1,
        "selection": "planning.log.* with mtime_ns >= run started_ns",
        "started_ns": args.started_ns,
        "files": records,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
