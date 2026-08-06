"""State construction helpers and replayable snapshot validation."""

from __future__ import annotations

from .belief import BeliefState
from .budget import BudgetLedger
from .contracts import DiagnosticState, DiagnosisStatus, EpisodeSpec, ResponsibilityDomain
from .evidence import EvidenceLedger


def initial_state(episode: EpisodeSpec, budget: BudgetLedger) -> DiagnosticState:
    domains = list(ResponsibilityDomain)
    prior = 1.0 / len(domains)
    return DiagnosticState(
        episode_id=episode.episode_id,
        candidate_domains=domains,
        posterior={domain: prior for domain in domains},
        prediction_set=domains,
        remaining_budget=budget.remaining,
    )


def updated_state(
    state: DiagnosticState,
    belief: BeliefState,
    budget: BudgetLedger,
    evidence: EvidenceLedger,
) -> DiagnosticState:
    return DiagnosticState(
        episode_id=state.episode_id,
        step=len(evidence.entries()),
        candidate_domains=state.candidate_domains,
        posterior=belief.posterior,
        prediction_set=belief.prediction_set(),
        evidence_ledger=evidence.summaries(),
        executed_actions=[entry.action_id for entry in evidence.entries()],
        remaining_budget=budget.remaining,
        mapping_uncertainty=state.mapping_uncertainty,
        tool_failures=state.tool_failures,
        status=DiagnosisStatus.CONTINUE,
    )
