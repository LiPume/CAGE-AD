#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re


ANSI = re.compile(r"\x1b\[[0-9;]*m")
STARTED = re.compile(r"Start process \[(routing|planning|control)\] successfully\. pid: ([0-9]+)")


def parse_stack_pids(text: str) -> dict[str, int]:
    result = {name: int(pid) for name, pid in STARTED.findall(ANSI.sub("", text))}
    missing = {"routing", "planning", "control"} - set(result)
    if missing:
        raise RuntimeError("stack log does not contain required process PIDs: " + ", ".join(sorted(missing)))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-log", type=Path, required=True)
    parser.add_argument("--bridge-pid-file", type=Path, required=True)
    parser.add_argument("--scenario-pid", type=int, required=True)
    parser.add_argument("--interposer-pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pids = parse_stack_pids(args.stack_log.read_text(errors="replace"))
    pids.update(
        bridge=int(args.bridge_pid_file.read_text().strip()),
        scenario=args.scenario_pid,
        interposer=args.interposer_pid,
    )
    dead = [name for name, pid in pids.items() if not Path(f"/proc/{pid}").exists()]
    if dead:
        raise RuntimeError("required runtime process exited: " + ", ".join(dead))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(pids, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, args.output)
    print(json.dumps(pids, sort_keys=True))


if __name__ == "__main__":
    main()
