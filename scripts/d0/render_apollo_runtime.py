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
    parser.add_argument("--control-flag-file", type=Path)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    generated = (args.state_root / "generated_apollo").resolve()
    generated.mkdir(parents=True, exist_ok=True)
    deploy = repo / "deploy/autodl_apollo10"
    dag = (deploy / "d0_planning.dag.in").read_text().replace("__CAGE_REPO_ROOT__", str(repo))
    control_dag = "modules/control/control_component/dag/control.dag"
    if args.control_flag_file:
        control_flag_file = args.control_flag_file.resolve()
        if not control_flag_file.is_file():
            raise SystemExit(f"control flag file is missing: {control_flag_file}")
        rendered_control_dag = (
            "module_config {\n"
            '  module_library : "modules/control/control_component/libcontrol_component.so"\n'
            "  timer_components {\n"
            '    class_name : "ControlComponent"\n'
            "    config {\n"
            '      name: "control"\n'
            f'      flag_file_path: "{control_flag_file}"\n'
            "      interval: 10\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        atomic_text(generated / "d0_control.dag", rendered_control_dag)
        control_dag = str(generated / "d0_control.dag")
    launch = (
        (deploy / "d0_pnc.launch.in").read_text()
        .replace("__CAGE_GENERATED_ROOT__", str(generated))
        .replace("__CAGE_CONTROL_DAG__", control_dag)
    )
    atomic_text(generated / "d0_planning.dag", dag)
    atomic_text(generated / "d0_pnc.launch", launch)
    print(generated / "d0_pnc.launch")


if __name__ == "__main__":
    main()
