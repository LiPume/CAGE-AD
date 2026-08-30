"""Hash-chained append-only calibration ledger and crash-safe search replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .loader import ProtocolBundle, ProtocolValidationError
from .search import NestedSearchMachine, SearchEvent, SearchSnapshot


GENESIS_SHA256 = "0" * 64


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass(frozen=True)
class LedgerRecord:
    sequence: int
    recorded_at: str
    event_type: str
    operation_id: str
    payload: Mapping[str, Any]
    previous_sha256: str
    event_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttemptPlan:
    attempt_id: str
    recipe_id: str
    phase: str
    candidate_id: str
    seed: int
    condition: str
    source_commit: str
    protocol_bundle_sha256: str
    config_sha256: str
    command: Sequence[str]
    dose: Mapping[str, float] | None = None
    infrastructure_attempt: int = 0


@dataclass(frozen=True)
class AttemptResult:
    attempt_id: str
    status: str
    runtime_valid: bool
    five_layer_metrics: Mapping[str, Any]
    wall_seconds: float
    powered_on_seconds: float
    incremental_storage_bytes: int
    output_sha256: Mapping[str, str]
    failure_reason: str | None = None


class CalibrationLedger:
    def __init__(self, path: Path):
        self.path = path
        if path.exists() and path.is_symlink():
            raise ProtocolValidationError("calibration ledger must not be a symlink")
        self._records = self._read_and_validate()

    @property
    def records(self) -> tuple[LedgerRecord, ...]:
        return tuple(self._records)

    def _read_and_validate(self) -> list[LedgerRecord]:
        if not self.path.exists():
            return []
        records: list[LedgerRecord] = []
        previous = GENESIS_SHA256
        for line_number, line in enumerate(self.path.read_text().splitlines(), start=1):
            if not line.strip():
                raise ProtocolValidationError(f"blank ledger line at {line_number}")
            try:
                raw = json.loads(line)
                supplied_hash = raw.pop("event_sha256")
                calculated = hashlib.sha256(_canonical(raw)).hexdigest()
                record = LedgerRecord(event_sha256=supplied_hash, **raw)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ProtocolValidationError(f"malformed ledger line {line_number}: {exc}") from exc
            if record.sequence != line_number:
                raise ProtocolValidationError(f"non-contiguous ledger sequence at line {line_number}")
            if record.previous_sha256 != previous:
                raise ProtocolValidationError(f"broken ledger chain at line {line_number}")
            if record.event_sha256 != calculated:
                raise ProtocolValidationError(f"ledger hash mismatch at line {line_number}")
            if not record.operation_id or not record.event_type:
                raise ProtocolValidationError(f"empty ledger identity at line {line_number}")
            records.append(record)
            previous = record.event_sha256
        return records

    def find_operation(self, operation_id: str) -> LedgerRecord | None:
        matches = [record for record in self._records if record.operation_id == operation_id]
        if len(matches) > 1:
            raise ProtocolValidationError(f"duplicate ledger operation: {operation_id}")
        return matches[0] if matches else None

    def append_once(
        self,
        *,
        operation_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        recorded_at: str,
    ) -> LedgerRecord:
        existing = self.find_operation(operation_id)
        if existing is not None:
            if existing.event_type != event_type or dict(existing.payload) != dict(payload):
                raise ProtocolValidationError(f"idempotency conflict for operation: {operation_id}")
            return existing
        if not operation_id or not recorded_at:
            raise ProtocolValidationError("ledger operation and timestamp are required")
        raw = {
            "sequence": len(self._records) + 1,
            "recorded_at": recorded_at,
            "event_type": event_type,
            "operation_id": operation_id,
            "payload": dict(payload),
            "previous_sha256": self._records[-1].event_sha256 if self._records else GENESIS_SHA256,
        }
        digest = hashlib.sha256(_canonical(raw)).hexdigest()
        record = LedgerRecord(event_sha256=digest, **raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, _canonical(record.to_dict()) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._records.append(record)
        return record

    def plan_attempt(self, plan: AttemptPlan, *, recorded_at: str) -> LedgerRecord:
        if self.find_attempt_plan(plan.attempt_id) is not None:
            existing = self.find_operation(f"attempt-plan/{plan.attempt_id}")
            assert existing is not None
            if dict(existing.payload) != asdict(plan):
                raise ProtocolValidationError(f"attempt plan changed: {plan.attempt_id}")
            return existing
        if not plan.command or any(not isinstance(item, str) or not item for item in plan.command):
            raise ProtocolValidationError("attempt command must be an argv sequence")
        return self.append_once(
            operation_id=f"attempt-plan/{plan.attempt_id}",
            event_type="attempt_planned",
            payload=asdict(plan),
            recorded_at=recorded_at,
        )

    def complete_attempt(self, result: AttemptResult, *, recorded_at: str) -> LedgerRecord:
        if self.find_attempt_plan(result.attempt_id) is None:
            raise ProtocolValidationError(f"cannot complete unplanned attempt: {result.attempt_id}")
        if result.status not in {"completed", "invalid", "failed", "interrupted"}:
            raise ProtocolValidationError(f"invalid attempt status: {result.status}")
        return self.append_once(
            operation_id=f"attempt-result/{result.attempt_id}",
            event_type="attempt_finished",
            payload=asdict(result),
            recorded_at=recorded_at,
        )

    def find_attempt_plan(self, attempt_id: str) -> AttemptPlan | None:
        record = self.find_operation(f"attempt-plan/{attempt_id}")
        return None if record is None else AttemptPlan(**record.payload)

    def pending_attempt_ids(self) -> tuple[str, ...]:
        planned = [
            record.payload["attempt_id"]
            for record in self._records
            if record.event_type == "attempt_planned"
        ]
        finished = {
            record.payload["attempt_id"]
            for record in self._records
            if record.event_type == "attempt_finished"
        }
        return tuple(attempt_id for attempt_id in planned if attempt_id not in finished)

    def replay_search(self, bundle: ProtocolBundle, recipe_id: str) -> NestedSearchMachine:
        machine = NestedSearchMachine(bundle, recipe_id)
        transitions = [
            record
            for record in self._records
            if record.event_type == "search_transition" and record.payload.get("recipe_id") == recipe_id
        ]
        for record in transitions:
            before = SearchSnapshot.from_dict(record.payload["before"])
            if before != machine.snapshot:
                raise ProtocolValidationError(f"search ledger before-state mismatch at {record.sequence}")
            event = SearchEvent(record.payload["event"])
            after = machine.advance(event, classification=record.payload.get("classification"))
            if after != SearchSnapshot.from_dict(record.payload["after"]):
                raise ProtocolValidationError(f"search ledger after-state mismatch at {record.sequence}")
        return machine

    def advance_search_once(
        self,
        bundle: ProtocolBundle,
        recipe_id: str,
        event: SearchEvent,
        *,
        transition_id: str,
        recorded_at: str,
        classification: str | None = None,
    ) -> SearchSnapshot:
        operation_id = f"search/{recipe_id}/{transition_id}"
        existing = self.find_operation(operation_id)
        if existing is not None:
            if existing.payload.get("event") != event.value or existing.payload.get("classification") != classification:
                raise ProtocolValidationError(f"idempotency conflict for search transition: {transition_id}")
            self.replay_search(bundle, recipe_id)
            return SearchSnapshot.from_dict(existing.payload["after"])
        machine = self.replay_search(bundle, recipe_id)
        before = machine.snapshot
        after = machine.advance(event, classification=classification)
        self.append_once(
            operation_id=operation_id,
            event_type="search_transition",
            payload={
                "recipe_id": recipe_id,
                "event": event.value,
                "classification": classification,
                "before": before.to_dict(),
                "after": after.to_dict(),
            },
            recorded_at=recorded_at,
        )
        return after
