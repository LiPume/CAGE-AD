#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "scripts/d0/pr826/p3_semantic_fixture.cc"
HEADER = (
    REPO
    / "benchmarks/apollo_d0/pr826_reference_v1/p3_semantic_port/nearby_filter_policy.h"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def semantic_view(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture": document["fixture"],
        "distance_limit_m": document["distance_limit_m"],
        "candidates": document["candidates"],
        "final_selected_candidate": document["final_selected_candidate"],
        "final_trajectories": document["final_trajectories"],
    }


def output_semantic_view(document: dict[str, Any]) -> dict[str, Any]:
    """Fields that can change the resulting candidate/trajectory output.

    The private decision trace is intentionally excluded: expanded-domain mode may evaluate an
    extra candidate and then retain it because a downstream guard is false. That is a mechanism
    trace difference, but not a Prediction semantic-output difference.
    """
    return {
        "fixture": document["fixture"],
        "enabled_candidates": [
            candidate["candidate_id"]
            for candidate in document["candidates"]
            if candidate["enable_after"]
        ],
        "final_selected_candidate": document["final_selected_candidate"],
        "final_trajectories": document["final_trajectories"],
    }


def by_id(document: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    return next(
        candidate
        for candidate in document["candidates"]
        if candidate["candidate_id"] == candidate_id
    )


def run(binary: Path, output: Path, fixture: str, mode: str) -> dict[str, Any]:
    subprocess.run(
        [str(binary), fixture, mode, str(output)],
        check=True,
        cwd=REPO,
    )
    return load(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    binary = output_dir / "p3_semantic_fixture"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-I",
            str(REPO),
            str(SOURCE),
            "-o",
            str(binary),
        ],
        check=True,
        cwd=REPO,
    )

    fixed_path = output_dir / "semantic_fixture_fixed.json"
    faulty_path = output_dir / "semantic_fixture_faulty.json"
    legacy_path = output_dir / "semantic_fixture_identity_legacy.json"
    wrong_fixed_path = output_dir / "semantic_fixture_wrong_fixed.json"
    wrong_faulty_path = output_dir / "semantic_fixture_wrong_faulty.json"
    reversed_path = output_dir / "semantic_fixture_reversed_fixed.json"

    fixed = run(binary, fixed_path, "target", "fixed")
    faulty = run(binary, faulty_path, "target", "candidate")
    legacy = run(binary, legacy_path, "target", "legacy")
    wrong_fixed = run(binary, wrong_fixed_path, "wrong", "fixed")
    wrong_faulty = run(binary, wrong_faulty_path, "wrong", "candidate")
    reversed_fixed = run(binary, reversed_path, "target", "fixed")

    identity_pass = semantic_view(fixed) == semantic_view(legacy)
    wrong_condition_pass = output_semantic_view(wrong_fixed) == output_semantic_view(
        wrong_faulty
    )
    reversibility_pass = semantic_view(fixed) == semantic_view(reversed_fixed)
    target_candidate_fixed = by_id(fixed, "A")
    target_candidate_faulty = by_id(faulty, "A")
    target_condition_pass = (
        target_candidate_fixed["enable_after"] is True
        and target_candidate_faulty["enable_after"] is False
        and fixed["final_selected_candidate"] == "A"
        and faulty["final_selected_candidate"] == "B"
        and fixed["final_trajectories"]
        == ["trajectory_for_A", "trajectory_for_B"]
        and faulty["final_trajectories"] == ["trajectory_for_B"]
    )
    changed_ids = [
        candidate["candidate_id"]
        for candidate in fixed["candidates"]
        if candidate["enable_after"]
        != by_id(faulty, candidate["candidate_id"])["enable_after"]
    ]
    exact_delta_pass = changed_ids == ["A"]
    all_pass = all(
        [
            identity_pass,
            wrong_condition_pass,
            reversibility_pass,
            target_condition_pass,
            exact_delta_pass,
        ]
    )
    diff = {
        "schema_version": 1,
        "status": "PASS" if all_pass else "FAIL",
        "controls": {
            "identity": identity_pass,
            "wrong_condition": wrong_condition_pass,
            "target_condition": target_condition_pass,
            "exact_candidate_delta": exact_delta_pass,
            "reversibility": reversibility_pass,
        },
        "changed_candidate_ids": changed_ids,
        "fixed_final_selected_candidate": fixed["final_selected_candidate"],
        "faulty_final_selected_candidate": faulty["final_selected_candidate"],
        "fixed_final_trajectories": fixed["final_trajectories"],
        "faulty_final_trajectories": faulty["final_trajectories"],
        "artifacts": {},
        "source_sha256": sha256(SOURCE),
        "policy_header_sha256": sha256(HEADER),
        "binary_sha256": sha256(binary),
    }
    for path in [
        fixed_path,
        faulty_path,
        legacy_path,
        wrong_fixed_path,
        wrong_faulty_path,
        reversed_path,
    ]:
        diff["artifacts"][path.name] = sha256(path)
    diff_path = output_dir / "semantic_fixture_diff.json"
    diff_path.write_text(
        json.dumps(diff, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(diff, indent=2, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
