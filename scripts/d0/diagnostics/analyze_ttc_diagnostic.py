#!/usr/bin/env python3
"""CPU-only protocol sanity and isolated diagnostic trace analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cage_ad.diagnostics.ttc_null import analytic_candidate_sanity, summarize_trace
from cage_ad.protocol_v1.loader import load_protocol


def scenario_sanity(repo_root: Path) -> dict:
    bundle = load_protocol(repo_root)
    requested = {
        "LBC0": ("lead_brake_close", "lead_vehicle_deceleration"),
        "LBM0": ("lead_brake_moderate", "lead_vehicle_deceleration"),
        "CIE0": ("cut_in_early", "cut_in_or_crossing_actor"),
        "CIL0": ("cut_in_late", "cut_in_or_crossing_actor"),
    }
    result = {"schema_version": 1, "diagnostic_only_not_dataset": True, "ego_speeds_mps": [0, 2, 4, 6, 8, 10], "candidates": {}}
    for candidate_id, (scenario_id, family) in requested.items():
        candidates = bundle.scenarios["scenarios"][scenario_id]["candidate_order"]
        matches = [dict(item) for item in candidates if item["candidate_id"] == candidate_id]
        if len(matches) != 1:
            raise RuntimeError(f"candidate is missing or duplicated: {candidate_id}")
        candidate = matches[0]
        result["candidates"][candidate_id] = {
            "scenario_id": scenario_id,
            "semantic_family": family,
            "runs": [analytic_candidate_sanity(candidate, family, speed) for speed in result["ego_speeds_mps"]],
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--scenario-sanity-output", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    if bool(args.scenario_sanity_output) == bool(args.trace):
        parser.error("choose exactly one of --scenario-sanity-output or --trace")
    if args.scenario_sanity_output:
        document = scenario_sanity(args.repo_root)
        output = args.scenario_sanity_output
    else:
        if args.summary_output is None:
            parser.error("--summary-output is required with --trace")
        document = summarize_trace(args.trace)
        output = args.summary_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps(document, sort_keys=True))


if __name__ == "__main__":
    main()
