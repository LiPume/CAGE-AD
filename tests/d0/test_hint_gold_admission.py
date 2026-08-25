from __future__ import annotations

from copy import deepcopy

import pytest

from cage_ad.benchmark_construction.admission import AdmissionError, evaluate_candidate


SHA = "a" * 64


def candidate() -> dict:
    return {
        "schema_version": 1,
        "candidate_id": "opaque-gold-001",
        "fault_implementation_sha256": SHA,
        "reference_runs": [
            {
                "run_id": f"reference-{index}",
                "infrastructure_valid": True,
                "task_failure": False,
                "oracle_hidden_from_diagnosis": True,
                "evidence_sha256": SHA,
            }
            for index in range(3)
        ],
        "faulty_runs": [
            {
                "run_id": f"faulty-{index}",
                "infrastructure_valid": True,
                "task_failure": True,
                "mechanism_confirmed": True,
                "mechanism_activated_at_s": 4.0,
                "failure_onset_s": 7.5,
                "oracle_hidden_from_diagnosis": True,
                "evidence_sha256": SHA,
            }
            for index in range(3)
        ],
        "visible_leakage_hits": [],
        "diagnosis": {"correct_probe_repair": False, "agent_correct": False},
    }


def test_retain_requires_only_reference_fault_mechanism_repeatability_and_isolation():
    result = evaluate_candidate(candidate())
    assert result["benchmark_admission"] == "RETAINED_GOLD"
    assert result["diagnosis_readiness"] == "NOT_EVALUATED"
    assert result["probe_results_used_for_admission"] is False


@pytest.mark.parametrize(
    ("mutation", "failed_gate"),
    [
        (lambda value: value["reference_runs"][0].update(task_failure=True), "reference_pass"),
        (lambda value: value["faulty_runs"][1].update(task_failure=False), "faulty_fail"),
        (
            lambda value: value["faulty_runs"][2].update(mechanism_confirmed=False),
            "mechanism_confirmed",
        ),
        (
            lambda value: value["faulty_runs"][0].update(failure_onset_s=9.1),
            "activation_precedes_failure",
        ),
        (lambda value: value["visible_leakage_hits"].append("fault_label"), "visible_leakage"),
    ],
)
def test_rejects_each_scientific_gate(mutation, failed_gate):
    value = candidate()
    mutation(value)
    result = evaluate_candidate(value)
    assert result["benchmark_admission"] == "REJECTED_CANDIDATE"
    assert failed_gate in result["failed_gates"]


def test_requires_exactly_three_independent_repeats():
    value = candidate()
    value["faulty_runs"].pop()
    result = evaluate_candidate(value)
    assert "faulty_repeat_count" in result["failed_gates"]


def test_missing_timing_evidence_fails_closed():
    value = deepcopy(candidate())
    del value["faulty_runs"][0]["failure_onset_s"]
    with pytest.raises(AdmissionError, match="failure_onset_s"):
        evaluate_candidate(value)


def test_invalid_evidence_hash_fails_closed():
    value = candidate()
    value["reference_runs"][0]["evidence_sha256"] = "not-a-sha"
    with pytest.raises(AdmissionError, match="evidence_sha256"):
        evaluate_candidate(value)


def test_explicitly_missing_failure_timestamp_rejects_without_fabrication():
    value = candidate()
    value["faulty_runs"][0]["failure_onset_s"] = None
    result = evaluate_candidate(value)
    assert result["benchmark_admission"] == "REJECTED_CANDIDATE"
    assert "activation_precedes_failure" in result["failed_gates"]
