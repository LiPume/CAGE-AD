from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from cage_ad.active_diagnosis.contracts import CostVector
from cage_ad.active_diagnosis.verifier import EvidenceRejected, EvidenceVerifier, RawToolResult

from .conftest import write_visible


def raw(path: Path) -> RawToolResult:
    return RawToolResult(
        evidence_id="opaque-evidence-001",
        semantic_slot="motion_plan",
        provenance="synthetic_fixture",
        payload_path=path,
        measured_cost=CostVector(access="L1", bytes=path.stat().st_size),
    )


def test_verifier_accepts_visible_checksum_bound_json(roots) -> None:
    path = write_visible(roots["visible"] / "payload.json")
    verified = EvidenceVerifier(roots["visible"], roots["private"]).verify("O1", raw(path))
    assert verified.payload_ref.size_bytes == path.stat().st_size
    assert len(verified.payload_ref.sha256) == 64


@pytest.mark.parametrize(
    "key",
    ["fault_type", "responsibility_domain", "oracle", "injector_state", "scenario_parent"],
)
def test_verifier_rejects_forbidden_keys(roots, key: str) -> None:
    path = write_visible(roots["visible"] / "payload.json", {"summary": {key: "secret"}})
    with pytest.raises(EvidenceRejected, match="forbidden key"):
        EvidenceVerifier(roots["visible"], roots["private"]).verify("O1", raw(path))


def test_verifier_rejects_private_and_outside_paths(roots, tmp_path) -> None:
    private = write_visible(roots["private"] / "payload.json")
    outside = write_visible(tmp_path / "outside.json")
    verifier = EvidenceVerifier(roots["visible"], roots["private"])
    with pytest.raises(EvidenceRejected, match="private-oracle"):
        verifier.verify("O1", raw(private))
    with pytest.raises(EvidenceRejected, match="outside"):
        verifier.verify("O1", raw(outside))


@pytest.mark.skipif(os.geteuid() != 0, reason="physical UID permission test requires root")
def test_private_oracle_is_unreadable_to_diagnosis_uid(roots) -> None:
    oracle = roots["private"] / "oracle.json"
    oracle.write_text(json.dumps({"responsibility_domain": "motion_planning"}))
    oracle.chmod(0o600)
    completed = subprocess.run(
        [
            "setpriv",
            "--reuid=65534",
            "--regid=65534",
            "--clear-groups",
            "/usr/bin/head",
            "-c",
            "1",
            str(oracle),
        ],
        check=False,
        capture_output=True,
    )
    assert completed.returncode != 0
