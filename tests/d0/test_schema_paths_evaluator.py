from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cage_ad.active_diagnosis.contracts import (
    ActionProposal,
    DiagnosisResult,
    DiagnosticState,
    EpisodeSpec,
    VerifiedEvidence,
)
from cage_ad.active_diagnosis.paths import RuntimePaths


ROOT = Path(__file__).resolve().parents[2]
MODELS = (EpisodeSpec, DiagnosticState, ActionProposal, VerifiedEvidence, DiagnosisResult)


def test_checked_in_json_schemas_match_pydantic_models() -> None:
    for model in MODELS:
        path = ROOT / "contracts/d0" / f"{model.__name__}.schema.json"
        checked_in = json.loads(path.read_text())
        Draft202012Validator.check_schema(checked_in)
        assert checked_in == model.model_json_schema()


def test_runtime_paths_require_four_environment_roots(monkeypatch, tmp_path) -> None:
    for name in (
        "CAGE_RUNTIME_ROOT",
        "CAGE_STATE_ROOT",
        "CAGE_DATA_ROOT",
        "CAGE_PRIVATE_ORACLE_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="missing required"):
        RuntimePaths.from_environment()

    roots = [tmp_path / name for name in ("runtime", "state", "data", "oracle")]
    for name, path in zip(
        ("CAGE_RUNTIME_ROOT", "CAGE_STATE_ROOT", "CAGE_DATA_ROOT", "CAGE_PRIVATE_ORACLE_ROOT"),
        roots,
    ):
        monkeypatch.setenv(name, str(path))
    paths = RuntimePaths.from_environment()
    paths.ensure_directories()
    assert paths.private_oracle_root.stat().st_mode & 0o777 == 0o700


def test_private_root_must_not_overlap_visible_roots(tmp_path) -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        RuntimePaths(tmp_path, tmp_path / "state", tmp_path / "data", tmp_path / "private").assert_separated()


def test_diagnosis_package_has_no_private_evaluator_import() -> None:
    package = ROOT / "src/cage_ad/active_diagnosis"
    text = "\n".join(path.read_text() for path in package.glob("*.py"))
    assert "private_evaluator" not in text
    assert "CAGE_PRIVATE_ORACLE_ROOT" not in text.replace(
        '"CAGE_PRIVATE_ORACLE_ROOT",', ""
    )


def test_evaluator_refuses_to_run_before_diagnosis_exit(tmp_path) -> None:
    diagnosis = tmp_path / "diagnosis.json"
    oracle = tmp_path / "oracle.json"
    diagnosis.write_text(json.dumps({"episode_id": "opaque", "prediction_set": ["motion_planning"]}))
    oracle.write_text(json.dumps({"responsibility_domain": "motion_planning"}))
    completed = subprocess.run(
        [
            os.environ.get("PYTHON", "python3"),
            str(ROOT / "scripts/d0/private_evaluator.py"),
            "--diagnosis-result",
            str(diagnosis),
            "--private-oracle",
            str(oracle),
            "--diagnosis-exited-marker",
            str(tmp_path / "missing.marker"),
            "--output",
            str(tmp_path / "evaluation.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert not (tmp_path / "evaluation.json").exists()
