#!/usr/bin/env python3
"""Compare stock and inactive-port Prediction semantics on matched inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def keyed_frames(payload: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for frame in payload["frames"]:
        key = f'{float(frame["source_timestamp_sec"]):.9f}'
        if key in result:
            raise ValueError(f"duplicate source timestamp {key}")
        result[key] = frame
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--inactive-port", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-common-frames", type=int, default=100)
    args = parser.parse_args()

    stock_payload = json.loads(args.stock.read_text())
    inactive_payload = json.loads(args.inactive_port.read_text())
    stock = keyed_frames(stock_payload)
    inactive = keyed_frames(inactive_payload)
    common = sorted(set(stock) & set(inactive))
    mismatches = [key for key in common if stock[key] != inactive[key]]
    stock_only = sorted(set(stock) - set(inactive))
    inactive_only = sorted(set(inactive) - set(stock))

    checks = {
        "minimum_common_frames": len(common) >= args.minimum_common_frames,
        "common_frames_exactly_equal": not mismatches,
        "stock_capture_nonempty": bool(stock),
        "inactive_capture_nonempty": bool(inactive),
    }
    result = {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "stock_frame_count": len(stock),
        "inactive_port_frame_count": len(inactive),
        "common_frame_count": len(common),
        "mismatch_count": len(mismatches),
        "first_mismatch_source_timestamp": mismatches[0] if mismatches else None,
        "stock_only_count": len(stock_only),
        "inactive_only_count": len(inactive_only),
        "common_semantics_sha256": canonical_sha([stock[key] for key in common]),
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
