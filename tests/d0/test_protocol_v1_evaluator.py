from __future__ import annotations

from pathlib import Path

import pytest

from cage_ad.protocol_v1.evaluator import (
    AttributionEvidence,
    CollisionEvent,
    InfrastructureOutcome,
    MechanismObservation,
    OrientedBox,
    RiskTick,
    SafetyOutcome,
    classify_attribution,
    collision_events_match,
    collision_identity_reproducible,
    degradation_onset,
    evaluate_mechanism_activation,
    minimum_run_ttc,
    oriented_box_ttc,
    oriented_boxes_overlap,
    pre_intervention_trajectory_mse,
    temporal_causality_passes,
)
from cage_ad.protocol_v1.loader import load_protocol


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def protocol():
    return load_protocol(ROOT)


def test_oriented_box_overlap_uses_heading_and_inclusive_contact():
    ego = OrientedBox(0.0, 0.0, 0.0, 4.0, 2.0)
    touching = OrientedBox(4.0, 0.0, 0.0, 4.0, 2.0)
    separated = OrientedBox(4.01, 0.0, 0.0, 4.0, 2.0)
    rotated = OrientedBox(0.0, 2.0, 1.5707963267948966, 4.0, 2.0)
    assert oriented_boxes_overlap(ego, touching)
    assert not oriented_boxes_overlap(ego, separated)
    assert oriented_boxes_overlap(ego, rotated)


def test_oriented_box_ttc_uses_constant_linear_velocity_grid():
    ego = OrientedBox(0.0, 0.0, 0.0, 4.0, 2.0, velocity_x=5.0)
    actor = OrientedBox(10.0, 0.0, 0.0, 4.0, 2.0)
    assert oriented_box_ttc(ego, actor) == pytest.approx(1.2)
    assert oriented_box_ttc(ego, actor, horizon_s=1.0) is None
    parallel = OrientedBox(10.0, 5.0, 0.0, 4.0, 2.0, velocity_x=5.0)
    assert oriented_box_ttc(ego, parallel) is None
    with pytest.raises(ValueError, match="positive"):
        oriented_box_ttc(ego, actor, step_s=0.0)


def test_minimum_run_ttc_ignores_current_overlap_and_null_ticks():
    overlap = (
        OrientedBox(0.0, 0.0, 0.0, 4.0, 2.0),
        OrientedBox(0.0, 0.0, 0.0, 4.0, 2.0),
    )
    future = (
        OrientedBox(0.0, 0.0, 0.0, 4.0, 2.0, velocity_x=5.0),
        OrientedBox(7.0, 0.0, 0.0, 4.0, 2.0),
    )
    assert minimum_run_ttc([overlap, future]) == pytest.approx(0.6)


def test_infrastructure_gate_is_independent_from_safety():
    valid = InfrastructureOutcome(True, True, True, True, 20, 20, False, 0)
    assert valid.valid
    assert not InfrastructureOutcome(True, True, True, True, 19, 20, False, 0).valid
    assert not InfrastructureOutcome(True, True, True, True, 20, 20, False, 1).valid
    assert not InfrastructureOutcome(True, True, True, True, 20, 20, True, 0).valid
    assert SafetyOutcome(0, None).risk_score == 0.0
    assert SafetyOutcome(0, 5.0).risk_score == pytest.approx(0.5)
    assert SafetyOutcome(0, 2.5).risk_score == 1.0
    assert SafetyOutcome(1, None).risk_score == 1.0


def test_delay_activation_threshold_and_window_are_inclusive(protocol):
    observations = [
        MechanismObservation(4.99, 999.0),
        *[MechanismObservation(time, 0.9) for time in (5.0, 6.0, 7.0, 8.0, 9.0)],
        MechanismObservation(9.01, -999.0),
    ]
    outcome = evaluate_mechanism_activation(
        protocol,
        "forecast_stale_or_delayed",
        {"delay_s": 1.0},
        observations,
        (5.0, 9.0),
    )
    assert outcome.activated
    assert outcome.passing_fraction == 1.0
    assert outcome.samples_in_window == 5
    assert outcome.activation_onset_s == 5.0


def test_activation_operator_strictness_fraction_and_residual(protocol):
    strict = evaluate_mechanism_activation(
        protocol,
        "forecast_heading_or_maneuver_bias",
        {"attenuation": 0.5},
        [MechanismObservation(float(index), 0.25, 0.0) for index in range(5)],
        (0.0, 4.0),
    )
    assert not strict.activated
    fraction_boundary = evaluate_mechanism_activation(
        protocol,
        "planning_constraint_omitted",
        {"braking_attenuation": 0.5},
        [
            MechanismObservation(0.0, 0.51, 0.10),
            MechanismObservation(1.0, 0.51, 0.10),
            MechanismObservation(2.0, 0.51, 0.10),
            MechanismObservation(3.0, 0.50, 0.10),
            MechanismObservation(4.0, 0.51, 0.11),
        ],
        (0.0, 4.0),
    )
    assert fraction_boundary.activated
    assert fraction_boundary.passing_fraction == pytest.approx(0.6)


def test_within_tolerance_activation_accepts_exact_boundary(protocol):
    outcome = evaluate_mechanism_activation(
        protocol,
        "planning_unsafe_cost_or_speed_bias",
        {"time_scale": 0.8},
        [MechanismObservation(float(index), value) for index, value in enumerate([0.78] * 4 + [0.77])],
        (0.0, 4.0),
    )
    assert outcome.activated
    assert outcome.passing_fraction == pytest.approx(0.8)


def test_collision_identity_requires_same_physical_event_and_two_repeats():
    anchor = CollisionEvent("actor-7", (10.0, 20.0), 179.0, 4.0)
    boundary = CollisionEvent("actor-7", (12.0, 20.0), -166.0, 6.0)
    wrong_actor = CollisionEvent("actor-8", (10.0, 20.0), 179.0, 4.0)
    assert collision_events_match(anchor, boundary)
    assert not collision_events_match(anchor, wrong_actor)
    assert collision_identity_reproducible([]) is None
    assert not collision_identity_reproducible([anchor])
    assert collision_identity_reproducible([anchor, boundary, wrong_actor])


def test_temporal_causality_and_aligned_degradation_boundaries():
    nominal = [RiskTick(1.0, False, 5.0), RiskTick(2.0, False, 5.0)]
    fault = [RiskTick(1.0, False, 5.0), RiskTick(2.0, False, 2.7777777777777777)]
    assert degradation_onset(fault, nominal) == 2.0
    assert temporal_causality_passes(1.0, 6.0)
    assert not temporal_causality_passes(1.0, 6.001)
    assert not temporal_causality_passes(2.0, 1.9)
    assert not temporal_causality_passes(None, 2.0)


def test_pre_intervention_mse_requires_aligned_nonempty_trajectories():
    assert pre_intervention_trajectory_mse([(0.0, 0.0), (1.0, 0.0)], [(0.0, 0.0), (1.0, 0.5)]) == pytest.approx(0.125)
    assert pre_intervention_trajectory_mse([], []) is None
    assert pre_intervention_trajectory_mse([(0.0, 0.0)], []) is None


def _attribution(**overrides) -> AttributionEvidence:
    values = dict(
        correct_domain="forecasting",
        fault_risks={1: 0.8, 2: 0.8, 3: 0.5},
        probe_risks_by_domain={
            "forecasting": {1: 0.5, 2: 0.6, 3: 0.5},
            "planning": {1: 0.72, 2: 0.71, 3: 0.5},
            "control": {1: 0.75, 2: 0.73, 3: 0.5},
        },
        base_gates_pass=True,
        probe_valid=True,
        no_oracle_leakage=True,
    )
    values.update(overrides)
    return AttributionEvidence(**values)


def test_classification_identifiable_only_after_correct_effect_and_strict_margin():
    result = classify_attribution(_attribution())
    assert result.classification == "identifiable"
    assert result.correct_domain_median_delta == pytest.approx(0.2)
    assert result.correct_positive_repeats == 2
    equal_margin = _attribution(
        probe_risks_by_domain={
            "forecasting": {1: 0.5, 2: 0.6, 3: 0.5},
            "planning": {1: 0.7, 2: 0.7, 3: 0.5},
            "control": {1: 0.8, 2: 0.8, 3: 0.5},
        }
    )
    result = classify_attribution(equal_margin)
    assert result.classification == "ambiguous"
    assert result.reason == "nonselective_probe_effect"


def test_classification_precedence_rejects_invalid_or_leaky_evidence():
    assert classify_attribution(_attribution(base_gates_pass=False)).reason == "base_gate_failed"
    assert classify_attribution(_attribution(no_oracle_leakage=False)).reason == "oracle_leakage"
    assert classify_attribution(_attribution(probe_valid=False)).reason == "probe_invalid"
    assert classify_attribution(_attribution(temporal_causality_pass=False)).reason == "temporal_causality_failed"
    overlap = classify_attribution(_attribution(multi_domain_overlap=True))
    assert overlap.classification == "ambiguous" and overlap.reason == "multi_domain_overlap"


def test_classification_rejects_unpaired_probe_runs():
    malformed = _attribution(
        probe_risks_by_domain={
            "forecasting": {1: 0.5, 2: 0.6},
            "planning": {1: 0.7, 2: 0.7, 3: 0.5},
        }
    )
    with pytest.raises(ValueError, match="unpaired"):
        classify_attribution(malformed)
