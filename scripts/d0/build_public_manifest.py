#!/usr/bin/env python3
"""Build a deterministic public manifest without reading evaluator-private data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cage_ad.dataset_manifest import build_public_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_public_manifest(
        data_root=args.data_root,
        state_root=args.state_root,
        repo_root=args.repo_root,
        batch_id=args.batch_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, args.output)
    print(
        "public_manifest=PASS "
        f"episodes={manifest['diagnosis_episode_count']} "
        f"companions={manifest['companion_run_count']} "
        f"sha256={manifest['content_sha256']}"
    )


if __name__ == "__main__":
    main()
