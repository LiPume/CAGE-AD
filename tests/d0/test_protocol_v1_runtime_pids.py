from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "scripts/d0/protocol_v1/capture_runtime_pids.py"
SPEC = importlib.util.spec_from_file_location("capture_runtime_pids", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_stack_pid_parser_accepts_ansi_logs_and_exact_required_names():
    text = "\n".join(
        [
            "[\x1b[1;32mcyber\x1b[0m] INFO Start process [routing] successfully. pid: 101",
            "INFO Start process [old_routing_adapter] successfully. pid: 102",
            "INFO Start process [planning] successfully. pid: 103",
            "INFO Start process [control] successfully. pid: 104",
        ]
    )
    assert MODULE.parse_stack_pids(text) == {"routing": 101, "planning": 103, "control": 104}


def test_stack_pid_parser_fails_closed_when_module_is_missing():
    with pytest.raises(RuntimeError, match="control"):
        MODULE.parse_stack_pids(
            "INFO Start process [routing] successfully. pid: 1\n"
            "INFO Start process [planning] successfully. pid: 2\n"
        )
