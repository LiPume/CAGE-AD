#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cage_ad.protocol_v1.attempts import prepare_attempt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--private-oracle-root", type=Path, required=True)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--dose-json")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--infrastructure-attempt", type=int, default=0)
    args = parser.parse_args()
    prepared = prepare_attempt(
        repo_root=args.repo_root,
        state_root=args.state_root,
        data_root=args.data_root,
        private_oracle_root=args.private_oracle_root,
        recipe_id=args.recipe_id,
        phase=args.phase,
        candidate_id=args.candidate_id,
        seed=args.seed,
        condition=args.condition,
        dose=None if args.dose_json is None else json.loads(args.dose_json),
        source_commit=args.source_commit,
        infrastructure_attempt=args.infrastructure_attempt,
    )
    print(
        json.dumps(
            {
                "attempt_id": prepared.attempt_id,
                "private_root": str(prepared.private_root),
                "visible_root": str(prepared.visible_root),
                "log_root": str(prepared.log_root),
                "plan_record_sha256": prepared.plan_record_sha256,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
