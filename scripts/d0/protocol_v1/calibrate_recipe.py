#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cage_ad.protocol_v1.orchestrator import RecipeOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--private-oracle-root", type=Path, required=True)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = RecipeOrchestrator(
        repo_root=args.repo_root,
        bundle_root=args.bundle_root,
        runtime_root=args.runtime_root,
        state_root=args.state_root,
        data_root=args.data_root,
        private_oracle_root=args.private_oracle_root,
        recipe_id=args.recipe_id,
        execute=args.execute,
    ).run()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
