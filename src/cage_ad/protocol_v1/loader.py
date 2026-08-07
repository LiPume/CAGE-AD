"""Fail-closed loader for the normative Apollo D0 protocol-v1 registries."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import jsonschema
import yaml


PROTOCOL_VERSION = "cage-ad-d0-protocol-v1"
REGISTRY_FILES = (
    "scenario_recipes.yaml",
    "fault_recipes.yaml",
    "probe_recipes.yaml",
    "episode_recipes.yaml",
    "quality_gates.yaml",
    "literature_provenance.yaml",
)

EXPECTED_SEARCH_PROGRAM = (
    "for_candidate_in_declared_order_run_nominal_gate",
    "if_nominal_gate_fails_record_and_continue_next_candidate",
    "for_dose_in_declared_weak_to_strong_order_run_activation_degradation_temporal_and_collision_identity_gates",
    "if_dose_gate_fails_record_and_continue_next_dose",
    "on_first_dose_passing_pre_probe_gates_run_all_three_probes_and_stop_all_candidate_and_dose_search",
    "if_probe_evidence_is_valid_apply_complete_classification_tree_identifiable_or_ambiguous",
    "if_probe_evidence_is_invalid_classify_rejected_probe_invalid",
    "if_all_doses_fail_for_candidate_continue_next_candidate",
    "if_all_candidates_exhausted_classify_rejected_no_causal_dose",
    "never_try_another_candidate_or_stronger_dose_after_a_causally_valid_dose_is_found",
)


class ProtocolValidationError(ValueError):
    """The registry cannot safely drive execution."""


@dataclass(frozen=True)
class ProtocolBundle:
    root: Path
    scenarios: Mapping[str, Any]
    faults: Mapping[str, Any]
    probes: Mapping[str, Any]
    episodes: Mapping[str, Any]
    quality_gates: Mapping[str, Any]
    literature: Mapping[str, Any]
    file_sha256: Mapping[str, str]
    bundle_sha256: str

    @property
    def recipe_order(self) -> tuple[str, ...]:
        return tuple(item["recipe_id"] for item in self.episodes["episodes"])

    def recipe(self, recipe_id: str) -> Mapping[str, Any]:
        matches = [item for item in self.episodes["episodes"] if item["recipe_id"] == recipe_id]
        if len(matches) != 1:
            raise ProtocolValidationError(f"unknown or duplicate recipe: {recipe_id}")
        return MappingProxyType(matches[0])


def _load_mapping(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ProtocolValidationError(f"registry must not be a symlink: {path}")
    try:
        value = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ProtocolValidationError(f"cannot load registry {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolValidationError(f"registry root must be a mapping: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolValidationError(message)


def _strictly_monotone(values: list[float], *, increasing: bool) -> bool:
    pairs = zip(values, values[1:])
    return all(left < right if increasing else left > right for left, right in pairs)


def _validate_dose_order(fault_id: str, recipe: Mapping[str, Any]) -> None:
    grid = recipe.get("dose_grid")
    _require(isinstance(grid, list) and len(grid) == 4, f"{fault_id}: expected four doses")
    _require(all(isinstance(item, dict) and len(item) == 1 for item in grid), f"{fault_id}: dose must have one field")
    keys = {next(iter(item)) for item in grid}
    _require(len(keys) == 1, f"{fault_id}: mixed dose fields")
    key = next(iter(keys))
    try:
        values = [float(item[key]) for item in grid]
    except (TypeError, ValueError) as exc:
        raise ProtocolValidationError(f"{fault_id}: non-numeric dose") from exc
    descending = fault_id in {
        "planning_unsafe_cost_or_speed_bias",
        "control_gain_saturation_tracking_bias",
    }
    _require(
        _strictly_monotone(values, increasing=not descending),
        f"{fault_id}: dose grid is not declared weak-to-strong",
    )


def _validate_cross_references(documents: Mapping[str, dict[str, Any]]) -> None:
    scenarios_doc = documents["scenario_recipes.yaml"]
    faults_doc = documents["fault_recipes.yaml"]
    probes_doc = documents["probe_recipes.yaml"]
    episodes_doc = documents["episode_recipes.yaml"]
    gates = documents["quality_gates.yaml"]

    for name, document in documents.items():
        _require(document.get("protocol_version") == PROTOCOL_VERSION, f"{name}: protocol version mismatch")

    scenarios = scenarios_doc.get("scenarios")
    faults = faults_doc.get("faults")
    probes = probes_doc.get("probes")
    _require(isinstance(scenarios, dict) and scenarios, "scenario registry is empty")
    _require(isinstance(faults, dict) and len(faults) == 6, "fault registry must declare six faults")
    _require(isinstance(probes, dict) and set(probes) == {"probe_forecasting", "probe_planning", "probe_control"}, "probe registry mismatch")

    candidate_ids: list[str] = []
    for scenario_id, scenario in scenarios.items():
        candidates = scenario.get("candidate_order")
        _require(isinstance(candidates, list) and len(candidates) == 3, f"{scenario_id}: expected three candidates")
        ids = [item.get("candidate_id") for item in candidates]
        _require(all(isinstance(item, str) and item for item in ids), f"{scenario_id}: invalid candidate id")
        _require(len(set(ids)) == 3, f"{scenario_id}: duplicate candidate id")
        candidate_ids.extend(ids)
    _require(len(candidate_ids) == len(set(candidate_ids)), "candidate ids must be globally unique")

    for fault_id, fault in faults.items():
        _validate_dose_order(fault_id, fault)
        _require(bool(fault.get("target_fields")), f"{fault_id}: target fields missing")
        _require(bool(fault.get("activation_signature")), f"{fault_id}: activation signature missing")

    recipe_rows = episodes_doc.get("episodes")
    _require(isinstance(recipe_rows, list) and len(recipe_rows) == 12, "episode registry must contain twelve recipes")
    recipe_ids = [item.get("recipe_id") for item in recipe_rows]
    _require(len(set(recipe_ids)) == 12, "recipe ids must be unique")
    for item in recipe_rows:
        _require(item.get("scenario_id") in scenarios, f"{item.get('recipe_id')}: unknown scenario")
        _require(item.get("fault_id") in faults, f"{item.get('recipe_id')}: unknown fault")

    search_program = tuple(episodes_doc.get("normative_nested_search", ()))
    _require(search_program == EXPECTED_SEARCH_PROGRAM, "normative nested-search program changed or reordered")

    calibration = set(episodes_doc.get("calibration_seeds", ()))
    formal = set(episodes_doc.get("formal_seeds_after_freeze", ()))
    regression = set(probes_doc.get("common", {}).get("fault_free_regression_seeds", ()))
    _require(calibration and formal and regression, "seed registries must be non-empty")
    _require(calibration.isdisjoint(formal), "calibration and formal seeds overlap")
    _require(calibration.isdisjoint(regression), "calibration and regression seeds overlap")
    _require(formal.isdisjoint(regression), "formal and regression seeds overlap")

    _require(
        faults_doc.get("common", {}).get("injection_start") == probes_doc.get("common", {}).get("start_s")
        and faults_doc.get("common", {}).get("injection_end") == probes_doc.get("common", {}).get("end_s"),
        "fault and probe trigger windows differ",
    )
    _require(set(gates.get("classification", {})) == {"identifiable", "ambiguous", "rejected"}, "classification roots mismatch")
    _require(bool(gates.get("complete_classification_tree", {}).get("precedence")), "classification precedence missing")


def load_protocol(repo_root: Path) -> ProtocolBundle:
    repo_root = repo_root.resolve()
    root = repo_root / "benchmarks/apollo_d0/protocol_v1"
    schema_path = repo_root / "contracts/d0/DatasetGenerationRecipes.schema.json"
    _require(root.is_dir(), f"protocol root missing: {root}")
    documents = {name: _load_mapping(root / name) for name in REGISTRY_FILES}
    try:
        schema = json.loads(schema_path.read_text())
        jsonschema.Draft202012Validator(schema).validate(documents["episode_recipes.yaml"])
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError, jsonschema.SchemaError) as exc:
        raise ProtocolValidationError(f"episode schema validation failed: {exc}") from exc
    _validate_cross_references(documents)

    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in REGISTRY_FILES}
    hashes[schema_path.relative_to(repo_root).as_posix()] = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    accumulator = hashlib.sha256()
    for name, digest in sorted(hashes.items()):
        accumulator.update(name.encode())
        accumulator.update(b"\0")
        accumulator.update(digest.encode())
        accumulator.update(b"\n")
    return ProtocolBundle(
        root=root,
        scenarios=MappingProxyType(documents["scenario_recipes.yaml"]),
        faults=MappingProxyType(documents["fault_recipes.yaml"]),
        probes=MappingProxyType(documents["probe_recipes.yaml"]),
        episodes=MappingProxyType(documents["episode_recipes.yaml"]),
        quality_gates=MappingProxyType(documents["quality_gates.yaml"]),
        literature=MappingProxyType(documents["literature_provenance.yaml"]),
        file_sha256=MappingProxyType(hashes),
        bundle_sha256=accumulator.hexdigest(),
    )
