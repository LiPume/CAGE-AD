"""Policies can propose typed actions; they receive no executor capability."""

from __future__ import annotations

from typing import Protocol

from .catalog import ActionCatalog
from .contracts import ActionProposal, DiagnosticState


class DiagnosticPolicy(Protocol):
    def propose(self, state: DiagnosticState, catalog: ActionCatalog) -> list[ActionProposal]: ...
