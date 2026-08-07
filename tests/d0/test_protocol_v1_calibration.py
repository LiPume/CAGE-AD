from __future__ import annotations

import pytest

from cage_ad.protocol_v1.calibration import (
    RunEvidence,
    calibration_gate_config,
    evaluate_dose_gate,
    evaluate_nominal_gate,
    evaluate_probe_gate,
)
from cage_ad.protocol_v1.loader import load_protocol
from pathlib import Path


CONFIG = calibration_gate_config(load_protocol(Path(__file__).resolve().parents[2]))


def _run(
    seed: int,
    *,
    risk_ttc: float | None = 5.0,
    collision: bool = False,
    activated: bool | None = None,
    x_offset: float = 0.0,
    runtime_valid: bool = True,
) -> RunEvidence:
    collision_payload = {
        "collision_count": int(collision),
        "minimum_ttc_s": risk_ttc,
        "collision_object_id": "cage_interaction_actor" if collision else None,
        "collision_position_m": [10.0, 0.0] if collision else None,
        "collision_angle_deg": 0.0 if collision else None,
        "collision_relative_speed_mps": 3.0 if collision else None,
    }
    return RunEvidence(
        seed=seed,
        runtime_valid=runtime_valid,
        route_accepted=runtime_valid,
        safety=collision_payload,
        task={"route_completion": 0.5, "forward_progress_m": 40.0, "timeout": True},
        mechanism=(
            None
            if activated is None
            else {"activated": activated, "activation_onset_s": 5.0 if activated else None}
        ),
        samples=[
            {
                "simulator_time_s": index * 0.05,
                "ego_x_m": index * 0.1 + x_offset,
                "ego_y_m": 0.0,
                "obb_ttc_s": (
                    5.0 if activated and index * 0.05 < 5.0 else risk_ttc
                ),
            }
            for index in range(200)
        ],
    )


def test_nominal_gate_exact_open_closed_ttc_band():
    runs = [_run(seed, risk_ttc=value) for seed, value in zip(range(5), [2.5001, 3.0, 4.0, 6.0, 2.5])]
    result = evaluate_nominal_gate(runs, CONFIG)
    assert result.passed and result.ttc_in_band == 4
    failed = evaluate_nominal_gate([_run(seed, risk_ttc=None) for seed in range(5)], CONFIG)
    assert not failed.passed and "nominal_outside_sensitivity_band" in failed.reasons


def test_dose_gate_requires_activation_degradation_temporal_order_and_collision_identity():
    nominal = {seed: _run(seed, risk_ttc=5.0) for seed in (1101, 1102, 1103)}
    fault = [_run(seed, risk_ttc=2.5, activated=True) for seed in nominal]
    result = evaluate_dose_gate(nominal, fault, CONFIG)
    assert result.passed
    assert result.risk_increase_repeats == 3 and result.temporally_causal_repeats == 3
    inactive = fault[:]
    inactive[0] = _run(1101, risk_ttc=2.5, activated=False)
    result = evaluate_dose_gate(nominal, inactive, CONFIG)
    assert not result.passed and "fault_not_activated" in result.reasons


def test_dose_gate_rejects_one_nonreproducible_collision():
    nominal = {seed: _run(seed, risk_ttc=5.0) for seed in (1101, 1102, 1103)}
    fault = [
        _run(1101, risk_ttc=2.5, collision=True, activated=True),
        _run(1102, risk_ttc=2.5, activated=True),
        _run(1103, risk_ttc=2.5, activated=True),
    ]
    result = evaluate_dose_gate(nominal, fault, CONFIG)
    assert not result.passed and result.collision_identity is False


def test_probe_gate_classifies_selective_effect_and_checks_regression_harm():
    seeds = (1101, 1102, 1103)
    no_probe = {seed: _run(seed, risk_ttc=2.5) for seed in seeds}
    probes = {
        "interaction_forecasting": {seed: _run(seed, risk_ttc=5.0) for seed in seeds},
        "motion_planning": {seed: _run(seed, risk_ttc=2.8) for seed in seeds},
        "tracking_execution": {seed: _run(seed, risk_ttc=2.7) for seed in seeds},
    }
    regression_seeds = range(3101, 3106)
    regression_nominal = {seed: _run(seed, risk_ttc=5.0) for seed in regression_seeds}
    regression = {
        domain: {seed: _run(seed, risk_ttc=5.0) for seed in regression_seeds}
        for domain in probes
    }
    result = evaluate_probe_gate(
        correct_domain="interaction_forecasting",
        trigger_start_s=5.0,
        no_probe_by_seed=no_probe,
        probes_by_domain=probes,
        regression_nominal_by_seed=regression_nominal,
        regression_probes_by_domain=regression,
        base_gates_pass=True,
        no_oracle_leakage=True,
        config=CONFIG,
    )
    assert result.passed and result.classification == "identifiable"
    assert result.regression_harm_rate == 0.0
    regression["motion_planning"][3101] = _run(3101, risk_ttc=2.0)
    harmed = evaluate_probe_gate(
        correct_domain="interaction_forecasting",
        trigger_start_s=5.0,
        no_probe_by_seed=no_probe,
        probes_by_domain=probes,
        regression_nominal_by_seed=regression_nominal,
        regression_probes_by_domain=regression,
        base_gates_pass=True,
        no_oracle_leakage=True,
        config=CONFIG,
    )
    assert not harmed.passed and harmed.reason == "probe_invalid"


def test_probe_gate_rejects_pre_intervention_mismatch():
    seeds = (1101, 1102, 1103)
    no_probe = {seed: _run(seed, risk_ttc=2.5) for seed in seeds}
    probes = {
        "interaction_forecasting": {seed: _run(seed, risk_ttc=5.0, x_offset=1.0) for seed in seeds},
        "motion_planning": {seed: _run(seed, risk_ttc=2.8) for seed in seeds},
        "tracking_execution": {seed: _run(seed, risk_ttc=2.8) for seed in seeds},
    }
    regression_seeds = range(3101, 3106)
    nominal_regression = {seed: _run(seed) for seed in regression_seeds}
    regression = {domain: {seed: _run(seed) for seed in regression_seeds} for domain in probes}
    result = evaluate_probe_gate(
        correct_domain="interaction_forecasting",
        trigger_start_s=5.0,
        no_probe_by_seed=no_probe,
        probes_by_domain=probes,
        regression_nominal_by_seed=nominal_regression,
        regression_probes_by_domain=regression,
        base_gates_pass=True,
        no_oracle_leakage=True,
        config=CONFIG,
    )
    assert not result.passed and result.reason == "probe_invalid"
