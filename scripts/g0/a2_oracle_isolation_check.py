#!/usr/bin/env python3
"""Prove the diagnosis UID cannot read A2 private artifacts or injector state."""

import argparse
import json
import os
from pathlib import Path
import subprocess


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def denied(path: str) -> dict:
    completed = subprocess.run(
        [
            "setpriv",
            "--reuid=1001",
            "--regid=1001",
            "--clear-groups",
            "/usr/bin/head",
            "-c",
            "1",
            path,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "target_class": "private_artifact",
        "read_denied": completed.returncode != 0,
        "return_code": completed.returncode,
        "error_class": "permission_denied"
        if "Permission denied" in completed.stderr
        else "unreadable",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-config", required=True)
    parser.add_argument("--oracle", required=True)
    parser.add_argument("--injector-pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = [
        denied(args.private_config),
        denied(args.oracle),
        denied(f"/proc/{args.injector_pid}/environ"),
    ]
    result = {
        "schema_version": 1,
        "diagnosis_uid": 1001,
        "checks": checks,
        "result": "PASS" if all(item["read_denied"] for item in checks) else "FAIL",
        "note": "Targets are named by class only; private paths and contents are omitted.",
    }
    atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
