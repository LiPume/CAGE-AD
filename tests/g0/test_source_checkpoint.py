from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def test_design_documents_are_byte_exact() -> None:
    provenance = yaml.safe_load((ROOT / "artifacts/g0/SOURCE_PROVENANCE.yaml").read_text())
    for name, expected in provenance["d0_design_documents"].items():
        actual = hashlib.sha256((ROOT / "docs/d0" / name).read_bytes()).hexdigest()
        assert actual == expected


def test_g0_contract_and_golden_fixture() -> None:
    schema_path = ROOT / "contracts/g0/semantic_slots.schema.json"
    fixture_path = ROOT / "contracts/conformance/golden_inputs/tracking_execution_delayed.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(json.loads(fixture_path.read_text()))


def test_upstream_provenance_resolves_patches() -> None:
    for path in (ROOT / "third_party").glob("*/UPSTREAM.yaml"):
        document = yaml.safe_load(path.read_text())
        if "patch" in document:
            assert (path.parent / document["patch"]).resolve().is_file()


def test_no_historical_source_dependency_in_package_contract() -> None:
    assert not (ROOT / "src").exists() or "Zhijia-Guardian" not in "\n".join(
        path.read_text(errors="ignore") for path in (ROOT / "src").rglob("*") if path.is_file()
    )
