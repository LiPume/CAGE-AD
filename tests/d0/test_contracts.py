from __future__ import annotations

import pytest
from pydantic import ValidationError

from cage_ad.active_diagnosis.contracts import (
    AccessRegime,
    ActionProposal,
    ActionType,
    CostVector,
    DiagnosticState,
    ResponsibilityDomain,
)


DOMAINS = list(ResponsibilityDomain)


def test_contracts_forbid_unknown_fields(episode) -> None:
    with pytest.raises(ValidationError):
        type(episode).model_validate({**episode.model_dump(), "responsibility_domain": "tracking_execution"})


def test_diagnostic_state_requires_normalized_complete_posterior() -> None:
    with pytest.raises(ValidationError):
        DiagnosticState(
            episode_id="opaque-episode",
            candidate_domains=DOMAINS,
            posterior={domain: 0.2 for domain in DOMAINS},
            remaining_budget=CostVector(),
        )


def test_action_proposal_cannot_report_confidence() -> None:
    with pytest.raises(ValidationError):
        ActionProposal(
            proposal_id="proposal-123",
            proposed_by="policy",
            action_id="O1",
            target_hypotheses=[ResponsibilityDomain.MOTION_PLANNING],
            required_regime=AccessRegime.L1,
            action_type=ActionType.OBSERVATION,
            self_reported_confidence=0.9,
        )


@pytest.mark.parametrize("field", ["bytes", "signals", "risk", "tokens", "api_cost_usd"])
def test_cost_vector_rejects_negative_values(field: str) -> None:
    with pytest.raises(ValidationError):
        CostVector(**{field: -1})
