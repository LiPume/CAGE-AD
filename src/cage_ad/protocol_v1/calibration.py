"""Pure gate aggregation for one protocol-v1 calibration recipe."""

from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import median
from typing import Any, Mapping, Sequence

from .evaluator import (
    AttributionEvidence,
    CollisionEvent,
    RiskTick,
    SafetyOutcome,
    classify_attribution,
    collision_identity_reproducible,
    degradation_onset,
    pre_intervention_trajectory_mse,
    temporal_causality_passes,
)
from .loader import ProtocolBundle, ProtocolValidationError


@dataclass(frozen=True)
class CalibrationGateConfig:
    nominal_repeats: int
    nominal_ttc_lower_exclusive: float
    nominal_ttc_upper_inclusive: float
    nominal_ttc_in_band_required: int
    fault_repeats: int
    paired_risk_increase_minimum: float
    safety_degradation_required: int
    maximum_causal_delay_s: float
    collision_matching_repeats: int
    collision_position_tolerance_m: float
    collision_angle_tolerance_deg: float
    collision_relative_speed_tolerance_mps: float
    pre_intervention_mse_max_m2: float
    correct_domain_minimum_median_delta: float
    correct_domain_positive_repeats_required: int
    wrong_domain_margin: float
    regression_harm_rate_max: float
    regression_repeats: int


def calibration_gate_config(bundle: ProtocolBundle) -> CalibrationGateConfig:
    admission = bundle.scenarios["scenario_admission"]
    quality = bundle.quality_gates
    fault = quality["calibration_gates"]["selected_fault"]
    collision = quality["calibration_gates"]["collision_identity_when_collision_occurs"]
    paired = quality["paired_effect"]
    ttc = admission["nominal_min_ttc_s"]
    margin_match = re.search(r"strictly_greater_than_0_([0-9]+)$", paired["wrong_domain_margin"])
    if margin_match is None:
        raise ProtocolValidationError("cannot parse normative wrong-domain margin")
    wrong_domain_margin = float("0." + margin_match.group(1))
    return CalibrationGateConfig(
        nominal_repeats=len(admission["calibration_trials_per_candidate"]["seeds"]),
        nominal_ttc_lower_exclusive=float(ttc["lower_exclusive"]),
        nominal_ttc_upper_inclusive=float(ttc["upper_inclusive"]),
        nominal_ttc_in_band_required=int(ttc["required_repeats_in_band"]),
        fault_repeats=int(fault["repeats"]),
        paired_risk_increase_minimum=float(fault["paired_risk_increase_minimum"]),
        safety_degradation_required=int(fault["safety_degradation_required"]),
        maximum_causal_delay_s=float(
            quality["calibration_gates"]["temporal_causality"]["maximum_trigger_to_degradation_delay_s"]
        ),
        collision_matching_repeats=int(collision["required_matching_repeats"]),
        collision_position_tolerance_m=float(collision["collision_position_tolerance_m"]),
        collision_angle_tolerance_deg=float(collision["collision_angle_tolerance_deg"]),
        collision_relative_speed_tolerance_mps=float(collision["collision_relative_speed_tolerance_mps"]),
        pre_intervention_mse_max_m2=float(paired["pre_intervention_trajectory_mse_max_m2"]),
        correct_domain_minimum_median_delta=float(paired["correct_domain_minimum_median_delta"]),
        correct_domain_positive_repeats_required=int(paired["correct_domain_positive_repeats_required"]),
        wrong_domain_margin=wrong_domain_margin,
        regression_harm_rate_max=float(paired["regression_false_repair_or_harm_rate_max"]),
        regression_repeats=len(bundle.probes["common"]["fault_free_regression_seeds"]),
    )


@dataclass(frozen=True)
class RunEvidence:
    seed: int
    runtime_valid: bool
    route_accepted: bool
    safety: Mapping[str, Any]
    task: Mapping[str, Any]
    mechanism: Mapping[str, Any] | None
    samples: Sequence[Mapping[str, Any]]

    @property
    def risk(self) -> float:
        return SafetyOutcome(
            collision_count=int(self.safety["collision_count"]),
            minimum_ttc_s=self.safety.get("minimum_ttc_s"),
        ).risk_score

    @property
    def collision_event(self) -> CollisionEvent | None:
        if int(self.safety["collision_count"]) <= 0:
            return None
        return CollisionEvent(
            counterpart_id=str(self.safety["collision_object_id"]),
            position_m=tuple(map(float, self.safety["collision_position_m"])),
            angle_deg=float(self.safety["collision_angle_deg"]),
            relative_speed_mps=float(self.safety["collision_relative_speed_mps"]),
        )


@dataclass(frozen=True)
class NominalGateResult:
    passed: bool
    runtime_valid: int
    collision_free: int
    route_accepted: int
    ttc_in_band: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DoseGateResult:
    passed: bool
    runtime_valid: int
    mechanism_activated: int
    risk_increase_repeats: int
    temporally_causal_repeats: int
    collision_identity: bool | None
    paired_risk_increases: Mapping[int, float]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ProbeGateResult:
    passed: bool
    classification: str
    reason: str
    pre_intervention_mse: Mapping[str, Mapping[int, float | None]]
    regression_harm_rate: float
    median_effect_by_domain: Mapping[str, float]
    correct_positive_repeats: int
    correct_minus_best_wrong: float


def evaluate_nominal_gate(
    runs: Sequence[RunEvidence], config: CalibrationGateConfig
) -> NominalGateResult:
    if len(runs) != config.nominal_repeats or len({run.seed for run in runs}) != config.nominal_repeats:
        raise ProtocolValidationError("nominal gate requires five unique calibration seeds")
    runtime_valid = sum(run.runtime_valid for run in runs)
    collision_free = sum(int(run.safety["collision_count"]) == 0 for run in runs)
    route_accepted = sum(run.route_accepted for run in runs)
    ttc_in_band = sum(
        run.safety.get("minimum_ttc_s") is not None
        and float(run.safety["minimum_ttc_s"]) > config.nominal_ttc_lower_exclusive
        and float(run.safety["minimum_ttc_s"]) <= config.nominal_ttc_upper_inclusive
        for run in runs
    )
    reasons = []
    if runtime_valid != config.nominal_repeats:
        reasons.append("infrastructure_invalid")
    if collision_free != config.nominal_repeats:
        reasons.append("nominal_unsafe")
    if route_accepted != config.nominal_repeats:
        reasons.append("nominal_route_not_accepted")
    if ttc_in_band < config.nominal_ttc_in_band_required:
        reasons.append("nominal_outside_sensitivity_band")
    return NominalGateResult(not reasons, runtime_valid, collision_free, route_accepted, ttc_in_band, tuple(reasons))


def _risk_ticks(run: RunEvidence) -> list[RiskTick]:
    return [
        RiskTick(
            simulator_time_s=float(sample["simulator_time_s"]),
            collision=False,
            ttc_s=sample.get("obb_ttc_s"),
        )
        for sample in run.samples
    ]


def evaluate_dose_gate(
    nominal_by_seed: Mapping[int, RunEvidence],
    fault_runs: Sequence[RunEvidence],
    config: CalibrationGateConfig,
) -> DoseGateResult:
    if len(fault_runs) != config.fault_repeats or len({run.seed for run in fault_runs}) != config.fault_repeats:
        raise ProtocolValidationError("dose gate requires three unique calibration seeds")
    if set(run.seed for run in fault_runs) - set(nominal_by_seed):
        raise ProtocolValidationError("dose gate lacks same-seed nominal evidence")
    runtime_valid = sum(run.runtime_valid for run in fault_runs)
    activated = sum(bool(run.mechanism and run.mechanism.get("activated")) for run in fault_runs)
    increases = {
        run.seed: run.risk - nominal_by_seed[run.seed].risk for run in fault_runs
    }
    degraded = [
        run for run in fault_runs if increases[run.seed] >= config.paired_risk_increase_minimum
    ]
    causal = 0
    for run in degraded:
        mechanism_onset = None if run.mechanism is None else run.mechanism.get("activation_onset_s")
        system_onset = degradation_onset(_risk_ticks(run), _risk_ticks(nominal_by_seed[run.seed]))
        causal += temporal_causality_passes(
            mechanism_onset, system_onset, maximum_delay_s=config.maximum_causal_delay_s
        )
    collision_events = [event for run in fault_runs if (event := run.collision_event) is not None]
    identity = collision_identity_reproducible(
        collision_events,
        required_matching_repeats=config.collision_matching_repeats,
        position_tolerance_m=config.collision_position_tolerance_m,
        angle_tolerance_deg=config.collision_angle_tolerance_deg,
        relative_speed_tolerance_mps=config.collision_relative_speed_tolerance_mps,
    )
    reasons = []
    if runtime_valid != config.fault_repeats:
        reasons.append("infrastructure_invalid")
    if activated != config.fault_repeats:
        reasons.append("fault_not_activated")
    if len(degraded) < config.safety_degradation_required:
        reasons.append("no_paired_safety_degradation")
    if causal != len(degraded) or causal < config.safety_degradation_required:
        reasons.append("temporal_causality_failed")
    if identity is False:
        reasons.append("collision_identity_not_reproducible")
    return DoseGateResult(
        not reasons,
        runtime_valid,
        activated,
        len(degraded),
        causal,
        identity,
        increases,
        tuple(reasons),
    )


def _pre_window_xy(run: RunEvidence, trigger_start_s: float) -> list[tuple[float, float]]:
    return [
        (float(sample["ego_x_m"]), float(sample["ego_y_m"]))
        for sample in run.samples
        if float(sample["simulator_time_s"]) < trigger_start_s
    ]


def evaluate_probe_gate(
    *,
    correct_domain: str,
    trigger_start_s: float,
    no_probe_by_seed: Mapping[int, RunEvidence],
    probes_by_domain: Mapping[str, Mapping[int, RunEvidence]],
    regression_nominal_by_seed: Mapping[int, RunEvidence],
    regression_probes_by_domain: Mapping[str, Mapping[int, RunEvidence]],
    base_gates_pass: bool,
    no_oracle_leakage: bool,
    multi_domain_overlap: bool = False,
    config: CalibrationGateConfig,
) -> ProbeGateResult:
    required_domains = {"interaction_forecasting", "motion_planning", "tracking_execution"}
    if set(probes_by_domain) != required_domains or set(regression_probes_by_domain) != required_domains:
        raise ProtocolValidationError("probe gate requires exactly three responsibility domains")
    seeds = set(no_probe_by_seed)
    if len(seeds) != config.fault_repeats or any(set(runs) != seeds for runs in probes_by_domain.values()):
        raise ProtocolValidationError("probe gate requires paired seeds 1101-1103")
    regression_seeds = set(regression_nominal_by_seed)
    if len(regression_seeds) != config.regression_repeats or any(
        set(runs) != regression_seeds for runs in regression_probes_by_domain.values()
    ):
        raise ProtocolValidationError("probe regression gate requires five paired seeds")
    similarity: dict[str, dict[int, float | None]] = {}
    similarity_valid = True
    for domain, runs in probes_by_domain.items():
        similarity[domain] = {}
        for seed, probe in runs.items():
            value = pre_intervention_trajectory_mse(
                _pre_window_xy(no_probe_by_seed[seed], trigger_start_s),
                _pre_window_xy(probe, trigger_start_s),
            )
            similarity[domain][seed] = value
            similarity_valid &= value is not None and value <= config.pre_intervention_mse_max_m2
    all_probe_runtime_valid = all(
        run.runtime_valid for runs in probes_by_domain.values() for run in runs.values()
    ) and all(
        run.runtime_valid for runs in regression_probes_by_domain.values() for run in runs.values()
    ) and all(run.runtime_valid for run in regression_nominal_by_seed.values())
    harm = 0
    regression_pairs = 0
    for runs in regression_probes_by_domain.values():
        for seed, probe in runs.items():
            baseline = regression_nominal_by_seed[seed]
            regression_pairs += 1
            harm += (
                probe.risk - baseline.risk >= config.paired_risk_increase_minimum
                or (int(baseline.safety["collision_count"]) == 0 and int(probe.safety["collision_count"]) > 0)
            )
    harm_rate = harm / regression_pairs
    probe_valid = (
        all_probe_runtime_valid and similarity_valid and harm_rate <= config.regression_harm_rate_max
    )
    fault_risks = {seed: run.risk for seed, run in no_probe_by_seed.items()}
    probe_risks = {
        domain: {seed: run.risk for seed, run in runs.items()}
        for domain, runs in probes_by_domain.items()
    }
    attribution = classify_attribution(
        AttributionEvidence(
            correct_domain=correct_domain,
            fault_risks=fault_risks,
            probe_risks_by_domain=probe_risks,
            base_gates_pass=base_gates_pass,
            probe_valid=probe_valid,
            no_oracle_leakage=no_oracle_leakage,
            multi_domain_overlap=multi_domain_overlap,
        ),
        correct_domain_minimum_median_delta=config.correct_domain_minimum_median_delta,
        correct_domain_positive_repeats_required=config.correct_domain_positive_repeats_required,
        wrong_domain_margin=config.wrong_domain_margin,
    )
    medians = {
        domain: median(fault_risks[seed] - risks[seed] for seed in sorted(seeds))
        for domain, risks in probe_risks.items()
    }
    best_wrong = max(value for domain, value in medians.items() if domain != correct_domain)
    margin = medians[correct_domain] - best_wrong
    return ProbeGateResult(
        attribution.classification != "rejected",
        attribution.classification,
        attribution.reason,
        similarity,
        harm_rate,
        medians,
        attribution.correct_positive_repeats,
        margin,
    )
