#!/usr/bin/env python3
"""Render Apollo launch templates into the external state root."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(content)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    generated = (args.state_root / "generated_apollo").resolve()
    generated.mkdir(parents=True, exist_ok=True)
    deploy = repo / "deploy/autodl_apollo10"
    dag = (deploy / "d0_planning.dag.in").read_text().replace("__CAGE_REPO_ROOT__", str(repo))
    launch = (deploy / "d0_pnc.launch.in").read_text().replace(
        "__CAGE_GENERATED_ROOT__", str(generated)
    )
    atomic_text(generated / "d0_planning.dag", dag)
    atomic_text(generated / "d0_pnc.launch", launch)
    print(generated / "d0_pnc.launch")


if __name__ == "__main__":
    main()
