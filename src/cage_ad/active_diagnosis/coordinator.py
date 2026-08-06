"""The single legal tool-execution boundary."""

from __future__ import annotations

from typing import Protocol

from .budget import BudgetExceeded, BudgetLedger, BudgetProfile
from .catalog import ActionCatalog, ActionDefinition
from .contracts import ActionProposal, EpisodeSpec, VerifiedEvidence
from .events import AppendOnlyEventLog
from .evidence import EvidenceLedger
from .verifier import EvidenceRejected, EvidenceVerifier, RawToolResult


class ToolExecutor(Protocol):
    idempotent: bool

    def execute(
        self,
        proposal: ActionProposal,
        *,
        idempotency_key: str,
        maximum_cost,
    ) -> RawToolResult: ...


class ToolExecutionFailed(RuntimeError):
    pass


class CentralExecutionGate:
    """Only this object owns executors and can convert output to evidence."""

    def __init__(
        self,
        *,
        episode: EpisodeSpec,
        catalog: ActionCatalog,
        budget_profile: BudgetProfile,
        verifier: EvidenceVerifier,
        event_log: AppendOnlyEventLog,
        executors: dict[str, ToolExecutor],
    ) -> None:
        self.episode = episode
        self.catalog = catalog
        self.verifier = verifier
        self.event_log = event_log
        self.executors = dict(executors)
        recovered = [
            VerifiedEvidence.model_validate(event.payload["evidence"])
            for event in event_log.read()
            if event.event_type == "ACTION_COMPLETED"
        ]
        spent = None
        for item in recovered:
            spent = item.measured_cost if spent is None else spent.plus(item.measured_cost)
        self.budget = BudgetLedger(budget_profile, spent=spent)
        self.evidence = EvidenceLedger(recovered)

    def _idempotency_key(self, definition: ActionDefinition) -> str:
        return f"{self.episode.episode_id}:{definition.action_id}"

    def execute(self, proposal: ActionProposal) -> VerifiedEvidence:
        cached = self.evidence.for_action(proposal.action_id)
        if cached is not None:
            return cached
        definition = self.catalog.validate(
            proposal,
            allowed_action_ids=set(self.episode.allowed_action_ids),
            observable_regime=self.episode.observable_regime,
            executed_actions=set(),
        )
        executor = self.executors.get(definition.action_id)
        if executor is None:
            raise ToolExecutionFailed("no executor registered for legal action")
        if definition.intervention and not executor.idempotent:
            raise ToolExecutionFailed("intervention executor must guarantee idempotency")
        key = self._idempotency_key(definition)
        self.budget.reserve(key, definition.maximum_cost)
        self.event_log.append(
            f"start:{key}",
            "ACTION_STARTED",
            {
                "action_id": definition.action_id,
                "idempotency_key": key,
                "intervention": definition.intervention,
                "maximum_cost": definition.maximum_cost.model_dump(mode="json"),
            },
        )
        try:
            raw = executor.execute(
                proposal,
                idempotency_key=key,
                maximum_cost=definition.maximum_cost,
            )
            verified = self.verifier.verify(definition.action_id, raw)
            self.budget.commit(key, verified.measured_cost)
        except (EvidenceRejected, BudgetExceeded, Exception) as exc:
            self.budget.rollback(key)
            self.event_log.append(
                f"failed:{key}",
                "ACTION_FAILED",
                {
                    "action_id": definition.action_id,
                    "error_class": type(exc).__name__,
                    "message": str(exc),
                },
            )
            raise
        self.event_log.append(
            f"complete:{key}",
            "ACTION_COMPLETED",
            {"evidence": verified.model_dump(mode="json")},
        )
        self.evidence.append(verified)
        return verified
