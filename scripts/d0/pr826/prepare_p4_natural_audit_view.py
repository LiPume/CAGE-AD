#!/usr/bin/env python3
"""Build a read-only audit view that points stack.log at Apollo's native Prediction glog."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


DOMAIN = re.compile(r"S3TRACE stage=eligibility .* domain=(?P<domain>[01])")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--apollo-log-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    timing = json.loads((args.run_dir / "timing.json").read_text())
    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    start_ns, end_ns = int(timing["started_ns"]), int(timing["ended_ns"])
    candidates = []
    for path in args.apollo_log_root.glob("prediction.log.INFO.*"):
        stat = path.stat()
        if not (start_ns <= stat.st_mtime_ns <= end_ns + 2_000_000_000):
            continue
        text = path.read_text(errors="replace")
        domains = {int(match["domain"]) for match in DOMAIN.finditer(text)}
        if domains:
            candidates.append((path, domains, len(text)))
    if len(candidates) != 1:
        raise SystemExit(
            f"expected exactly one Prediction S3 trace in run interval, got {candidates}"
        )
    trace, domains, size = candidates[0]
    expected_domain = int(manifest["private_prediction_runtime"]["domain_active"])
    if domains != {expected_domain}:
        raise SystemExit(f"trace domain mismatch: {domains} != {{{expected_domain}}}")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    links = {
        "summary.json": args.run_dir / "summary.json",
        "planning_input_timeline.jsonl": args.run_dir / "planning_input_timeline.jsonl",
        "stack.log": trace,
    }
    for name, source in links.items():
        (args.output_dir / name).symlink_to(source.resolve())
    result = {
        "schema_version": 1,
        "run_id": manifest["screening_id"],
        "run_dir": str(args.run_dir.resolve()),
        "run_interval_ns": [start_ns, end_ns],
        "prediction_trace": str(trace.resolve()),
        "prediction_trace_sha256": sha256(trace),
        "prediction_trace_size": size,
        "observed_domains": sorted(domains),
        "expected_domain": expected_domain,
        "status": "PASS",
    }
    atomic_json(args.output_dir / "trace_provenance.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
