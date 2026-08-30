from __future__ import annotations

import json
from pathlib import Path

import pytest

from cage_ad.protocol_v1.audit import (
    assert_diagnosis_visible_document_safe,
    assert_storage_isolation,
    audit_repository_files,
    audit_runtime_sources,
    audit_visible_tree,
)
from cage_ad.protocol_v1.loader import ProtocolValidationError


ROOT = Path(__file__).resolve().parents[2]


def test_safe_opaque_visible_document_passes():
    assert_diagnosis_visible_document_safe(
        {
            "schema_version": 2,
            "episode_id": "d0v1_9f44db00be62484f",
            "evidence": {"minimum_ttc_s": 3.1, "forecast_samples": []},
        }
    )


@pytest.mark.parametrize(
    "document",
    [
        {"fault_id": "opaque"},
        {"nested": {"candidate_id": "hidden"}},
        {"note": "the source was CAL-F01"},
        {"episode_id": "LBC0"},
        {"description": "forecast_stale_or_delayed"},
        {"companion_linkage": ["x", "y"]},
    ],
)
def test_visible_leakage_fails_closed(document):
    with pytest.raises(ProtocolValidationError, match="leakage"):
        assert_diagnosis_visible_document_safe(document)


def test_visible_tree_rejects_symlinks_and_private_names(tmp_path):
    safe = tmp_path / "safe"
    safe.mkdir()
    (safe / "evidence.json").write_text(json.dumps({"episode_id": "d0v1_deadbeef"}))
    assert audit_visible_tree(safe) == (safe / "evidence.json",)
    (safe / "CAL-F01.json").write_text("{}")
    with pytest.raises(ProtocolValidationError, match="path leaks"):
        audit_visible_tree(safe)
    (safe / "CAL-F01.json").unlink()
    (safe / "link").symlink_to(safe / "evidence.json")
    with pytest.raises(ProtocolValidationError, match="symlink"):
        audit_visible_tree(safe)


def test_storage_roots_must_be_disjoint_and_private(tmp_path):
    repo, data, private = tmp_path / "repo", tmp_path / "data", tmp_path / "private"
    for path in (repo, data, private):
        path.mkdir()
    private.chmod(0o700)
    assert_storage_isolation(repo, data, private)
    private.chmod(0o750)
    with pytest.raises(ProtocolValidationError, match="group or other"):
        assert_storage_isolation(repo, data, private)
    with pytest.raises(ProtocolValidationError, match="overlap"):
        assert_storage_isolation(repo, data, data / "private")


def test_runtime_bindings_use_protocol_v1_and_no_legacy_semantics():
    paths = audit_runtime_sources(ROOT)
    assert len(paths) == 3


def test_repository_audit_detects_secret_and_large_file(tmp_path):
    (tmp_path / "safe.py").write_text("print('safe')\n")
    assert audit_repository_files(tmp_path, maximum_bytes=100)["file_count"] == 1
    (tmp_path / "secret.txt").write_text("-----BEGIN " + "OPENSSH PRIVATE KEY-----\n")
    with pytest.raises(ProtocolValidationError, match="secret"):
        audit_repository_files(tmp_path, maximum_bytes=100)
    (tmp_path / "secret.txt").unlink()
    (tmp_path / "large.bin").write_bytes(b"x" * 101)
    with pytest.raises(ProtocolValidationError, match="large"):
        audit_repository_files(tmp_path, maximum_bytes=100)
