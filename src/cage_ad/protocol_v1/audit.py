"""Fail-closed leakage, source, secret, and repository-size audits."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .loader import ProtocolValidationError


FORBIDDEN_VISIBLE_KEYS = {
    "recipe_id",
    "fault_id",
    "fault_mechanism",
    "responsibility_domain",
    "candidate_id",
    "candidate",
    "dose",
    "trigger_window",
    "companion_linkage",
    "correct_probe_role",
    "wrong_probe_roles",
    "private_oracle",
    "scenario_id",
}
FORBIDDEN_VISIBLE_VALUE_PATTERNS = (
    re.compile(r"\bCAL-[FPC]\d{2}\b", re.IGNORECASE),
    re.compile(r"\b(?:LBC|LBM|CIE|CIL)[0-2]\b", re.IGNORECASE),
    re.compile(r"\b(?:forecast_stale_or_delayed|forecast_heading_or_maneuver_bias|planning_constraint_omitted|planning_unsafe_cost_or_speed_bias|control_command_transport_delay|control_gain_saturation_tracking_bias)\b"),
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
)
LEGACY_RUNTIME_SYMBOLS = {
    "constant_velocity_probe",
    "bounded_brake_probe",
    "safety_envelope_probe",
    "forecast_fault",
    "planning_fault",
    "control_fault",
    "scenario_kind",
}


def _walk(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield path, str(key), nested
            yield from _walk(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk(nested, f"{path}[{index}]")


def assert_diagnosis_visible_document_safe(document: Mapping[str, Any]) -> None:
    violations: list[str] = []
    for path, key, value in _walk(document):
        if key.lower() in FORBIDDEN_VISIBLE_KEYS:
            violations.append(f"{path}.{key}: forbidden key")
        if isinstance(value, str) and any(pattern.search(value) for pattern in FORBIDDEN_VISIBLE_VALUE_PATTERNS):
            violations.append(f"{path}.{key}: forbidden semantic value")
    if violations:
        raise ProtocolValidationError("diagnosis-visible leakage: " + "; ".join(violations))


def audit_visible_tree(root: Path) -> tuple[Path, ...]:
    if not root.exists() or root.is_symlink():
        raise ProtocolValidationError("visible evidence root is missing or a symlink")
    checked: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ProtocolValidationError(f"visible evidence contains a symlink: {path}")
        if path.is_dir():
            continue
        if any(pattern.search(path.as_posix()) for pattern in FORBIDDEN_VISIBLE_VALUE_PATTERNS):
            raise ProtocolValidationError(f"visible evidence path leaks a private identifier: {path}")
        if path.suffix == ".json":
            try:
                value = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise ProtocolValidationError(f"invalid visible JSON: {path}") from exc
            if not isinstance(value, dict):
                raise ProtocolValidationError(f"visible JSON root is not a mapping: {path}")
            assert_diagnosis_visible_document_safe(value)
        checked.append(path)
    return tuple(checked)


def assert_storage_isolation(repo_root: Path, data_root: Path, private_oracle_root: Path) -> None:
    repo, data, private = (path.resolve() for path in (repo_root, data_root, private_oracle_root))
    if private == repo or repo in private.parents or private in repo.parents:
        raise ProtocolValidationError("private oracle and Git repository overlap")
    if private == data or data in private.parents or private in data.parents:
        raise ProtocolValidationError("private oracle and diagnosis-visible data overlap")
    if private.exists() and private.stat().st_mode & 0o077:
        raise ProtocolValidationError("private oracle root is accessible to group or other users")


def audit_runtime_sources(repo_root: Path) -> tuple[Path, ...]:
    paths = (
        repo_root / "src/cage_ad/adapters/apollo_d0/scenario_runtime.py",
        repo_root / "src/cage_ad/adapters/apollo_d0/interposer_runtime.py",
        repo_root / "src/cage_ad/adapters/apollo_d0/run_runtime.py",
    )
    violations = []
    for path in paths:
        content = path.read_text()
        for symbol in LEGACY_RUNTIME_SYMBOLS:
            if symbol in content:
                violations.append(f"{path.name}:{symbol}")
        if "protocol_v1" not in content or "load_protocol" not in content:
            violations.append(f"{path.name}:missing protocol-v1 loader binding")
    if violations:
        raise ProtocolValidationError("legacy or unbound runtime source: " + ", ".join(violations))
    return paths


def audit_repository_files(repo_root: Path, *, maximum_bytes: int = 1_000_000) -> dict[str, int]:
    excluded_roots = {".git", ".pytest_cache", "__pycache__"}
    file_count = total_bytes = 0
    violations: list[str] = []
    for path in sorted(repo_root.rglob("*")):
        relative = path.relative_to(repo_root)
        if any(part in excluded_roots for part in relative.parts) or not path.is_file():
            continue
        size = path.stat().st_size
        file_count += 1
        total_bytes += size
        if size > maximum_bytes:
            violations.append(f"large:{relative}:{size}")
            continue
        content = path.read_bytes()
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            violations.append(f"secret:{relative}")
    if violations:
        raise ProtocolValidationError("repository audit failed: " + ", ".join(violations))
    return {"file_count": file_count, "total_bytes": total_bytes, "maximum_file_bytes": maximum_bytes}
