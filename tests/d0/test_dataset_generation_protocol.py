from __future__ import annotations

from collections import Counter
from pathlib import Path

import json
import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "benchmarks/apollo_d0/protocol_v1"
DOC = ROOT / "docs/dataset/CAGE_AD_D0_GENERATION_PROTOCOL.md"
SCHEMA = ROOT / "contracts/d0/DatasetGenerationRecipes.schema.json"


def _yaml(name: str) -> dict:
    return yaml.safe_load((PROTOCOL / name).read_text())


def test_episode_registry_matches_schema_and_has_unique_ids() -> None:
    registry = _yaml("episode_recipes.yaml")
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text())).validate(registry)
    ids = [item["recipe_id"] for item in registry["episodes"]]
    assert len(ids) == len(set(ids)) == 12
    assert set(registry["calibration_seeds"]).isdisjoint(registry["formal_seeds_after_freeze"])


def test_every_episode_references_declared_scenario_and_fault() -> None:
    episodes = _yaml("episode_recipes.yaml")["episodes"]
    scenarios = set(_yaml("scenario_recipes.yaml")["scenarios"])
    faults = set(_yaml("fault_recipes.yaml")["faults"])
    assert {item["scenario_id"] for item in episodes} <= scenarios
    assert {item["fault_id"] for item in episodes} <= faults
    assert Counter(item["fault_id"] for item in episodes) == Counter({fault: 2 for fault in faults})


def test_scenario_search_and_fault_dose_are_fully_declared() -> None:
    scenarios = _yaml("scenario_recipes.yaml")["scenarios"]
    for scenario in scenarios.values():
        candidates = scenario["candidate_order"]
        assert len(candidates) == 3
        assert len({item["candidate_id"] for item in candidates}) == 3

    faults = _yaml("fault_recipes.yaml")["faults"]
    for fault in faults.values():
        assert len(fault["dose_grid"]) == 4
        assert fault["target_fields"]
        assert fault["activation_signature"]["required_fraction_of_window"] >= 0.6


def test_protocol_separates_infrastructure_safety_task_and_attribution() -> None:
    gates = _yaml("quality_gates.yaml")
    assert set(gates["outcome_layers"]) == {
        "infrastructure_valid",
        "safety_outcome",
        "task_outcome",
        "mechanism_outcome",
    }
    assert set(gates["classification"]) == {"identifiable", "ambiguous", "rejected"}
    assert "route_request_failure" in gates["outcome_layers"]["infrastructure_valid"]["invalid_examples"]


def test_probes_are_domain_complete_fixed_and_non_oracle() -> None:
    registry = _yaml("probe_recipes.yaml")
    probes = registry["probes"]
    assert set(probes) == {"probe_forecasting", "probe_planning", "probe_control"}
    assert {item["responsibility_domain"] for item in probes.values()} == {
        "interaction_forecasting",
        "motion_planning",
        "tracking_execution",
    }
    assert registry["common"]["receives_fault_id"] is False
    assert registry["common"]["receives_simulator_future_truth"] is False
    assert len(registry["common"]["fault_free_regression_seeds"]) == 5


def test_human_protocol_covers_every_recipe_and_source() -> None:
    text = DOC.read_text()
    episodes = _yaml("episode_recipes.yaml")["episodes"]
    sources = _yaml("literature_provenance.yaml")["sources"]
    missing = [item["recipe_id"] for item in episodes if item["recipe_id"] not in text]
    missing += [source for source in sources if source.replace("_", " ") not in text]
    assert missing == []
