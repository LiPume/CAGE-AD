"""Deterministic schema, permission, provenance, and checksum verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ArtifactReference, CostVector, VerifiedEvidence


FORBIDDEN_KEYS = frozenset(
    {
        "fault",
        "fault_type",
        "fault_name",
        "fault_config",
        "responsibility_domain",
        "ground_truth",
        "gt",
        "injector",
        "injector_state",
        "injector_path",
        "oracle",
        "oracle_ref",
        "private_oracle",
        "scenario_parent",
        "split_parent",
    }
)
FORBIDDEN_PATH_PARTS = frozenset({"private", "oracle", "injector", "ground_truth"})


@dataclass(frozen=True)
class RawToolResult:
    evidence_id: str
    semantic_slot: str
    provenance: str
    payload_path: Path
    measured_cost: CostVector
    side_effects: tuple[str, ...] = ()
    tool_success: bool = True


class EvidenceRejected(RuntimeError):
    pass


def _scan_keys(value: Any, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_KEYS:
                raise EvidenceRejected(f"forbidden key at {location}: {normalized}")
            _scan_keys(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_keys(child, f"{location}[{index}]")


class EvidenceVerifier:
    def __init__(self, visible_root: Path, private_oracle_root: Path) -> None:
        self.visible_root = visible_root.resolve()
        self.private_oracle_root = private_oracle_root.resolve()

    def verify(self, action_id: str, result: RawToolResult) -> VerifiedEvidence:
        if not result.tool_success:
            raise EvidenceRejected("tool did not report success")
        payload = result.payload_path.resolve(strict=True)
        if payload == self.private_oracle_root or self.private_oracle_root in payload.parents:
            raise EvidenceRejected("private-oracle payload cannot be verified as visible evidence")
        if self.visible_root not in payload.parents:
            raise EvidenceRejected("payload is outside diagnosis-visible root")
        relative = payload.relative_to(self.visible_root)
        if any(part.lower() in FORBIDDEN_PATH_PARTS for part in relative.parts):
            raise EvidenceRejected("payload path contains a forbidden private marker")
        raw = payload.read_bytes()
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvidenceRejected("visible payload must be valid JSON") from exc
        _scan_keys(decoded)
        reference = ArtifactReference(
            relative_path=relative.as_posix(),
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )
        return VerifiedEvidence(
            action_id=action_id,
            evidence_id=result.evidence_id,
            semantic_slot=result.semantic_slot,
            provenance=result.provenance,
            side_effects=list(result.side_effects),
            measured_cost=result.measured_cost,
            payload_ref=reference,
        )
