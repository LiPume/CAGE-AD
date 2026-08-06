#!/usr/bin/env python3
"""Private evaluator for D0-A0 confirmations, probes, and leakage checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cage_ad.active_diagnosis.contracts import AccessRegime, ArtifactReference, CostVector, EpisodeSpec
from cage_ad.active_diagnosis.verifier import EvidenceVerifier, RawToolResult
from cage_ad.adapters.apollo_d0.semantics import FaultMechanism
from cage_ad.adapters.apollo_d0.smoke import (
    ACTION_BY_DOMAIN,
    DOMAINS,
    evidence_payloads,
    forbidden_visible_tokens,
    mechanism_confirmed,
    task_failure,
)


def atomic_json(path: Path, value: Any, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def load_run(private_batch: Path, retained: Path, run_id: str):
    private = private_batch / run_id
    return (
        json.loads((private / "run_metrics.json").read_text()),
        json.loads((retained / f"{run_id}.json").read_text()),
        json.loads((private / "interposer_stats.json").read_text()),
    )


def cost_for(action_id: str, payload_size: int, run: tuple | None) -> CostVector:
    if action_id == "O0_failure_summary":
        return CostVector(access=AccessRegime.L0, bytes=payload_size, signals=1)
    if action_id == "O2_timing_metadata":
        return CostVector(access=AccessRegime.L2, bytes=payload_size, signals=3)
    if action_id == "O3_semantic_replay":
        return CostVector(access=AccessRegime.L1, bytes=payload_size, signals=3, replay_count=2)
    if action_id.startswith("I2_"):
        assert run is not None
        return CostVector(
            access=AccessRegime.L1,
            bytes=payload_size,
            signals=3,
            replay_count=1,
            intervention_count=1,
            runtime_seconds=float(run[0]["wall_seconds"]),
            risk=1.0 if action_id.startswith("I2_F") else 2.0,
        )
    return CostVector(access=AccessRegime.L1, bytes=payload_size, signals=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--private-oracle-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    private_batch = args.private_oracle_root / args.batch_id
    results = []
    for oracle_path in sorted(private_batch.glob("episode_*.json")):
        oracle = json.loads(oracle_path.read_text())
        episode_id = oracle["episode_id"]
        visible_root = args.data_root / args.batch_id / episode_id / "visible"
        retained = args.data_root / args.batch_id / episode_id / "retained"
        nominal = load_run(private_batch, retained, oracle["runs"]["nominal"])
        fault_runs = [
            load_run(private_batch, retained, oracle["runs"][role])
            for role in oracle["fault_repeat_roles"]
        ]
        probes = {
            domain: load_run(private_batch, retained, oracle["runs"][f"probe_{domain}"])
            for domain in DOMAINS
        }
        mechanism = FaultMechanism(oracle["fault_mechanism"])
        repeat_checks = []
        for metrics, capture, stats in fault_runs:
            mechanism_ok, delta = mechanism_confirmed(
                mechanism, nominal[1], nominal[2], capture, stats
            )
            repeat_checks.append(
                {
                    "runtime_valid": metrics["result"] == "PASS",
                    "mechanism_confirmed": mechanism_ok,
                    "mechanism_delta": round(delta, 6),
                    "task_failure": task_failure(metrics),
                }
            )
        repeat_votes = sum(
            row["runtime_valid"] and row["mechanism_confirmed"] and row["task_failure"]
            for row in repeat_checks
        )
        correct_domain = oracle["responsibility_domain"]
        correct_metrics = probes[correct_domain][0]
        correct_probe_repair = task_failure(fault_runs[0][0]) and not task_failure(correct_metrics)
        wrong_probe_false_repairs = {
            domain: task_failure(fault_runs[0][0]) and not task_failure(probes[domain][0])
            for domain in DOMAINS
            if domain != correct_domain
        }
        payloads = evidence_payloads(fault_runs, probes)
        evidence_root = visible_root / "evidence"
        verified = []
        verifier = EvidenceVerifier(visible_root, args.private_oracle_root)
        for index, (action_id, payload) in enumerate(sorted(payloads.items())):
            payload_path = evidence_root / f"{action_id}.json"
            atomic_json(payload_path, payload)
            probe_run = None
            for domain, mapped_action in ACTION_BY_DOMAIN.items():
                if mapped_action == action_id:
                    probe_run = probes[domain]
            item = verifier.verify(
                action_id,
                RawToolResult(
                    evidence_id=hashlib.sha256(f"{episode_id}:{action_id}".encode()).hexdigest()[:24],
                    semantic_slot=payload.get("slot", "episode_summary"),
                    provenance="apollo_10_carla_0.9.15_semantic_adapter",
                    payload_path=payload_path,
                    measured_cost=cost_for(action_id, payload_path.stat().st_size, probe_run),
                    side_effects=("bounded_probe_run",) if action_id.startswith("I2_") else (),
                ),
            )
            verified.append(item.model_dump(mode="json"))
        initial = next(item for item in verified if item["action_id"] == "O0_failure_summary")
        spec = EpisodeSpec.model_validate_json((visible_root / "episode.json").read_text())
        spec.initial_evidence_refs = [ArtifactReference.model_validate(initial["payload_ref"])]
        atomic_json(visible_root / "episode.json", spec.model_dump(mode="json"))
        atomic_json(visible_root / "evidence_index.json", {"schema_version": 1, "evidence": verified})
        visible_bytes = b"".join(path.read_bytes() for path in sorted(visible_root.rglob("*.json")))
        token_hits = sorted(
            token for token in forbidden_visible_tokens(oracle) if token.encode() in visible_bytes
        )
        episode_pass = (
            nominal[0]["result"] == "PASS"
            and not task_failure(nominal[0])
            and repeat_votes >= 2
            and correct_probe_repair
            and not token_hits
        )
        result = {
            "episode_id": episode_id,
            "scenario_kind": oracle["scenario_kind"],
            "responsibility_domain": correct_domain,
            "fault_mechanism": oracle["fault_mechanism"],
            "nominal_valid": nominal[0]["result"] == "PASS" and not task_failure(nominal[0]),
            "repeat_checks": repeat_checks,
            "repeat_votes": repeat_votes,
            "correct_probe_repair": correct_probe_repair,
            "wrong_probe_false_repairs": wrong_probe_false_repairs,
            "leakage_token_hits": token_hits,
            "visible_checksums": {
                path.relative_to(visible_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(visible_root.rglob("*.json"))
            },
            "result": "PASS" if episode_pass else "FAIL",
        }
        atomic_json(private_batch / f"evaluation_{episode_id}.json", result, 0o600)
        results.append(result)
    report = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "episode_count": len(results),
        "pass_count": sum(row["result"] == "PASS" for row in results),
        "failure_count": sum(row["result"] != "PASS" for row in results),
        "wrong_probe_false_repair_count": sum(
            sum(row["wrong_probe_false_repairs"].values()) for row in results
        ),
        "episodes": results,
    }
    report["status"] = "PASS" if report["pass_count"] == len(results) == 12 else "FAIL"
    atomic_json(args.state_root / "evidence" / f"{args.batch_id}_evaluation.json", report)
    print(
        f"d0_a0_evaluation={report['status']} pass={report['pass_count']}/{report['episode_count']}"
    )
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
