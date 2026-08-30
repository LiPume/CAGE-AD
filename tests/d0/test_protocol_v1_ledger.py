from __future__ import annotations

import json
from pathlib import Path

import pytest

from cage_ad.protocol_v1.ledger import (
    AttemptPlan,
    AttemptResult,
    CalibrationLedger,
)
from cage_ad.protocol_v1.loader import ProtocolValidationError, load_protocol
from cage_ad.protocol_v1.search import SearchEvent, SearchPhase


ROOT = Path(__file__).resolve().parents[2]


def _plan(attempt_id: str = "opaque-001") -> AttemptPlan:
    return AttemptPlan(
        attempt_id=attempt_id,
        recipe_id="CAL-F01",
        phase="nominal_gate",
        candidate_id="LBC0",
        seed=1101,
        condition="nominal",
        source_commit="a" * 40,
        protocol_bundle_sha256="b" * 64,
        config_sha256="c" * 64,
        command=["python", "-m", "cage_ad.protocol_v1.runtime", "--opaque-run-id", attempt_id],
    )


def _result(attempt_id: str = "opaque-001") -> AttemptResult:
    return AttemptResult(
        attempt_id=attempt_id,
        status="completed",
        runtime_valid=True,
        five_layer_metrics={
            "infrastructure_valid": True,
            "mechanism_activated": None,
            "safety_outcome": {"collision_count": 0, "minimum_ttc_s": 3.2},
            "task_outcome": {"route_completion": 1.0},
            "attribution_outcome": None,
        },
        wall_seconds=32.0,
        powered_on_seconds=45.0,
        incremental_storage_bytes=1234,
        output_sha256={"private_metrics.json": "d" * 64},
    )


def test_attempt_lifecycle_is_hash_chained_idempotent_and_resumable(tmp_path):
    path = tmp_path / "calibration.jsonl"
    ledger = CalibrationLedger(path)
    first = ledger.plan_attempt(_plan(), recorded_at="2026-08-07T05:00:00Z")
    duplicate = ledger.plan_attempt(_plan(), recorded_at="a-different-time-is-ignored")
    assert duplicate == first
    assert ledger.pending_attempt_ids() == ("opaque-001",)
    result = ledger.complete_attempt(_result(), recorded_at="2026-08-07T05:01:00Z")
    assert result.previous_sha256 == first.event_sha256
    assert ledger.pending_attempt_ids() == ()
    resumed = CalibrationLedger(path)
    assert resumed.records == ledger.records
    assert path.stat().st_mode & 0o777 == 0o600


def test_attempt_plan_conflict_and_unplanned_completion_fail_closed(tmp_path):
    ledger = CalibrationLedger(tmp_path / "calibration.jsonl")
    ledger.plan_attempt(_plan(), recorded_at="2026-08-07T05:00:00Z")
    changed = _plan()
    changed = AttemptPlan(**{**changed.__dict__, "seed": 1102})
    with pytest.raises(ProtocolValidationError, match="changed"):
        ledger.plan_attempt(changed, recorded_at="2026-08-07T05:00:01Z")
    with pytest.raises(ProtocolValidationError, match="unplanned"):
        ledger.complete_attempt(_result("not-planned"), recorded_at="2026-08-07T05:01:00Z")


def test_ledger_detects_payload_tampering_and_chain_truncation_shape(tmp_path):
    path = tmp_path / "calibration.jsonl"
    ledger = CalibrationLedger(path)
    ledger.plan_attempt(_plan(), recorded_at="2026-08-07T05:00:00Z")
    raw = json.loads(path.read_text())
    raw["payload"]["seed"] = 9999
    path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ProtocolValidationError, match="hash mismatch"):
        CalibrationLedger(path)


def test_search_transitions_replay_only_the_normative_state_machine(tmp_path):
    bundle = load_protocol(ROOT)
    ledger = CalibrationLedger(tmp_path / "calibration.jsonl")
    after_nominal = ledger.advance_search_once(
        bundle,
        "CAL-F01",
        SearchEvent.NOMINAL_PASSED,
        transition_id="nominal-LBC0",
        recorded_at="2026-08-07T05:00:00Z",
    )
    assert after_nominal.phase == SearchPhase.DOSE and after_nominal.dose_index == 0
    duplicate = ledger.advance_search_once(
        bundle,
        "CAL-F01",
        SearchEvent.NOMINAL_PASSED,
        transition_id="nominal-LBC0",
        recorded_at="ignored",
    )
    assert duplicate == after_nominal
    after_dose = ledger.advance_search_once(
        bundle,
        "CAL-F01",
        SearchEvent.DOSE_PASSED,
        transition_id="dose-LBC0-0",
        recorded_at="2026-08-07T05:01:00Z",
    )
    assert after_dose.phase == SearchPhase.PROBES
    assert after_dose.selected_dose == {"delay_s": 0.5}
    assert CalibrationLedger(ledger.path).replay_search(bundle, "CAL-F01").snapshot == after_dose


def test_search_replay_detects_manual_state_forgery_even_with_rehashed_line(tmp_path):
    bundle = load_protocol(ROOT)
    path = tmp_path / "calibration.jsonl"
    ledger = CalibrationLedger(path)
    ledger.advance_search_once(
        bundle,
        "CAL-F01",
        SearchEvent.NOMINAL_PASSED,
        transition_id="nominal-LBC0",
        recorded_at="2026-08-07T05:00:00Z",
    )
    record = ledger.records[0].to_dict()
    record["payload"]["after"]["dose_index"] = 3
    unsigned = {key: value for key, value in record.items() if key != "event_sha256"}
    import hashlib

    record["event_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    forged = CalibrationLedger(path)
    with pytest.raises(ProtocolValidationError, match="after-state mismatch"):
        forged.replay_search(bundle, "CAL-F01")
