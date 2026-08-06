"""Replayable diagnosis session over the central execution gate."""

from __future__ import annotations

from collections.abc import Callable

from .belief import BeliefState
from .contracts import ActionProposal, DiagnosticState, EpisodeSpec, ResponsibilityDomain
from .coordinator import CentralExecutionGate
from .events import AppendOnlyEventLog
from .state import initial_state, updated_state


LikelihoodExtractor = Callable[[object], dict[ResponsibilityDomain, float]]


class DiagnosisSession:
    def __init__(
        self,
        episode: EpisodeSpec,
        gate: CentralExecutionGate,
        event_log: AppendOnlyEventLog,
    ) -> None:
        self.episode = episode
        self.gate = gate
        self.event_log = event_log
        latest = event_log.latest_payload("STATE_SNAPSHOT")
        if latest is None:
            self.state = initial_state(episode, gate.budget)
            self.belief = BeliefState(self.state.posterior)
            self._snapshot("initial")
        else:
            self.state = DiagnosticState.model_validate(latest["state"])
            if self.state.episode_id != episode.episode_id:
                raise ValueError("event log belongs to a different episode")
            self.belief = BeliefState(self.state.posterior)

    def _snapshot(self, reason: str) -> None:
        snapshot_id = f"state:{self.episode.episode_id}:{self.state.step}:{reason}"
        self.event_log.append(
            snapshot_id,
            "STATE_SNAPSHOT",
            {"reason": reason, "state": self.state.model_dump(mode="json")},
        )

    def execute(
        self,
        proposal: ActionProposal,
        likelihood_extractor: LikelihoodExtractor,
    ) -> DiagnosticState:
        previous = self.gate.evidence.for_action(proposal.action_id)
        evidence = self.gate.execute(proposal)
        if previous is None:
            self.belief.update(likelihood_extractor(evidence))
        self.state = updated_state(
            self.state,
            self.belief,
            self.gate.budget,
            self.gate.evidence,
        )
        self._snapshot("action_complete")
        return self.state
