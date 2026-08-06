"""Append-only, hash-chained event log with deterministic crash recovery."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass(frozen=True)
class Event:
    sequence: int
    event_id: str
    event_type: str
    timestamp: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


class EventLogCorruption(RuntimeError):
    pass


class AppendOnlyEventLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _hash(unsigned: dict[str, Any]) -> str:
        return hashlib.sha256(canonical_json(unsigned)).hexdigest()

    def read(self) -> list[Event]:
        events: list[Event] = []
        previous = GENESIS_HASH
        if not self.path.exists():
            return events
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.endswith("\n"):
                    raise EventLogCorruption(f"partial event at line {line_number}")
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EventLogCorruption(f"invalid JSON at line {line_number}") from exc
                event_hash = raw.pop("event_hash", None)
                if raw.get("sequence") != len(events):
                    raise EventLogCorruption(f"non-contiguous sequence at line {line_number}")
                if raw.get("previous_hash") != previous:
                    raise EventLogCorruption(f"broken hash chain at line {line_number}")
                if event_hash != self._hash(raw):
                    raise EventLogCorruption(f"invalid event hash at line {line_number}")
                raw["event_hash"] = event_hash
                event = Event(**raw)
                events.append(event)
                previous = event.event_hash
        return events

    def append(self, event_id: str, event_type: str, payload: dict[str, Any]) -> Event:
        with self._lock:
            events = self.read()
            matches = [event for event in events if event.event_id == event_id]
            if matches:
                existing = matches[0]
                if existing.event_type != event_type or existing.payload != payload:
                    raise ValueError("event ID reused with different content")
                return existing
            unsigned = {
                "sequence": len(events),
                "event_id": event_id,
                "event_type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
                "previous_hash": events[-1].event_hash if events else GENESIS_HASH,
            }
            raw = {**unsigned, "event_hash": self._hash(unsigned)}
            encoded = canonical_json(raw) + b"\n"
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return Event(**raw)

    def iter_type(self, event_type: str) -> Iterator[Event]:
        return (event for event in self.read() if event.event_type == event_type)

    def latest_payload(self, event_type: str) -> dict[str, Any] | None:
        matches = list(self.iter_type(event_type))
        return None if not matches else matches[-1].payload
