#!/usr/bin/env python3
"""Export a D0-A0 evaluation to deterministic CSV, Parquet, and SVG artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


FIELDS = [
    "batch_id",
    "source_commit",
    "config_sha256",
    "episode_id",
    "scenario_kind",
    "responsibility_domain",
    "fault_mechanism",
    "result",
    "nominal_valid",
    "runtime_valid_count",
    "mechanism_confirmed_count",
    "task_failure_count",
    "repeat_votes",
    "correct_probe_repair",
    "wrong_probe_false_repair_count",
    "leakage_hit_count",
]


def flatten(evaluation: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for episode in evaluation["episodes"]:
        checks = episode["repeat_checks"]
        rows.append(
            {
                "batch_id": evaluation["batch_id"],
                "source_commit": plan["source_commit"],
                "config_sha256": plan["config_sha256"],
                "episode_id": episode["episode_id"],
                "scenario_kind": episode["scenario_kind"],
                "responsibility_domain": episode["responsibility_domain"],
                "fault_mechanism": episode["fault_mechanism"],
                "result": episode["result"],
                "nominal_valid": episode["nominal_valid"],
                "runtime_valid_count": sum(item["runtime_valid"] for item in checks),
                "mechanism_confirmed_count": sum(
                    item["mechanism_confirmed"] for item in checks
                ),
                "task_failure_count": sum(item["task_failure"] for item in checks),
                "repeat_votes": episode["repeat_votes"],
                "correct_probe_repair": episode["correct_probe_repair"],
                "wrong_probe_false_repair_count": sum(
                    episode["wrong_probe_false_repairs"].values()
                ),
                "leakage_hit_count": len(episode["leakage_token_hits"]),
            }
        )
    return sorted(rows, key=lambda row: row["episode_id"])


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, temporary, compression="zstd", version="2.6")
    os.replace(temporary, path)


def write_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    groups = sorted({(row["scenario_kind"], row["responsibility_domain"]) for row in rows})
    passed = Counter(
        (row["scenario_kind"], row["responsibility_domain"])
        for row in rows
        if row["result"] == "PASS"
    )
    width, height = 900, 420
    left, top, bottom = 70, 45, 130
    plot_height = height - top - bottom
    bar_width = 78
    gap = (width - left - 30 - bar_width * len(groups)) / max(1, len(groups))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="450" y="25" text-anchor="middle" font-family="sans-serif" font-size="18">D0-A0 combined-gate passes (of 2 mechanisms)</text>',
    ]
    for tick in range(3):
        y = top + plot_height - tick * plot_height / 2
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="870" y2="{y:.1f}" stroke="#ddd"/>')
        parts.append(f'<text x="55" y="{y + 5:.1f}" text-anchor="end" font-family="sans-serif" font-size="12">{tick}</text>')
    for index, group in enumerate(groups):
        x = left + gap / 2 + index * (bar_width + gap)
        value = passed[group]
        bar_height = value * plot_height / 2
        y = top + plot_height - bar_height
        color = "#2a9d8f" if value else "#d9d9d9"
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" fill="{color}"/>')
        parts.append(f'<text x="{x + bar_width / 2:.1f}" y="{y - 7:.1f}" text-anchor="middle" font-family="sans-serif" font-size="14">{value}/2</text>')
        scene = "cut-in" if group[0].startswith("cut_in") else "lead-decel"
        domain = {
            "interaction_forecasting": "forecast",
            "motion_planning": "planning",
            "tracking_execution": "control",
        }[group[1]]
        parts.append(f'<text transform="translate({x + bar_width / 2:.1f},305) rotate(45)" font-family="sans-serif" font-size="12">{scene} / {domain}</text>')
    parts.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text("\n".join(parts) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--svg", type=Path, required=True)
    args = parser.parse_args()
    rows = flatten(json.loads(args.evaluation.read_text()), json.loads(args.plan.read_text()))
    write_csv(args.csv, rows)
    write_parquet(args.parquet, rows)
    write_svg(args.svg, rows)
    print(f"smoke_results_export=PASS rows={len(rows)}")


if __name__ == "__main__":
    main()
