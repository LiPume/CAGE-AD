#!/usr/bin/env python3
"""CPU-only source handoff audit; never opens runtime or private oracle payloads."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 1_000_000
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
ALLOWED_LARGE_SUFFIXES: set[str] = set()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_candidates() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / raw.decode() for raw in completed.stdout.split(b"\0") if raw]


def main() -> int:
    errors: list[str] = []
    paths = tracked_candidates()
    forbidden_names = {".env", "id_rsa", "id_ed25519"}
    for path in paths:
        relative = path.relative_to(ROOT)
        if path.name in forbidden_names or path.suffix in {".pem", ".key"}:
            errors.append(f"forbidden sensitive filename: {relative}")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES and path.suffix not in ALLOWED_LARGE_SUFFIXES:
            errors.append(f"large file: {relative} ({size} bytes)")
        if size <= MAX_FILE_BYTES:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"binary file: {relative}")
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(content):
                    errors.append(f"possible secret in {relative}: {pattern.pattern}")

    provenance = yaml.safe_load((ROOT / "artifacts/g0/SOURCE_PROVENANCE.yaml").read_text())
    for name, expected in provenance["d0_design_documents"].items():
        actual = digest(ROOT / "docs/d0" / name)
        if actual != expected:
            errors.append(f"design checksum mismatch: {name}")

    upstreams = sorted((ROOT / "third_party").glob("*/UPSTREAM.yaml"))
    if len(upstreams) != 3:
        errors.append(f"expected 3 UPSTREAM files, found {len(upstreams)}")
    for path in upstreams:
        document = yaml.safe_load(path.read_text())
        for key in ("schema_version", "name", "license"):
            if key not in document:
                errors.append(f"{path.relative_to(ROOT)} missing {key}")

    for patch in sorted((ROOT / "third_party/patches").glob("*.patch")):
        text = patch.read_text()
        if not text.startswith("diff --git ") or "--- a/" not in text or "+++ b/" not in text:
            errors.append(f"invalid textual patch structure: {patch.relative_to(ROOT)}")

    forbidden_runtime_material = ("oracle_private", ".record", ".bag", ".pcd", ".onnx", ".engine")
    for path in paths:
        lowered = str(path.relative_to(ROOT)).lower()
        if any(token in lowered for token in forbidden_runtime_material):
            errors.append(f"forbidden runtime/private material: {path.relative_to(ROOT)}")

    if errors:
        print("source_audit=FAIL", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"source_audit=PASS files={len(paths)} upstreams={len(upstreams)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
