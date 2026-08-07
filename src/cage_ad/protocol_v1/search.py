"""The only candidate/dose search state machine for protocol v1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

from .loader import EXPECTED_SEARCH_PROGRAM, ProtocolBundle, ProtocolValidationError


class SearchPhase(str, Enum):
    NOMINAL = "nominal_gate"
    DOSE = "dose_gate"
    PROBES = "probe_gate"
    TERMINAL = "terminal"


class SearchEvent(str, Enum):
    NOMINAL_PASSED = "nominal_passed"
    NOMINAL_FAILED = "nominal_failed"
    DOSE_PASSED = "dose_passed"
    DOSE_FAILED = "dose_failed"
    PROBES_VALID = "probes_valid"
    PROBES_INVALID = "probes_invalid"


@dataclass(frozen=True)
class SearchSnapshot:
    recipe_id: str
    phase: SearchPhase
    candidate_index: int
    dose_index: int | None
    selected_candidate_id: str | None = None
    selected_dose: Mapping[str, Any] | None = None
    terminal_classification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["phase"] = self.phase.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SearchSnapshot":
        try:
            return cls(
                recipe_id=str(value["recipe_id"]),
                phase=SearchPhase(value["phase"]),
                candidate_index=int(value["candidate_index"]),
                dose_index=None if value.get("dose_index") is None else int(value["dose_index"]),
                selected_candidate_id=value.get("selected_candidate_id"),
                selected_dose=value.get("selected_dose"),
                terminal_classification=value.get("terminal_classification"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolValidationError(f"invalid search snapshot: {exc}") from exc


class NestedSearchMachine:
    """Interpret the registry's normative search once; orchestration must use this class."""

    def __init__(self, bundle: ProtocolBundle, recipe_id: str, snapshot: SearchSnapshot | None = None):
        if tuple(bundle.episodes["normative_nested_search"]) != EXPECTED_SEARCH_PROGRAM:
            raise ProtocolValidationError("refusing to execute a non-normative search program")
        self.bundle = bundle
        self.recipe_row = bundle.recipe(recipe_id)
        self.scenario = bundle.scenarios["scenarios"][self.recipe_row["scenario_id"]]
        self.fault = bundle.faults["faults"][self.recipe_row["fault_id"]]
        self.candidates = self.scenario["candidate_order"]
        self.doses = self.fault["dose_grid"]
        self.snapshot = snapshot or SearchSnapshot(
            recipe_id=recipe_id,
            phase=SearchPhase.NOMINAL,
            candidate_index=0,
            dose_index=None,
        )
        self._validate_snapshot(self.snapshot)

    def _validate_snapshot(self, snapshot: SearchSnapshot) -> None:
        if snapshot.recipe_id != self.recipe_row["recipe_id"]:
            raise ProtocolValidationError("search snapshot recipe mismatch")
        if not 0 <= snapshot.candidate_index < len(self.candidates):
            raise ProtocolValidationError("search snapshot candidate index out of bounds")
        if snapshot.phase == SearchPhase.DOSE and (
            snapshot.dose_index is None or not 0 <= snapshot.dose_index < len(self.doses)
        ):
            raise ProtocolValidationError("dose phase requires a valid dose index")
        if snapshot.phase == SearchPhase.PROBES and (
            snapshot.selected_candidate_id is None or snapshot.selected_dose is None
        ):
            raise ProtocolValidationError("probe phase requires a frozen candidate and dose")
        if snapshot.phase == SearchPhase.TERMINAL and snapshot.terminal_classification is None:
            raise ProtocolValidationError("terminal snapshot requires a classification")

    @property
    def current_candidate(self) -> Mapping[str, Any]:
        return self.candidates[self.snapshot.candidate_index]

    @property
    def current_dose(self) -> Mapping[str, Any] | None:
        return None if self.snapshot.dose_index is None else self.doses[self.snapshot.dose_index]

    def advance(self, event: SearchEvent, *, classification: str | None = None) -> SearchSnapshot:
        state = self.snapshot
        if state.phase == SearchPhase.TERMINAL:
            raise ProtocolValidationError("terminal search cannot advance")
        if state.phase == SearchPhase.NOMINAL:
            if event == SearchEvent.NOMINAL_PASSED:
                next_state = SearchSnapshot(state.recipe_id, SearchPhase.DOSE, state.candidate_index, 0)
            elif event == SearchEvent.NOMINAL_FAILED:
                next_state = self._next_candidate_or_terminal(state)
            else:
                raise ProtocolValidationError(f"illegal event {event.value} in nominal phase")
        elif state.phase == SearchPhase.DOSE:
            if event == SearchEvent.DOSE_PASSED:
                next_state = SearchSnapshot(
                    state.recipe_id,
                    SearchPhase.PROBES,
                    state.candidate_index,
                    state.dose_index,
                    selected_candidate_id=self.current_candidate["candidate_id"],
                    selected_dose=dict(self.current_dose or {}),
                )
            elif event == SearchEvent.DOSE_FAILED:
                assert state.dose_index is not None
                if state.dose_index + 1 < len(self.doses):
                    next_state = SearchSnapshot(state.recipe_id, SearchPhase.DOSE, state.candidate_index, state.dose_index + 1)
                else:
                    next_state = self._next_candidate_or_terminal(state)
            else:
                raise ProtocolValidationError(f"illegal event {event.value} in dose phase")
        else:
            if event == SearchEvent.PROBES_INVALID:
                next_state = SearchSnapshot(
                    state.recipe_id,
                    SearchPhase.TERMINAL,
                    state.candidate_index,
                    state.dose_index,
                    state.selected_candidate_id,
                    state.selected_dose,
                    "rejected_probe_invalid",
                )
            elif event == SearchEvent.PROBES_VALID:
                if classification not in {
                    "identifiable",
                    "ambiguous_multi_domain",
                    "ambiguous_insufficient_correct_effect",
                    "ambiguous_nonselective",
                }:
                    raise ProtocolValidationError("probe-valid transition requires a protocol classification")
                next_state = SearchSnapshot(
                    state.recipe_id,
                    SearchPhase.TERMINAL,
                    state.candidate_index,
                    state.dose_index,
                    state.selected_candidate_id,
                    state.selected_dose,
                    classification,
                )
            else:
                raise ProtocolValidationError(f"illegal event {event.value} in probe phase")
        self._validate_snapshot(next_state)
        self.snapshot = next_state
        return next_state

    def _next_candidate_or_terminal(self, state: SearchSnapshot) -> SearchSnapshot:
        if state.candidate_index + 1 < len(self.candidates):
            return SearchSnapshot(state.recipe_id, SearchPhase.NOMINAL, state.candidate_index + 1, None)
        return SearchSnapshot(
            state.recipe_id,
            SearchPhase.TERMINAL,
            state.candidate_index,
            state.dose_index,
            terminal_classification="rejected_no_causal_dose",
        )
