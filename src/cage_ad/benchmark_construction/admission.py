"""Fail-closed admission for one reference/faulty scene pair.

This module decides only whether a failure case exists.  It deliberately does
not inspect probes, diagnosis predictions, policies, or Agent outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class AdmissionError(ValueError):
    """Raised when candidate evidence is incomplete or malformed."""


@dataclass(frozen=True)
class AdmissionPolicy:
    reference_repeats: int = 3
    faulty_repeats: int = 3
    max_activation_to_failure_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.reference_repeats < 1 or self.faulty_repeats < 1:
            raise AdmissionError("repeat counts must be positive")
        if self.max_activation_to_failure_seconds <= 0:
            raise AdmissionError("activation-to-failure window must be positive")


def _required(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise AdmissionError(f"missing {context}.{key}")
    return mapping[key]


def _boolean(mapping: Mapping[str, Any], key: str, context: str) -> bool:
    value = _required(mapping, key, context)
    if not isinstance(value, bool):
        raise AdmissionError(f"{context}.{key} must be boolean")
    return value


def _nullable_number(mapping: Mapping[str, Any], key: str, context: str) -> float | None:
    value = _required(mapping, key, context)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdmissionError(f"{context}.{key} must be numeric or null")
    return float(value)


def _runs(candidate: Mapping[str, Any], key: str) -> Sequence[Mapping[str, Any]]:
    value = _required(candidate, key, "candidate")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise AdmissionError(f"candidate.{key} must be a list of objects")
    return value


def _run_id(run: Mapping[str, Any], context: str) -> str:
    value = _required(run, "run_id", context)
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise AdmissionError(f"{context}.run_id must be a non-empty opaque path component")
    return value


def _sha256(mapping: Mapping[str, Any], key: str, context: str) -> str:
    value = _required(mapping, key, context)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AdmissionError(f"{context}.{key} must be lowercase SHA-256")
    return value


def evaluate_candidate(
    candidate: Mapping[str, Any], policy: AdmissionPolicy = AdmissionPolicy()
) -> dict[str, Any]:
    """Evaluate a single scene/fault candidate under a HINT-style paired gate."""

    if _required(candidate, "schema_version", "candidate") != 1:
        raise AdmissionError("unsupported candidate schema_version")
    candidate_id = _required(candidate, "candidate_id", "candidate")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise AdmissionError("candidate.candidate_id must be a non-empty string")
    implementation_sha256 = _sha256(candidate, "fault_implementation_sha256", "candidate")

    references = _runs(candidate, "reference_runs")
    faulty = _runs(candidate, "faulty_runs")
    reference_checks = []
    for index, run in enumerate(references):
        context = f"candidate.reference_runs[{index}]"
        reference_checks.append(
            {
                "run_id": _run_id(run, context),
                "infrastructure_valid": _boolean(run, "infrastructure_valid", context),
                "task_failure": _boolean(run, "task_failure", context),
                "oracle_hidden_from_diagnosis": _boolean(
                    run, "oracle_hidden_from_diagnosis", context
                ),
                "evidence_sha256": _sha256(run, "evidence_sha256", context),
            }
        )
    faulty_checks = []
    for index, run in enumerate(faulty):
        context = f"candidate.faulty_runs[{index}]"
        activation = _nullable_number(run, "mechanism_activated_at_s", context)
        failure = _nullable_number(run, "failure_onset_s", context)
        faulty_checks.append(
            {
                "run_id": _run_id(run, context),
                "infrastructure_valid": _boolean(run, "infrastructure_valid", context),
                "task_failure": _boolean(run, "task_failure", context),
                "mechanism_confirmed": _boolean(run, "mechanism_confirmed", context),
                "mechanism_activated_at_s": activation,
                "failure_onset_s": failure,
                "activation_to_failure_s": (
                    None if activation is None or failure is None else failure - activation
                ),
                "oracle_hidden_from_diagnosis": _boolean(
                    run, "oracle_hidden_from_diagnosis", context
                ),
                "evidence_sha256": _sha256(run, "evidence_sha256", context),
            }
        )

    leakage_hits = _required(candidate, "visible_leakage_hits", "candidate")
    if not isinstance(leakage_hits, list) or any(not isinstance(item, str) for item in leakage_hits):
        raise AdmissionError("candidate.visible_leakage_hits must be a list of strings")

    gates = {
        "reference_repeat_count": len(reference_checks) == policy.reference_repeats,
        "reference_pass": all(
            row["infrastructure_valid"] and not row["task_failure"]
            for row in reference_checks
        ),
        "faulty_repeat_count": len(faulty_checks) == policy.faulty_repeats,
        "faulty_fail": all(
            row["infrastructure_valid"] and row["task_failure"] for row in faulty_checks
        ),
        "mechanism_confirmed": all(row["mechanism_confirmed"] for row in faulty_checks),
        "activation_precedes_failure": all(
            row["activation_to_failure_s"] is not None
            and 0.0 <= row["activation_to_failure_s"]
            <= policy.max_activation_to_failure_seconds
            for row in faulty_checks
        ),
        "oracle_isolation": all(
            row["oracle_hidden_from_diagnosis"]
            for row in [*reference_checks, *faulty_checks]
        ),
        "visible_leakage": not leakage_hits,
    }
    failed = [name for name, passed in gates.items() if not passed]
    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "admission_policy": {
            "reference_repeats": policy.reference_repeats,
            "faulty_repeats": policy.faulty_repeats,
            "max_activation_to_failure_seconds": policy.max_activation_to_failure_seconds,
        },
        "reference_checks": reference_checks,
        "faulty_checks": faulty_checks,
        "gates": gates,
        "failed_gates": failed,
        "benchmark_admission": "RETAINED_GOLD" if not failed else "REJECTED_CANDIDATE",
        "diagnosis_readiness": "NOT_EVALUATED",
        "probe_results_used_for_admission": False,
    }
