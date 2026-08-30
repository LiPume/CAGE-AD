"""Five-layer, protocol-v1 evaluation with oriented-box safety geometry."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Mapping, Sequence

from .loader import ProtocolBundle, ProtocolValidationError


@dataclass(frozen=True)
class OrientedBox:
    x: float
    y: float
    heading: float
    length: float
    width: float
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    object_id: str = ""

    def at(self, seconds: float) -> "OrientedBox":
        return OrientedBox(
            x=self.x + self.velocity_x * seconds,
            y=self.y + self.velocity_y * seconds,
            heading=self.heading,
            length=self.length,
            width=self.width,
            velocity_x=self.velocity_x,
            velocity_y=self.velocity_y,
            object_id=self.object_id,
        )

    def corners(self) -> tuple[tuple[float, float], ...]:
        forward = (math.cos(self.heading), math.sin(self.heading))
        left = (-forward[1], forward[0])
        half_length, half_width = self.length / 2.0, self.width / 2.0
        return tuple(
            (
                self.x + longitudinal * forward[0] + lateral * left[0],
                self.y + longitudinal * forward[1] + lateral * left[1],
            )
            for longitudinal, lateral in (
                (half_length, half_width),
                (half_length, -half_width),
                (-half_length, -half_width),
                (-half_length, half_width),
            )
        )


def _projection(points: Sequence[tuple[float, float]], axis: tuple[float, float]) -> tuple[float, float]:
    values = [x * axis[0] + y * axis[1] for x, y in points]
    return min(values), max(values)


def oriented_boxes_overlap(left: OrientedBox, right: OrientedBox) -> bool:
    if min(left.length, left.width, right.length, right.width) <= 0.0:
        raise ProtocolValidationError("oriented box dimensions must be positive")
    left_corners, right_corners = left.corners(), right.corners()
    axes = []
    for box in (left, right):
        axes.extend(
            [
                (math.cos(box.heading), math.sin(box.heading)),
                (-math.sin(box.heading), math.cos(box.heading)),
            ]
        )
    for axis in axes:
        left_min, left_max = _projection(left_corners, axis)
        right_min, right_max = _projection(right_corners, axis)
        if left_max < right_min or right_max < left_min:
            return False
    return True


def oriented_box_ttc(
    ego: OrientedBox,
    interaction_actor: OrientedBox,
    *,
    horizon_s: float = 10.0,
    step_s: float = 0.05,
) -> float | None:
    if horizon_s <= 0.0 or step_s <= 0.0:
        raise ProtocolValidationError("TTC horizon and step must be positive")
    steps = int(round(horizon_s / step_s))
    for index in range(steps + 1):
        seconds = index * step_s
        if oriented_boxes_overlap(ego.at(seconds), interaction_actor.at(seconds)):
            return seconds
    return None


def minimum_run_ttc(samples: Sequence[tuple[OrientedBox, OrientedBox]]) -> float | None:
    positive = [
        value
        for ego, actor in samples
        if (value := oriented_box_ttc(ego, actor)) is not None and value > 0.0
    ]
    return min(positive) if positive else None


@dataclass(frozen=True)
class InfrastructureOutcome:
    apollo_modules_healthy: bool
    route_accepted: bool
    actor_spawned: bool
    clock_advanced: bool
    planning_messages: int
    guarded_control_messages: int
    injector_exception: bool
    non_unit_frame_gaps: int = 0

    @property
    def valid(self) -> bool:
        return (
            self.apollo_modules_healthy
            and self.route_accepted
            and self.actor_spawned
            and self.clock_advanced
            and self.planning_messages >= 20
            and self.guarded_control_messages >= 20
            and not self.injector_exception
            and self.non_unit_frame_gaps == 0
        )


@dataclass(frozen=True)
class SafetyOutcome:
    collision_count: int
    minimum_ttc_s: float | None
    collision_object_id: str | None = None
    collision_position_m: tuple[float, float] | None = None
    collision_angle_deg: float | None = None
    collision_relative_speed_mps: float | None = None

    @property
    def risk_score(self) -> float:
        if self.collision_count > 0:
            return 1.0
        if self.minimum_ttc_s is None:
            return 0.0
        if self.minimum_ttc_s <= 0.0:
            return 1.0
        return _clamp(2.5 / self.minimum_ttc_s, 0.0, 1.0)


@dataclass(frozen=True)
class TaskOutcome:
    route_completion: float
    forward_progress_m: float
    timeout: bool


@dataclass(frozen=True)
class MechanismObservation:
    simulator_time_s: float
    metric_value: float
    transform_residual: float | None = None


@dataclass(frozen=True)
class MechanismOutcome:
    fault_id: str
    activated: bool
    activation_onset_s: float | None
    passing_fraction: float
    samples_in_window: int


@dataclass(frozen=True)
class AttributionOutcome:
    classification: str
    correct_domain_median_delta: float | None
    best_wrong_domain_median_delta: float | None
    correct_positive_repeats: int
    reason: str


@dataclass(frozen=True)
class EpisodeOutcome:
    infrastructure: InfrastructureOutcome
    safety: SafetyOutcome
    task: TaskOutcome
    mechanism: MechanismOutcome
    attribution: AttributionOutcome | None = None


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def evaluate_mechanism_activation(
    bundle: ProtocolBundle,
    fault_id: str,
    dose: Mapping[str, float],
    observations: Sequence[MechanismObservation],
    trigger_window: tuple[float, float],
) -> MechanismOutcome:
    try:
        recipe = bundle.faults["faults"][fault_id]
    except KeyError as exc:
        raise ProtocolValidationError(f"unknown fault activation recipe: {fault_id}") from exc
    signature = recipe["activation_signature"]
    start_s, end_s = trigger_window
    if end_s < start_s:
        raise ProtocolValidationError("activation window is reversed")
    window = [item for item in observations if start_s <= item.simulator_time_s <= end_s]
    if not window:
        return MechanismOutcome(fault_id, False, None, 0.0, 0)
    operator = signature["operator"]
    expected = None
    if "expected_from_dose_field" in signature:
        field = signature["expected_from_dose_field"]
        if field not in dose:
            raise ProtocolValidationError(f"activation dose field missing: {field}")
        expected = float(dose[field])

    def passes(item: MechanismObservation) -> bool:
        if operator == "greater_or_equal":
            boundary = expected - float(signature.get("lower_tolerance", 0.0))
            passed = item.metric_value > boundary or math.isclose(item.metric_value, boundary, abs_tol=1e-12)
        elif operator == "greater_than":
            passed = item.metric_value > float(signature["threshold"])
        elif operator == "within_absolute_tolerance":
            difference = abs(item.metric_value - expected)
            tolerance = float(signature["absolute_tolerance"])
            passed = difference < tolerance or math.isclose(difference, tolerance, abs_tol=1e-12)
        else:
            raise ProtocolValidationError(f"unsupported activation operator: {operator}")
        residual_limit = next(
            (
                float(value)
                for key, value in signature.items()
                if key.startswith("declared_transform_residual_max")
            ),
            None,
        )
        if residual_limit is not None:
            passed = (
                passed
                and item.transform_residual is not None
                and (
                    item.transform_residual < residual_limit
                    or math.isclose(item.transform_residual, residual_limit, abs_tol=1e-12)
                )
            )
        return passed

    decisions = [passes(item) for item in window]
    fraction = sum(decisions) / len(decisions)
    required = float(signature["required_fraction_of_window"])
    activated = fraction >= required
    onset = next(
        (item.simulator_time_s for item, passed in zip(window, decisions) if passed),
        None,
    )
    return MechanismOutcome(fault_id, activated, onset if activated else None, fraction, len(window))


@dataclass(frozen=True)
class CollisionEvent:
    counterpart_id: str
    position_m: tuple[float, float]
    angle_deg: float
    relative_speed_mps: float


def _wrapped_degrees_difference(right: float, left: float) -> float:
    return abs((right - left + 180.0) % 360.0 - 180.0)


def collision_events_match(
    left: CollisionEvent,
    right: CollisionEvent,
    *,
    position_tolerance_m: float = 2.0,
    angle_tolerance_deg: float = 15.0,
    relative_speed_tolerance_mps: float = 2.0,
) -> bool:
    return (
        left.counterpart_id == right.counterpart_id
        and math.dist(left.position_m, right.position_m) <= position_tolerance_m
        and _wrapped_degrees_difference(left.angle_deg, right.angle_deg) <= angle_tolerance_deg
        and abs(left.relative_speed_mps - right.relative_speed_mps) <= relative_speed_tolerance_mps
    )


def collision_identity_reproducible(
    events: Sequence[CollisionEvent],
    *,
    required_matching_repeats: int = 2,
    position_tolerance_m: float = 2.0,
    angle_tolerance_deg: float = 15.0,
    relative_speed_tolerance_mps: float = 2.0,
) -> bool | None:
    if not events:
        return None
    return any(
        sum(
            collision_events_match(
                anchor,
                candidate,
                position_tolerance_m=position_tolerance_m,
                angle_tolerance_deg=angle_tolerance_deg,
                relative_speed_tolerance_mps=relative_speed_tolerance_mps,
            )
            for candidate in events
        )
        >= required_matching_repeats
        for anchor in events
    )


@dataclass(frozen=True)
class RiskTick:
    simulator_time_s: float
    collision: bool
    ttc_s: float | None

    @property
    def risk(self) -> float:
        return SafetyOutcome(int(self.collision), self.ttc_s).risk_score


def degradation_onset(
    fault_ticks: Sequence[RiskTick], nominal_ticks: Sequence[RiskTick]
) -> float | None:
    nominal_by_time = {round(item.simulator_time_s, 6): item for item in nominal_ticks}
    for fault in fault_ticks:
        nominal = nominal_by_time.get(round(fault.simulator_time_s, 6))
        if nominal is None:
            continue
        if fault.collision or fault.risk - nominal.risk >= 0.20:
            return fault.simulator_time_s
    return None


def temporal_causality_passes(
    mechanism_onset_s: float | None,
    system_degradation_onset_s: float | None,
    *,
    maximum_delay_s: float = 5.0,
) -> bool:
    return (
        mechanism_onset_s is not None
        and system_degradation_onset_s is not None
        and mechanism_onset_s <= system_degradation_onset_s
        and system_degradation_onset_s - mechanism_onset_s <= maximum_delay_s
    )


def pre_intervention_trajectory_mse(
    nominal_xy: Sequence[tuple[float, float]], probe_xy: Sequence[tuple[float, float]]
) -> float | None:
    if len(nominal_xy) != len(probe_xy) or not nominal_xy:
        return None
    return sum(
        (nominal[0] - probe[0]) ** 2 + (nominal[1] - probe[1]) ** 2
        for nominal, probe in zip(nominal_xy, probe_xy)
    ) / len(nominal_xy)


@dataclass(frozen=True)
class AttributionEvidence:
    correct_domain: str
    fault_risks: Mapping[int, float]
    probe_risks_by_domain: Mapping[str, Mapping[int, float]]
    base_gates_pass: bool
    probe_valid: bool
    no_oracle_leakage: bool
    collision_identity_pass: bool = True
    temporal_causality_pass: bool = True
    multi_domain_overlap: bool = False


def classify_attribution(
    evidence: AttributionEvidence,
    *,
    correct_domain_minimum_median_delta: float = 0.20,
    correct_domain_positive_repeats_required: int = 2,
    wrong_domain_margin: float = 0.10,
) -> AttributionOutcome:
    if not evidence.base_gates_pass:
        return AttributionOutcome("rejected", None, None, 0, "base_gate_failed")
    if not evidence.no_oracle_leakage:
        return AttributionOutcome("rejected", None, None, 0, "oracle_leakage")
    if not evidence.collision_identity_pass:
        return AttributionOutcome("rejected", None, None, 0, "collision_identity_not_reproducible")
    if not evidence.temporal_causality_pass:
        return AttributionOutcome("rejected", None, None, 0, "temporal_causality_failed")
    if not evidence.probe_valid:
        return AttributionOutcome("rejected", None, None, 0, "probe_invalid")
    if evidence.correct_domain not in evidence.probe_risks_by_domain:
        raise ProtocolValidationError("correct-domain probe evidence missing")
    seeds = set(evidence.fault_risks)
    if not seeds:
        raise ProtocolValidationError("paired attribution evidence is empty")
    for domain, values in evidence.probe_risks_by_domain.items():
        if set(values) != seeds:
            raise ProtocolValidationError(f"unpaired probe risks for domain: {domain}")
    deltas = {
        domain: [evidence.fault_risks[seed] - values[seed] for seed in sorted(seeds)]
        for domain, values in evidence.probe_risks_by_domain.items()
    }
    correct_values = deltas[evidence.correct_domain]
    correct_median = median(correct_values)
    correct_positive = sum(value > 0.0 for value in correct_values)
    wrong_medians = [
        median(values) for domain, values in deltas.items() if domain != evidence.correct_domain
    ]
    if not wrong_medians:
        raise ProtocolValidationError("wrong-domain probe evidence missing")
    best_wrong = max(wrong_medians)
    if evidence.multi_domain_overlap:
        return AttributionOutcome(
            "ambiguous", correct_median, best_wrong, correct_positive, "multi_domain_overlap"
        )
    if (
        correct_median < correct_domain_minimum_median_delta
        or correct_positive < correct_domain_positive_repeats_required
    ):
        return AttributionOutcome(
            "ambiguous", correct_median, best_wrong, correct_positive, "insufficient_correct_effect"
        )
    if correct_median - best_wrong <= wrong_domain_margin:
        return AttributionOutcome(
            "ambiguous", correct_median, best_wrong, correct_positive, "nonselective_probe_effect"
        )
    return AttributionOutcome(
        "identifiable", correct_median, best_wrong, correct_positive, "all_gates_passed"
    )
