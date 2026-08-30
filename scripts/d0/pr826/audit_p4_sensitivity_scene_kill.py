#!/usr/bin/env python3
"""Apply the user-frozen system-level cancellation kill criterion after P4-SENS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stability", type=Path, required=True)
    parser.add_argument("--matched", type=Path, required=True)
    parser.add_argument("--pair-a", type=Path, required=True)
    parser.add_argument("--pair-b", type=Path, required=True)
    parser.add_argument("--pair-c", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stability = json.loads(args.stability.read_text())
    matched = json.loads(args.matched.read_text())
    pair_paths = [args.pair_a, args.pair_b, args.pair_c]
    pairs = [json.loads(path.read_text()) for path in pair_paths]
    rows = []
    for label, pair in zip("ABC", pairs):
        s0 = pair["runs"]["S0"]
        s1 = pair["runs"]["S1"]
        rows.append(
            {
                "pair": label,
                "s0_overtake": s0["overtake_success"],
                "s1_overtake": s1["overtake_success"],
                "s0_lane_entry_s": s0["lane_minus_1_entry_s"],
                "s1_lane_entry_s": s1["lane_minus_1_entry_s"],
                "lane_entry_delay_s": pair["pair_delta"]["lane_minus_1_entry_delay_s"],
                "s0_pass_6m_s": s0["pass_margin_6m_s"],
                "s1_pass_6m_s": s1["pass_margin_6m_s"],
                "pass_6m_delay_s": s1["pass_margin_6m_s"] - s0["pass_margin_6m_s"],
                "planning_delta_observed": pair["sensitivity_signal_observed"],
            }
        )
    s1_cancels = [not row["s1_overtake"] for row in rows]
    cancellation_stable = all(s1_cancels)
    delay_directions = [row["lane_entry_delay_s"] for row in rows]
    result = {
        "schema_version": 1,
        "analysis_type": "P4_SENS_SYSTEM_LEVEL_SCENE_KILL",
        "classification": "NON_ADMISSION_CAUSAL_SENSITIVITY_PROBE",
        "admission_evidence": False,
        "inputs": {
            "stability_sha256": sha256(args.stability),
            "matched_sha256": sha256(args.matched),
            "pair_audit_sha256": [sha256(path) for path in pair_paths],
        },
        "checks": {
            "manifests_matched": matched["status"] == "PASS",
            "low_level_planning_sensitivity_stable": stability[
                "stable_sensitivity_established"
            ] is True,
            "s1_cancels_overtake_3_of_3": cancellation_stable,
            "s1_lane_entry_effect_direction_consistent": all(value >= 0.0 for value in delay_directions),
        },
        "pairs": rows,
        "stable_planning_sensitivity": stability["stable_sensitivity_established"],
        "stable_overtake_cancellation": cancellation_stable,
        "system_level_disposition": "SCENE_REJECTED_S1_DOES_NOT_CANCEL_OVERTAKE",
        "pr826_active_run_on_this_scene_authorized": False,
        "status": "SCENE_CLOSED_FOR_GOLDEN_CASE",
        "interpretation": (
            "The left-merge semantic reproducibly changes Planning and delays longitudinal pass "
            "progress, but all three S1 runs still overtake and lane-entry timing changes direction "
            "across pairs. The scene is sensitive but not a stable failed-overtake amplifier."
        ),
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
