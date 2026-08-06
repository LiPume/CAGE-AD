from __future__ import annotations

from cage_ad.adapters.apollo_d0.semantics import FaultMechanism
from cage_ad.adapters.apollo_d0.smoke import (
    evidence_payloads,
    forbidden_visible_tokens,
    mechanism_confirmed,
    task_failure,
)


def metrics(*, collision=0, motion=True):
    return {
        "collision_count": collision,
        "minimum_positive_ttc_s": 4.0,
        "minimum_separation_m": 8.0,
        "forward_progress_m": 6.0,
        "maximum_ego_speed_mps": 2.0,
        "route": {"success": True},
        "criteria": {"motion": motion},
        "wall_seconds": 32.0,
        "simulation_seconds": 32.0,
        "non_unit_frame_gaps": 0,
    }


def capture(*, forecast=0.0, plan=1.0, throttle=2.0):
    return {
        "forecast_samples": [
            {"t": 1.0, "horizon_end_displacement_m": forecast, "predicted_speed_end_mps": 1.0}
        ],
        "plan_samples": [{"t": 1.0, "point_count": 2, "max_speed_mps": plan, "min_speed_mps": 0.0}],
        "control_samples": [
            {"t": 1.0, "throttle_pct": throttle, "brake_pct": 0.0, "steering_pct": 0.0, "queued_targets": 0}
        ],
    }


def stats(**values):
    return {
        "prediction_out": 10,
        "planning_out": 10,
        "control_out": 10,
        "delayed_releases": 0,
        **values,
    }


def test_task_failure_includes_safety_and_task_criteria():
    assert not task_failure(metrics())
    assert task_failure(metrics(collision=1))
    assert task_failure(metrics(motion=False))


def test_mechanism_confirmation_uses_domain_specific_signal():
    ok, delta = mechanism_confirmed(
        FaultMechanism.PLAN_CONSTRAINT_OMITTED,
        capture(plan=1.0),
        stats(),
        capture(plan=6.0),
        stats(),
    )
    assert ok
    assert delta == 5.0
    ok, delta = mechanism_confirmed(
        FaultMechanism.CONTROL_TRANSPORT_DELAY,
        capture(),
        stats(),
        capture(),
        stats(delayed_releases=25),
    )
    assert ok
    assert delta == 25.0


def test_visible_evidence_is_allowlisted_and_has_all_three_probes():
    fault = (metrics(collision=1), capture(forecast=4.0, plan=7.0), stats())
    probes = {
        "interaction_forecasting": (metrics(), capture(), stats()),
        "motion_planning": (metrics(), capture(), stats()),
        "tracking_execution": (metrics(), capture(), stats()),
    }
    result = evidence_payloads([fault, fault, fault], probes)
    assert set(result) == {
        "O0_failure_summary",
        "O1_forecast_window",
        "O1_motion_plan_window",
        "O1_tracking_window",
        "O2_timing_metadata",
        "O3_semantic_replay",
        "I2_F_constant_velocity",
        "I2_P_safety_envelope",
        "I2_C_bounded_brake",
    }
    encoded = str(result).lower()
    assert "fault_mechanism" not in encoded
    assert "responsibility_domain" not in encoded


def test_forbidden_tokens_cover_private_mechanism_scenario_and_run_ids():
    oracle = {
        "fault_mechanism": "planning_constraint_omitted",
        "scenario_kind": "lead_vehicle_deceleration",
        "runs": {"nominal": "opaque_run_a", "fault_repeat_0": "opaque_run_b"},
    }
    assert forbidden_visible_tokens(oracle) == {
        "planning_constraint_omitted",
        "lead_vehicle_deceleration",
        "opaque_run_a",
        "opaque_run_b",
    }
