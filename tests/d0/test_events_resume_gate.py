from __future__ import annotations

import json
from pathlib import Path

import pytest

from cage_ad.active_diagnosis.catalog import IllegalAction
from cage_ad.active_diagnosis.contracts import ActionType, CostVector, ResponsibilityDomain
from cage_ad.active_diagnosis.coordinator import CentralExecutionGate, ToolExecutionFailed
from cage_ad.active_diagnosis.events import AppendOnlyEventLog, EventLogCorruption
from cage_ad.active_diagnosis.runner import DiagnosisSession
from cage_ad.active_diagnosis.verifier import EvidenceVerifier, RawToolResult

from .conftest import proposal, write_visible


class FixtureExecutor:
    idempotent = True

    def __init__(self, payload: Path, *, fail_after_receipt_once: bool = False) -> None:
        self.payload = payload
        self.fail_after_receipt_once = fail_after_receipt_once
        self.receipts: set[str] = set()
        self.side_effect_count = 0

    def execute(self, proposal, *, idempotency_key: str, maximum_cost) -> RawToolResult:
        first = idempotency_key not in self.receipts
        if first:
            self.receipts.add(idempotency_key)
            self.side_effect_count += 1
            if self.fail_after_receipt_once:
                self.fail_after_receipt_once = False
                raise RuntimeError("simulated crash after durable intervention receipt")
        return RawToolResult(
            evidence_id=f"evidence-{proposal.action_id}",
            semantic_slot="control_target" if proposal.action_id.startswith("I2") else "motion_plan",
            provenance="synthetic_fixture",
            payload_path=self.payload,
            measured_cost=CostVector(
                access="L1",
                bytes=self.payload.stat().st_size,
                runtime_seconds=1,
                intervention_count=1 if proposal.action_id.startswith("I2") else 0,
                risk=1 if proposal.action_id.startswith("I2") else 0,
            ),
            side_effects=("bounded probe",) if proposal.action_id.startswith("I2") else (),
        )


class UnsafeInterventionExecutor(FixtureExecutor):
    idempotent = False


def make_gate(episode, catalog, budget_profile, roots, executors) -> CentralExecutionGate:
    return CentralExecutionGate(
        episode=episode,
        catalog=catalog,
        budget_profile=budget_profile,
        verifier=EvidenceVerifier(roots["visible"], roots["private"]),
        event_log=AppendOnlyEventLog(roots["state"] / "events.jsonl"),
        executors=executors,
    )


def test_event_log_is_idempotent_and_hash_chained(roots) -> None:
    log = AppendOnlyEventLog(roots["state"] / "events.jsonl")
    first = log.append("event-1", "TEST", {"value": 1})
    assert log.append("event-1", "TEST", {"value": 1}) == first
    assert len(log.read()) == 1
    with pytest.raises(ValueError):
        log.append("event-1", "TEST", {"value": 2})


def test_event_log_detects_tampering(roots) -> None:
    path = roots["state"] / "events.jsonl"
    log = AppendOnlyEventLog(path)
    log.append("event-1", "TEST", {"value": 1})
    raw = json.loads(path.read_text())
    raw["payload"]["value"] = 2
    path.write_text(json.dumps(raw) + "\n")
    with pytest.raises(EventLogCorruption):
        log.read()


def test_central_gate_executes_once_and_resume_does_not_recharge(
    episode, catalog, budget_profile, roots
) -> None:
    payload = write_visible(roots["visible"] / "motion.json")
    executor = FixtureExecutor(payload)
    gate = make_gate(episode, catalog, budget_profile, roots, {"O1_motion": executor})
    evidence = gate.execute(proposal("O1_motion"))
    spent = gate.budget.spent
    assert gate.execute(proposal("O1_motion")) == evidence
    assert gate.budget.spent == spent
    assert executor.side_effect_count == 1

    resumed = make_gate(episode, catalog, budget_profile, roots, {"O1_motion": executor})
    assert resumed.execute(proposal("O1_motion")) == evidence
    assert resumed.budget.spent == spent
    assert executor.side_effect_count == 1


def test_crash_resume_reuses_intervention_idempotency_receipt(
    episode, catalog, budget_profile, roots
) -> None:
    payload = write_visible(roots["visible"] / "probe.json")
    executor = FixtureExecutor(payload, fail_after_receipt_once=True)
    gate = make_gate(episode, catalog, budget_profile, roots, {"I2_control": executor})
    intervention = proposal("I2_control", ActionType.INTERVENTION)
    with pytest.raises(RuntimeError, match="simulated crash"):
        gate.execute(intervention)
    assert executor.side_effect_count == 1

    resumed = make_gate(episode, catalog, budget_profile, roots, {"I2_control": executor})
    evidence = resumed.execute(intervention)
    assert evidence.action_id == "I2_control"
    assert executor.side_effect_count == 1
    assert resumed.budget.spent.intervention_count == 1


def test_gate_rejects_non_idempotent_intervention(episode, catalog, budget_profile, roots) -> None:
    payload = write_visible(roots["visible"] / "probe.json")
    gate = make_gate(
        episode,
        catalog,
        budget_profile,
        roots,
        {"I2_control": UnsafeInterventionExecutor(payload)},
    )
    with pytest.raises(ToolExecutionFailed, match="idempotency"):
        gate.execute(proposal("I2_control", ActionType.INTERVENTION))


def test_gate_rejects_policy_invented_action(episode, catalog, budget_profile, roots) -> None:
    gate = make_gate(episode, catalog, budget_profile, roots, {})
    with pytest.raises(IllegalAction):
        gate.execute(proposal("O1_invented"))


def test_gate_rejects_policy_invented_parameters(episode, catalog, budget_profile, roots) -> None:
    gate = make_gate(episode, catalog, budget_profile, roots, {})
    malicious = proposal("O1_motion").model_copy(
        update={"requested_parameters": {"oracle_path": "/private/oracle.json"}}
    )
    with pytest.raises(IllegalAction, match="not declared"):
        gate.execute(malicious)


def test_session_state_resumes_without_second_belief_update(
    episode, catalog, budget_profile, roots
) -> None:
    payload = write_visible(roots["visible"] / "motion.json")
    executor = FixtureExecutor(payload)
    log = AppendOnlyEventLog(roots["state"] / "events.jsonl")
    gate = make_gate(episode, catalog, budget_profile, roots, {"O1_motion": executor})
    session = DiagnosisSession(episode, gate, log)
    likelihood = {
        ResponsibilityDomain.INTERACTION_FORECASTING: 0.1,
        ResponsibilityDomain.MOTION_PLANNING: 0.8,
        ResponsibilityDomain.TRACKING_EXECUTION: 0.1,
    }
    state = session.execute(proposal("O1_motion"), lambda _evidence: likelihood)
    resumed_gate = make_gate(episode, catalog, budget_profile, roots, {"O1_motion": executor})
    resumed = DiagnosisSession(episode, resumed_gate, log)
    same = resumed.execute(proposal("O1_motion"), lambda _evidence: likelihood)
    assert same.posterior == state.posterior
    assert same.step == 1
