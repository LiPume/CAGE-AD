from __future__ import annotations

import json
from pathlib import Path

import pytest

from cage_ad.protocol_v1.attempts import complete_attempt, prepare_attempt
from cage_ad.protocol_v1.ledger import CalibrationLedger
from cage_ad.protocol_v1.loader import ProtocolValidationError


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "9c28cfdbb744dff44c3eddeb913c0f1d18d28822"


def _roots(tmp_path: Path):
    state = tmp_path / "state"
    data = tmp_path / "data"
    private = tmp_path / "private"
    state.mkdir()
    data.mkdir()
    private.mkdir(mode=0o700)
    return state, data, private


def test_prepare_attempt_uses_private_hmac_identity_and_opaque_visible_manifest(tmp_path):
    state, data, private = _roots(tmp_path)
    first = prepare_attempt(
        repo_root=ROOT,
        state_root=state,
        data_root=data,
        private_oracle_root=private,
        recipe_id="CAL-F01",
        phase="nominal_gate",
        candidate_id="LBC0",
        seed=1101,
        condition="nominal",
        dose=None,
        source_commit=COMMIT,
        recorded_at="2026-08-07T06:00:00Z",
    )
    second = prepare_attempt(
        repo_root=ROOT,
        state_root=state,
        data_root=data,
        private_oracle_root=private,
        recipe_id="CAL-F01",
        phase="nominal_gate",
        candidate_id="LBC0",
        seed=1101,
        condition="nominal",
        dose=None,
        source_commit=COMMIT,
        recorded_at="ignored-by-idempotency",
    )
    assert second.attempt_id == first.attempt_id
    visible_text = (first.visible_root / "episode.json").read_text()
    assert first.attempt_id in visible_text
    for private_value in ("CAL-F01", "LBC0", "forecast_stale_or_delayed", "delay_s"):
        assert private_value not in visible_text
    private_identity = json.loads((first.private_root / "attempt_private.json").read_text())
    assert private_identity["recipe_id"] == "CAL-F01"
    assert (private / "protocol_v1/opaque_id_namespace.key").stat().st_mode & 0o777 == 0o600
    ledger = CalibrationLedger(state / "ledger/attempts.jsonl")
    assert len(ledger.records) == 1 and ledger.pending_attempt_ids() == (first.attempt_id,)


def test_prepare_attempt_validates_seed_dose_and_condition(tmp_path):
    state, data, private = _roots(tmp_path)
    common = dict(
        repo_root=ROOT,
        state_root=state,
        data_root=data,
        private_oracle_root=private,
        recipe_id="CAL-F01",
        phase="dose_gate",
        candidate_id="LBC0",
        source_commit=COMMIT,
    )
    with pytest.raises(ProtocolValidationError, match="seed"):
        prepare_attempt(**common, seed=2101, condition="fault_no_probe", dose={"delay_s": 0.5})
    with pytest.raises(ProtocolValidationError, match="dose"):
        prepare_attempt(**common, seed=1101, condition="fault_no_probe", dose={"delay_s": 9.0})
    with pytest.raises(ProtocolValidationError, match="must not contain"):
        prepare_attempt(**common, seed=1101, condition="nominal", dose={"delay_s": 0.5})


def test_complete_attempt_records_five_layers_hashes_and_resources_once(tmp_path):
    state, data, private = _roots(tmp_path)
    prepared = prepare_attempt(
        repo_root=ROOT,
        state_root=state,
        data_root=data,
        private_oracle_root=private,
        recipe_id="CAL-F01",
        phase="nominal_gate",
        candidate_id="LBC0",
        seed=1101,
        condition="nominal",
        dose=None,
        source_commit=COMMIT,
        recorded_at="2026-08-07T06:00:00Z",
    )
    (prepared.private_root / "run_metrics.json").write_text(
        json.dumps(
            {
                "infrastructure_valid": True,
                "safety_outcome": {"collision_count": 0, "minimum_ttc_s": 3.5},
                "task_outcome": {"route_completion": 0.8, "forward_progress_m": 70.0, "timeout": True},
            }
        )
    )
    (prepared.private_root / "scenario_stats.json").write_text(json.dumps({"injector_exception": None}))
    (prepared.private_root / "interposer_stats.json").write_text(
        json.dumps({"injector_exception": None, "activation_observations": []})
    )
    (prepared.private_root / "resource_usage.json").write_text(
        json.dumps({"wall_seconds": 50.0, "powered_on_seconds": 45.0})
    )
    result = complete_attempt(
        repo_root=ROOT,
        state_root=state,
        data_root=data,
        private_oracle_root=private,
        attempt_id=prepared.attempt_id,
        recorded_at="2026-08-07T06:01:00Z",
    )
    assert result.status == "completed" and result.runtime_valid
    assert set(result.five_layer_metrics) == {
        "infrastructure_valid",
        "mechanism_activated",
        "safety_outcome",
        "task_outcome",
        "attribution_outcome",
    }
    assert result.five_layer_metrics["mechanism_activated"] is None
    assert result.powered_on_seconds == 45.0
    assert any(key.endswith("run_metrics.json") for key in result.output_sha256)
    duplicate = complete_attempt(
        repo_root=ROOT,
        state_root=state,
        data_root=data,
        private_oracle_root=private,
        attempt_id=prepared.attempt_id,
    )
    assert duplicate == result
    ledger = CalibrationLedger(state / "ledger/attempts.jsonl")
    assert len(ledger.records) == 2 and ledger.pending_attempt_ids() == ()


def test_fault_attempt_computes_activation_from_private_observations(tmp_path):
    state, data, private = _roots(tmp_path)
    prepared = prepare_attempt(
        repo_root=ROOT,
        state_root=state,
        data_root=data,
        private_oracle_root=private,
        recipe_id="CAL-F01",
        phase="dose_gate",
        candidate_id="LBC0",
        seed=1101,
        condition="fault_no_probe",
        dose={"delay_s": 0.5},
        source_commit=COMMIT,
        recorded_at="2026-08-07T06:00:00Z",
    )
    (prepared.private_root / "run_metrics.json").write_text(
        json.dumps(
            {
                "infrastructure_valid": True,
                "safety_outcome": {"collision_count": 0, "minimum_ttc_s": 2.5},
                "task_outcome": {"route_completion": 0.5, "forward_progress_m": 40.0, "timeout": True},
            }
        )
    )
    (prepared.private_root / "scenario_stats.json").write_text("{}")
    (prepared.private_root / "interposer_stats.json").write_text(
        json.dumps(
            {
                "activation_observations": [
                    {"simulator_time_s": time, "metric_value": 0.5, "transform_residual": None}
                    for time in (5.0, 6.0, 7.0, 8.0, 9.0)
                ]
            }
        )
    )
    (prepared.private_root / "resource_usage.json").write_text(
        json.dumps({"wall_seconds": 40.0, "powered_on_seconds": 35.0})
    )
    result = complete_attempt(
        repo_root=ROOT,
        state_root=state,
        data_root=data,
        private_oracle_root=private,
        attempt_id=prepared.attempt_id,
    )
    assert result.five_layer_metrics["mechanism_activated"]["activated"]
