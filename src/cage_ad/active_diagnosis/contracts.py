"""Public contracts for diagnosis-visible state and actions.

Evaluator truth intentionally has no model in this module. It lives behind the
private evaluator process boundary and is never accepted by diagnosis entry points.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ResponsibilityDomain(str, Enum):
    INTERACTION_FORECASTING = "interaction_forecasting"
    MOTION_PLANNING = "motion_planning"
    TRACKING_EXECUTION = "tracking_execution"


class AccessRegime(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"

    @property
    def rank(self) -> int:
        return {self.L0: 0, self.L1: 1, self.L2: 2}[self]


class ActionType(str, Enum):
    OBSERVATION = "observation"
    INTERVENTION = "intervention"


class DiagnosisStatus(str, Enum):
    CONTINUE = "CONTINUE"
    DIAGNOSE = "DIAGNOSE"
    ABSTAIN = "ABSTAIN"
    TOOL_FAILURE = "TOOL_FAILURE"


class FailureWindow(StrictModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> "FailureWindow":
        if self.end_s <= self.start_s:
            raise ValueError("failure window end must be after start")
        return self


class CostVector(StrictModel):
    access: AccessRegime = AccessRegime.L0
    bytes: int = Field(default=0, ge=0)
    signals: int = Field(default=0, ge=0)
    replay_count: int = Field(default=0, ge=0)
    intervention_count: int = Field(default=0, ge=0)
    runtime_seconds: float = Field(default=0.0, ge=0)
    compute_seconds: float = Field(default=0.0, ge=0)
    human_minutes: float = Field(default=0.0, ge=0)
    risk: float = Field(default=0.0, ge=0)
    tokens: int = Field(default=0, ge=0)
    api_cost_usd: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def finite(self) -> "CostVector":
        for name in (
            "runtime_seconds",
            "compute_seconds",
            "human_minutes",
            "risk",
            "api_cost_usd",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        return self

    def plus(self, other: "CostVector") -> "CostVector":
        values: dict[str, Any] = {}
        for name in type(self).model_fields:
            if name == "access":
                values[name] = max((self.access, other.access), key=lambda item: item.rank)
            else:
                values[name] = getattr(self, name) + getattr(other, name)
        return CostVector(**values)


class ArtifactReference(StrictModel):
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    visibility: Literal["diagnosis_visible"] = "diagnosis_visible"

    @model_validator(mode="after")
    def safe_relative_path(self) -> "ArtifactReference":
        normalized = self.relative_path.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("artifact path must be relative and traversal-free")
        return self


class EpisodeSpec(StrictModel):
    episode_id: str = Field(min_length=8)
    stack: Literal["apollo_10"] = "apollo_10"
    scenario_template: str = Field(min_length=1)
    failure_type: str = Field(min_length=1)
    failure_window: FailureWindow
    observable_regime: AccessRegime
    initial_evidence_refs: list[ArtifactReference] = Field(default_factory=list)
    allowed_action_ids: list[str] = Field(min_length=1)
    budget_profile: str = Field(pattern=r"^B[0-4]$")
    seed: int = Field(ge=0)

    @model_validator(mode="after")
    def unique_actions(self) -> "EpisodeSpec":
        if len(self.allowed_action_ids) != len(set(self.allowed_action_ids)):
            raise ValueError("allowed action IDs must be unique")
        return self


class EvidenceSummary(StrictModel):
    evidence_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    semantic_slot: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    measured_cost: CostVector


class DiagnosticState(StrictModel):
    episode_id: str = Field(min_length=8)
    step: int = Field(default=0, ge=0)
    candidate_domains: list[ResponsibilityDomain] = Field(min_length=1)
    posterior: dict[ResponsibilityDomain, float]
    prediction_set: list[ResponsibilityDomain] = Field(default_factory=list)
    evidence_ledger: list[EvidenceSummary] = Field(default_factory=list)
    executed_actions: list[str] = Field(default_factory=list)
    remaining_budget: CostVector
    mapping_uncertainty: dict[str, float] = Field(default_factory=dict)
    tool_failures: list[str] = Field(default_factory=list)
    status: DiagnosisStatus = DiagnosisStatus.CONTINUE

    @model_validator(mode="after")
    def consistent(self) -> "DiagnosticState":
        candidates = set(self.candidate_domains)
        if len(candidates) != len(self.candidate_domains):
            raise ValueError("candidate domains must be unique")
        if set(self.posterior) != candidates:
            raise ValueError("posterior keys must exactly match candidate domains")
        if any(not math.isfinite(value) or value < 0 for value in self.posterior.values()):
            raise ValueError("posterior values must be finite and non-negative")
        if not math.isclose(sum(self.posterior.values()), 1.0, abs_tol=1e-9):
            raise ValueError("posterior must sum to one")
        if not set(self.prediction_set).issubset(candidates):
            raise ValueError("prediction set must be a candidate subset")
        if len(self.executed_actions) != len(set(self.executed_actions)):
            raise ValueError("executed action IDs must be unique")
        return self


class ActionProposal(StrictModel):
    proposal_id: str = Field(min_length=8)
    proposed_by: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    target_hypotheses: list[ResponsibilityDomain] = Field(min_length=1)
    predicted_outcome_partitions: list[list[ResponsibilityDomain]] = Field(default_factory=list)
    required_regime: AccessRegime
    action_type: ActionType
    rationale_evidence_ids: list[str] = Field(default_factory=list)
    requested_parameters: dict[str, Any] = Field(default_factory=dict)
    self_reported_confidence: None = None


class VerifiedEvidence(StrictModel):
    action_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=8)
    semantic_slot: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    tool_success: Literal[True] = True
    schema_valid: Literal[True] = True
    permission_valid: Literal[True] = True
    side_effects: list[str] = Field(default_factory=list)
    measured_cost: CostVector
    payload_ref: ArtifactReference


class DiagnosisResult(StrictModel):
    episode_id: str = Field(min_length=8)
    decision: Literal["diagnose", "abstain"]
    prediction_set: list[ResponsibilityDomain] = Field(min_length=1)
    posterior: dict[ResponsibilityDomain, float]
    selective_risk_estimate: float | None = Field(default=None, ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    executed_actions: list[str] = Field(default_factory=list)
    total_cost: CostVector
    stop_reason: Literal[
        "risk_met",
        "non_identifiable",
        "insufficient_budget",
        "tool_failure",
    ]
    audit_status: Literal["VERIFIED"] = "VERIFIED"

    @model_validator(mode="after")
    def normalized_posterior(self) -> "DiagnosisResult":
        if not math.isclose(sum(self.posterior.values()), 1.0, abs_tol=1e-9):
            raise ValueError("posterior must sum to one")
        if not set(self.prediction_set).issubset(self.posterior):
            raise ValueError("prediction set must be represented in posterior")
        return self
