#!/usr/bin/env python3
"""Run the deterministic final G0 evidence and workspace audit."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

import yaml


def run(command: list[str], cwd: Path) -> dict:
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, check=False
    )
    return {
        "command": command,
        "return_code": completed.returncode,
        "runtime_seconds": time.monotonic() - started,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_json(path: Path):
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.bundle_root.resolve()
    checks = {}

    json_paths = sorted((root / "coordination").rglob("*.json")) + sorted(
        (root / "runtime_state" / "evidence").rglob("*.json")
    )
    json_errors = []
    for path in json_paths:
        try:
            load_json(path)
        except Exception as exc:
            json_errors.append({"path": str(path.relative_to(root)), "error": str(exc)})
    checks["json_parse"] = {
        "passed": not json_errors,
        "files": len(json_paths),
        "errors": json_errors,
    }

    yaml_paths = sorted((root / "coordination").rglob("*.yaml")) + sorted(
        (root / "runtime_state").glob("*.yaml")
    ) + sorted((root / "runtime_state" / "evidence").rglob("*.yaml"))
    yaml_errors = []
    for path in yaml_paths:
        try:
            yaml.safe_load(path.read_text())
        except Exception as exc:
            yaml_errors.append({"path": str(path.relative_to(root)), "error": str(exc)})
    checks["yaml_parse"] = {
        "passed": not yaml_errors,
        "files": len(yaml_paths),
        "errors": yaml_errors,
    }

    a0 = [
        load_json(root / "runtime_state/evidence/a0/stability_1800s.json"),
        load_json(root / "runtime_state/evidence/a0/stability_1800s_run2.json"),
        load_json(root / "runtime_state/evidence/a0/stability_1800s_run3.json"),
    ]
    a1 = [load_json(root / f"runtime_state/evidence/a1/run_{i}.json") for i in (1, 2, 3)]
    a2 = [load_json(root / f"runtime_state/evidence/a2/run_{i}.json") for i in (1, 2, 3)]
    replay = load_json(root / "runtime_state/evidence/a2/run_4.json")
    manifests = [
        load_json(root / f"runtime_state/evidence/a2/manifest_{i}.json")
        for i in (1, 2, 3, 4)
    ]
    isolations = [
        load_json(root / f"runtime_state/evidence/a2/isolation_{i}.json")
        for i in (1, 2, 3, 4)
    ]
    checks["gate_evidence"] = {
        "passed": all(
            item["status"] == "PASS"
            and float(item["measured_wall_seconds"]) >= 1800.0
            and item["discarded_sensor_callbacks"] == {"rgb": 0, "lidar": 0}
            and item["max_sensor_world_timestamp_error_seconds"] == 0.0
            for item in a0
        )
        and all(item["result"] == "PASS" for item in a1 + a2 + [replay])
        and all(item["result"] == "PASS" for item in manifests + isolations),
        "a0_passes": sum(item["status"] == "PASS" for item in a0),
        "a0_wall_seconds": [item["measured_wall_seconds"] for item in a0],
        "a1_passes": sum(item["result"] == "PASS" for item in a1),
        "a2_formal_passes": sum(item["result"] == "PASS" for item in a2),
        "clean_shell_replay": replay["result"],
    }

    private_root = root / "runtime_state/evidence/a2/private"
    modes = {
        str(path.relative_to(root)): stat.S_IMODE(path.stat().st_mode)
        for path in [private_root] + [private_root / str(i) for i in (1, 2, 3, 4)]
    }
    visible_clean = True
    forbidden_keys = {"fault_type", "root_module", "oracle", "injector_state"}
    for index in (1, 2, 3, 4):
        visible = root / f"runtime/runs/a2/{index}/visible/o1_tracking_window.json"
        payload = load_json(visible)
        stack = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                visible_clean = visible_clean and not forbidden_keys.intersection(value)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    checks["oracle_isolation"] = {
        "passed": all(mode == 0o700 for mode in modes.values())
        and visible_clean
        and all(item["result"] == "PASS" for item in isolations),
        "private_directory_modes_octal": {key: oct(value) for key, value in modes.items()},
        "visible_payload_forbidden_keys_absent": visible_clean,
    }

    contract = run(
        [
            str(root / "runtime/envs/guardian-py310/bin/python"),
            str(root / "scripts/validate_contracts.py"),
            "--bundle-root",
            str(root),
        ],
        root,
    )
    checks["contract_conformance"] = {
        "passed": contract["return_code"] == 0,
        **contract,
    }

    guardian = run(
        [str(root / "runtime/envs/guardian-py310/bin/python"), "-m", "pytest", "-q"],
        root / "project/Zhijia-Guardian",
    )
    checks["guardian_tests"] = {"passed": guardian["return_code"] == 0, **guardian}

    bridge_diff = run(["git", "diff", "--check"], root / "runtime/bridge/apollo-carla")
    apollo_diff = run(["git", "diff", "--check"], root / "runtime/apollo/application-pnc")
    checks["git_diff_check"] = {
        "passed": bridge_diff["return_code"] == 0 and apollo_diff["return_code"] == 0,
        "bridge": bridge_diff,
        "apollo": apollo_diff,
    }

    shell_syntax = run(["bash", "-c", "bash -n scripts/*.sh"], root)
    python_compile = run(
        [str(root / "runtime/envs/guardian-py310/bin/python"), "-m", "compileall", "-q", "scripts"],
        root,
    )
    shell_lint = run(["bash", "-c", "shellcheck scripts/*.sh"], root)
    checks["static_checks"] = {
        "passed": shell_syntax["return_code"] == 0
        and python_compile["return_code"] == 0
        and shell_lint["return_code"] == 0,
        "shell_syntax": shell_syntax,
        "python_compile": python_compile,
        "shellcheck": shell_lint,
    }

    secret_pattern = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
    secret_hits = []
    scan_roots = [root / name for name in ("coordination", "docs", "project", "scripts", "runtime_state")]
    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 5_000_000:
                continue
            if any(part in {".git", "__pycache__", ".pytest_cache"} for part in path.parts):
                continue
            try:
                text = path.read_text(errors="strict")
            except (UnicodeDecodeError, PermissionError):
                continue
            if secret_pattern.search(text):
                secret_hits.append(str(path.relative_to(root)))
    env_files = [
        str(path.relative_to(root))
        for scan_root in scan_roots
        for path in scan_root.rglob(".env")
        if path.is_file()
    ]
    checks["sensitive_material"] = {
        "passed": not secret_hits and not env_files,
        "secret_pattern_hits": secret_hits,
        "env_files": env_files,
    }

    process_scan = run(
        [
            "bash",
            "-c",
            "ps -eo args= | grep -E 'CarlaUE4-Linux-Shipping|python3 -m carla_bridge.main|a2_control_interposer|modules/common/mainboard/mainboard' | grep -v -E 'grep -E|final_audit.py' || true",
        ],
        root,
    )
    residuals = process_scan["stdout_tail"].strip()
    checks["managed_process_residuals"] = {
        "passed": residuals == "",
        "residuals": residuals,
    }

    result = {
        "schema_version": 1,
        "result": "PASS" if all(item["passed"] for item in checks.values()) else "FAIL",
        "checks": checks,
    }
    atomic_json(args.output, result)
    print(json.dumps({"result": result["result"], "checks": {k: v["passed"] for k, v in checks.items()}}, sort_keys=True))
    raise SystemExit(0 if result["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
