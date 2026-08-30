"""YAML-driven deterministic scenario candidates for protocol v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .loader import ProtocolBundle, ProtocolValidationError


@dataclass(frozen=True)
class ScenarioCandidate:
    scenario_id: str
    semantic_family: str
    candidate_id: str
    values: Mapping[str, float | str]

    @property
    def conflict_onset_s(self) -> float:
        key = "brake_start_s" if self.semantic_family == "lead_vehicle_deceleration" else "cut_in_start_s"
        return float(self.values[key])

    @property
    def trigger_window(self) -> tuple[float, float]:
        return self.conflict_onset_s - 1.0, self.conflict_onset_s + 3.0

    @property
    def spawn_offsets_m(self) -> tuple[float, float]:
        if self.semantic_family == "lead_vehicle_deceleration":
            return float(self.values["initial_gap_m"]), 0.0
        return float(self.values["longitudinal_offset_m"]), float(self.values["lateral_offset_m"])

    def velocity(self, elapsed_s: float) -> tuple[float, float]:
        """Analytic longitudinal/lateral velocity in the actor frame."""
        if self.semantic_family == "lead_vehicle_deceleration":
            start = float(self.values["brake_start_s"])
            initial = float(self.values["lead_speed_mps"])
            deceleration = float(self.values["deceleration_mps2"])
            return (initial if elapsed_s < start else max(0.0, initial - deceleration * (elapsed_s - start))), 0.0
        start = float(self.values["cut_in_start_s"])
        lateral = 0.0 if elapsed_s < start else min(
            float(self.values["maximum_lateral_speed_mps"]),
            float(self.values["lateral_acceleration_mps2"]) * (elapsed_s - start),
        )
        return float(self.values["longitudinal_speed_mps"]), lateral

    def displacement(self, start_s: float, duration_s: float) -> tuple[float, float]:
        """精确积分冻结候选的分段线性速度，不改变候选或时间轴。"""

        if start_s < 0.0 or duration_s < 0.0:
            raise ProtocolValidationError("scenario displacement interval must be nonnegative")
        end_s = start_s + duration_s
        if self.semantic_family == "lead_vehicle_deceleration":
            brake = float(self.values["brake_start_s"])
            initial = float(self.values["lead_speed_mps"])
            deceleration = float(self.values["deceleration_mps2"])
            stop = brake + initial / deceleration

            def primitive(seconds: float) -> float:
                if seconds <= brake:
                    return initial * seconds
                if seconds <= stop:
                    after = seconds - brake
                    return initial * brake + initial * after - 0.5 * deceleration * after**2
                return initial * brake + initial**2 / (2.0 * deceleration)

            return primitive(end_s) - primitive(start_s), 0.0

        cut_in = float(self.values["cut_in_start_s"])
        acceleration = float(self.values["lateral_acceleration_mps2"])
        maximum = float(self.values["maximum_lateral_speed_mps"])
        ramp = maximum / acceleration

        def lateral_primitive(seconds: float) -> float:
            after = max(0.0, seconds - cut_in)
            if after <= ramp:
                return 0.5 * acceleration * after**2
            return 0.5 * acceleration * ramp**2 + maximum * (after - ramp)

        return (
            float(self.values["longitudinal_speed_mps"]) * duration_s,
            lateral_primitive(end_s) - lateral_primitive(start_s),
        )


def scenario_candidate(bundle: ProtocolBundle, scenario_id: str, candidate_index: int) -> ScenarioCandidate:
    scenarios = bundle.scenarios["scenarios"]
    if scenario_id not in scenarios:
        raise ProtocolValidationError(f"unknown scenario: {scenario_id}")
    scenario = scenarios[scenario_id]
    candidates = scenario["candidate_order"]
    if not 0 <= candidate_index < len(candidates):
        raise ProtocolValidationError(f"candidate index out of range: {scenario_id}/{candidate_index}")
    values: dict[str, Any] = dict(candidates[candidate_index])
    candidate_id = values.pop("candidate_id")
    return ScenarioCandidate(
        scenario_id=scenario_id,
        semantic_family=scenario["semantic_family"],
        candidate_id=candidate_id,
        values=values,
    )


def scenario_candidate_by_id(
    bundle: ProtocolBundle, scenario_id: str, candidate_id: str
) -> ScenarioCandidate:
    try:
        candidates = bundle.scenarios["scenarios"][scenario_id]["candidate_order"]
    except KeyError as exc:
        raise ProtocolValidationError(f"unknown scenario: {scenario_id}") from exc
    matches = [index for index, item in enumerate(candidates) if item.get("candidate_id") == candidate_id]
    if len(matches) != 1:
        raise ProtocolValidationError(f"unknown or duplicate candidate: {scenario_id}/{candidate_id}")
    return scenario_candidate(bundle, scenario_id, matches[0])
