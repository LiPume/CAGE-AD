from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from cage_ad.protocol_v1 import (
    NestedSearchMachine,
    ProtocolValidationError,
    SearchEvent,
    SearchPhase,
    load_protocol,
)


ROOT = Path(__file__).resolve().parents[2]


def copy_protocol(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    source = ROOT / "benchmarks/apollo_d0/protocol_v1"
    target = repo / "benchmarks/apollo_d0/protocol_v1"
    target.mkdir(parents=True)
    for path in source.iterdir():
        (target / path.name).write_bytes(path.read_bytes())
    schema = repo / "contracts/d0/DatasetGenerationRecipes.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_bytes((ROOT / "contracts/d0/DatasetGenerationRecipes.schema.json").read_bytes())
    return repo


def mutate_yaml(repo: Path, name: str, transform) -> None:
    path = repo / "benchmarks/apollo_d0/protocol_v1" / name
    value = yaml.safe_load(path.read_text())
    transform(value)
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def test_real_protocol_loads_with_stable_order_and_hashes():
    bundle = load_protocol(ROOT)
    assert bundle.recipe_order == (
        "CAL-F01", "CAL-F02", "CAL-F03", "CAL-F04",
        "CAL-P01", "CAL-P02", "CAL-P03", "CAL-P04",
        "CAL-C01", "CAL-C02", "CAL-C03", "CAL-C04",
    )
    assert len(bundle.file_sha256) == 7
    assert len(bundle.bundle_sha256) == 64


@pytest.mark.parametrize(
    "name,transform,error",
    [
        ("episode_recipes.yaml", lambda d: d["episodes"][0].update(scenario_id="missing"), "unknown scenario"),
        ("episode_recipes.yaml", lambda d: d["formal_seeds_after_freeze"].append(1101), "seeds overlap"),
        ("episode_recipes.yaml", lambda d: d["normative_nested_search"].reverse(), "search program changed"),
        ("fault_recipes.yaml", lambda d: d["faults"]["forecast_stale_or_delayed"]["dose_grid"].reverse(), "weak-to-strong"),
    ],
)
def test_loader_fails_closed_on_cross_registry_corruption(tmp_path, name, transform, error):
    repo = copy_protocol(tmp_path)
    mutate_yaml(repo, name, transform)
    with pytest.raises(ProtocolValidationError, match=error):
        load_protocol(repo)


def test_nested_search_uses_declared_candidate_and_dose_order():
    machine = NestedSearchMachine(load_protocol(ROOT), "CAL-F01")
    assert machine.current_candidate["candidate_id"] == "LBC0"
    state = machine.advance(SearchEvent.NOMINAL_PASSED)
    assert state.phase == SearchPhase.DOSE
    assert machine.current_dose == {"delay_s": 0.5}
    machine.advance(SearchEvent.DOSE_FAILED)
    assert machine.current_dose == {"delay_s": 1.0}
    state = machine.advance(SearchEvent.DOSE_PASSED)
    assert state.phase == SearchPhase.PROBES
    assert state.selected_candidate_id == "LBC0"
    assert state.selected_dose == {"delay_s": 1.0}
    state = machine.advance(SearchEvent.PROBES_VALID, classification="ambiguous_nonselective")
    assert state.phase == SearchPhase.TERMINAL
    assert state.terminal_classification == "ambiguous_nonselective"


def test_nested_search_exhausts_doses_then_candidates_and_never_advances_terminal():
    machine = NestedSearchMachine(load_protocol(ROOT), "CAL-C04")
    for candidate_index in range(3):
        machine.advance(SearchEvent.NOMINAL_PASSED)
        for _ in range(4):
            state = machine.advance(SearchEvent.DOSE_FAILED)
        if candidate_index < 2:
            assert state.phase == SearchPhase.NOMINAL
    assert state.phase == SearchPhase.TERMINAL
    assert state.terminal_classification == "rejected_no_causal_dose"
    with pytest.raises(ProtocolValidationError, match="cannot advance"):
        machine.advance(SearchEvent.NOMINAL_PASSED)


def test_probe_invalid_stops_search_without_trying_stronger_dose():
    machine = NestedSearchMachine(load_protocol(ROOT), "CAL-P03")
    machine.advance(SearchEvent.NOMINAL_PASSED)
    machine.advance(SearchEvent.DOSE_PASSED)
    state = machine.advance(SearchEvent.PROBES_INVALID)
    assert state.terminal_classification == "rejected_probe_invalid"
    assert state.selected_dose == {"time_scale": 0.9}
