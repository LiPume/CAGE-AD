"""Verified-evidence ledger; unverified tool output cannot enter state."""

from __future__ import annotations

from .contracts import EvidenceSummary, VerifiedEvidence


class EvidenceLedger:
    def __init__(self, entries: list[VerifiedEvidence] | None = None) -> None:
        self._entries: list[VerifiedEvidence] = []
        self._by_id: dict[str, VerifiedEvidence] = {}
        self._by_action: dict[str, VerifiedEvidence] = {}
        for entry in entries or []:
            self.append(entry)

    def append(self, evidence: VerifiedEvidence) -> None:
        existing = self._by_id.get(evidence.evidence_id)
        if existing is not None:
            if existing != evidence:
                raise ValueError("evidence ID reused with different content")
            return
        action_existing = self._by_action.get(evidence.action_id)
        if action_existing is not None and action_existing != evidence:
            raise ValueError("action already has different verified evidence")
        self._entries.append(evidence)
        self._by_id[evidence.evidence_id] = evidence
        self._by_action[evidence.action_id] = evidence

    def for_action(self, action_id: str) -> VerifiedEvidence | None:
        return self._by_action.get(action_id)

    def entries(self) -> list[VerifiedEvidence]:
        return list(self._entries)

    def summaries(self) -> list[EvidenceSummary]:
        return [
            EvidenceSummary(
                evidence_id=item.evidence_id,
                action_id=item.action_id,
                semantic_slot=item.semantic_slot,
                payload_sha256=item.payload_ref.sha256,
                measured_cost=item.measured_cost,
            )
            for item in self._entries
        ]
