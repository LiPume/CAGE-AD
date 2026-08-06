#!/usr/bin/env python3
"""Create opaque visible manifests and root-only evaluator plans for D0-A0."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid

import yaml

from cage_ad.active_diagnosis.contracts import EpisodeSpec, FailureWindow
from cage_ad.adapters.apollo_d0.semantics import DOMAIN_BY_MECHANISM, FaultMechanism, ScenarioKind


NAMESPACE = uuid.UUID("16e66fa2-2012-4d28-b203-e540581f3491")
DOMAINS = ["interaction_forecasting", "motion_planning", "tracking_execution"]
ACTIONS = [
    "O0_failure_summary",
    "O1_forecast_window",
    "O1_motion_plan_window",
    "O1_tracking_window",
    "O2_timing_metadata",
    "O3_semantic_replay",
    "I2_F_constant_velocity",
    "I2_P_safety_envelope",
    "I2_C_bounded_brake",
]


def atomic_json(path: Path, value: dict, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--private-oracle-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--batch-id", default="d0_a0_formal_v1")
    args = parser.parse_args()
    private = args.private_oracle_root / args.batch_id
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    args.data_root.mkdir(parents=True, exist_ok=True)
    config_hash = hashlib.sha256()
    for name in ("scenarios.yaml", "faults.yaml", "actions.yaml", "failure_thresholds.yaml"):
        config_hash.update((args.repo_root / "benchmarks/apollo_d0/draft" / name).read_bytes())

    episodes = []
    for scenario in ScenarioKind:
        opaque_scenario = "sg_" + uuid.uuid5(NAMESPACE, "scenario:" + scenario.value).hex[:12]
        for mechanism in FaultMechanism:
            domain = DOMAIN_BY_MECHANISM[mechanism]
            semantic_key = f"{args.batch_id}:{scenario.value}:{mechanism.value}:0"
            episode_id = uuid.uuid5(NAMESPACE, "episode:" + semantic_key).hex
            episode_root = args.data_root / args.batch_id / episode_id
            visible_root = episode_root / "visible"
            visible_root.mkdir(parents=True, exist_ok=True)
            spec = EpisodeSpec(
                episode_id=episode_id,
                scenario_template=opaque_scenario,
                failure_type="collision_or_safety_violation",
                failure_window=FailureWindow(start_s=0, end_s=32),
                observable_regime="L2",
                allowed_action_ids=ACTIONS,
                budget_profile="B3",
                seed=0,
            )
            atomic_json(visible_root / "episode.json", spec.model_dump(mode="json"), 0o640)
            runs = {}
            run_specs = [("nominal", None, None)]
            run_specs.extend(
                (f"fault_repeat_{repeat}", mechanism.value, None)
                for repeat in range(3)
            )
            run_specs.extend(
                (f"probe_{probe_domain}", mechanism.value, probe_domain)
                for probe_domain in DOMAINS
            )
            for role, fault, probe in run_specs:
                run_id = uuid.uuid5(NAMESPACE, f"run:{semantic_key}:{role}").hex
                run_private = private / run_id
                run_private.mkdir(parents=True, exist_ok=True, mode=0o700)
                run_private.chmod(0o700)
                atomic_json(
                    run_private / "scenario.json",
                    {"schema_version": 1, "scenario_kind": scenario.value, "seed": 0},
                    0o600,
                )
                atomic_json(
                    run_private / "injector.json",
                    {
                        "schema_version": 1,
                        "fault_mechanism": fault,
                        "probe_domain": probe,
                        "probe_start_s": 8.0,
                        "probe_duration_s": 3.0,
                        "control_delay_s": 1.5,
                    },
                    0o600,
                )
                runs[role] = run_id
            oracle = {
                "schema_version": 1,
                "episode_id": episode_id,
                "scenario_kind": scenario.value,
                "responsibility_domain": domain,
                "fault_mechanism": mechanism.value,
                "seed": 0,
                "runs": runs,
                "fault_repeat_roles": [f"fault_repeat_{repeat}" for repeat in range(3)],
                "correct_probe_role": f"probe_{domain}",
                "wrong_probe_roles": [
                    f"probe_{candidate}" for candidate in DOMAINS if candidate != domain
                ],
                "source_commit": args.source_commit,
                "config_sha256": config_hash.hexdigest(),
            }
            atomic_json(private / f"episode_{episode_id}.json", oracle, 0o600)
            episodes.append(
                {
                    "episode_id": episode_id,
                    "visible_manifest": str((visible_root / "episode.json").relative_to(args.data_root)),
                    "visible_manifest_sha256": digest(visible_root / "episode.json"),
                }
            )
    atomic_json(
        args.state_root / f"{args.batch_id}_plan.json",
        {
            "schema_version": 1,
            "status": "PREPARED",
            "batch_id": args.batch_id,
            "episodes": episodes,
            "episode_count": len(episodes),
            "source_commit": args.source_commit,
            "config_sha256": config_hash.hexdigest(),
        },
    )
    print(f"d0_a0_prepare=PASS batch={args.batch_id} episodes={len(episodes)}")


if __name__ == "__main__":
    main()
