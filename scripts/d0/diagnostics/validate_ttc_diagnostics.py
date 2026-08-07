#!/usr/bin/env python3
"""Validate diagnostic traces/videos and record content hashes outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe(path: Path, ffprobe: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    document = json.loads(result.stdout)
    if len(document.get("streams", ())) != 1:
        raise ValueError(f"{path}: expected one video stream")
    stream = document["streams"][0]
    if stream.get("codec_name") != "h264" or stream.get("width") != 1280 or stream.get("height") != 720:
        raise ValueError(f"{path}: unexpected video format {stream}")
    if float(document.get("format", {}).get("duration", 0.0)) <= 0.0:
        raise ValueError(f"{path}: nonpositive duration")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostic-data-root", type=Path, required=True)
    parser.add_argument("--diagnostic-state-root", type=Path, required=True)
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    for run_id in args.run_id:
        retained = args.diagnostic_data_root / run_id / "retained"
        trace = retained / "trace.jsonl"
        summary_path = retained / "summary.json"
        video = retained / "diagnostic_replay.mp4"
        finished_path = args.diagnostic_state_root / "runs" / run_id / "finished.json"
        summary = json.loads(summary_path.read_text())
        finished = json.loads(finished_path.read_text())
        line_count = sum(1 for line in trace.open() if line.strip())
        expected = int(summary["trace_frames"])
        if line_count != expected or int(finished["trace_frames"]) != expected:
            raise ValueError(
                f"{run_id}: trace lines={line_count} summary={expected} finished={finished['trace_frames']}"
            )
        probe = _probe(video, args.ffprobe)
        files = sorted(
            path
            for path in retained.iterdir()
            if path.is_file() and path.name in {
                "trace.jsonl",
                "summary.json",
                "xy_trajectory.png",
                "semantic_timeseries.png",
                "diagnostic_replay.mp4",
            }
        )
        records.append(
            {
                "run_id": run_id,
                "label": "DIAGNOSTIC_ONLY_NOT_DATASET",
                "trace_line_count": line_count,
                "summary_trace_frames": expected,
                "video_probe": probe,
                "sha256": {str(path): _sha256(path) for path in files},
            }
        )
    document = {"schema_version": 1, "status": "PASS", "runs": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"status": "PASS", "runs": len(records)}, sort_keys=True))


if __name__ == "__main__":
    main()
