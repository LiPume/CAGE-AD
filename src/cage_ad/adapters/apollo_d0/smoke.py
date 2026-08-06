"""Pure aggregation and allowlisting for the D0-A0 closed-loop smoke."""

from __future__ import annotations

import hashlib
import json
import statistics
from typing import Any

from cage_ad.adapters.apollo_d0.semantics import DOMAIN_BY_MECHANISM, FaultMechanism


DOMAINS = ("interaction_forecasting", "motion_planning", "tracking_execution")
ACTION_BY_DOMAIN = {
    "interaction_forecasting": "I2_F_constant_velocity",
    "motion_planning": "I2_P_safety_envelope",
    "tracking_execution": "I2_C_bounded_brake",
}


def task_failure(metrics: dict[str, Any]) -> bool:
    """Draft A0 safety/task criterion, frozen only at D0-3."""
    ttc = metrics.get("minimum_positive_ttc_s")
    return bool(
        metrics.get("collision_count", 0) > 0
        or (ttc is not None and ttc < 2.5)
        or not metrics.get("route", {}).get("success", False)
        or not metrics.get("criteria", {}).get("motion", False)
    )


def mechanism_signal(
    mechanism: FaultMechanism, capture: dict[str, Any], stats: dict[str, Any]
) -> float:
    if mechanism in {FaultMechanism.FORECAST_STALE, FaultMechanism.FORECAST_HEADING_BIAS}:
        values = [row["horizon_end_displacement_m"] for row in capture["forecast_samples"]]
        return statistics.fmean(values) if values else 0.0
    if mechanism in {
        FaultMechanism.PLAN_CONSTRAINT_OMITTED,
        FaultMechanism.PLAN_UNSAFE_SPEED_BIAS,
    }:
        values = [row["max_speed_mps"] for row in capture["plan_samples"]]
        return statistics.fmean(values) if values else 0.0
    if mechanism == FaultMechanism.CONTROL_TRANSPORT_DELAY:
        return float(stats.get("delayed_releases", 0))
    values = [row["throttle_pct"] for row in capture["control_samples"]]
    return statistics.fmean(values) if values else 0.0


def mechanism_confirmed(
    mechanism: FaultMechanism,
    nominal_capture: dict[str, Any],
    nominal_stats: dict[str, Any],
    fault_capture: dict[str, Any],
    fault_stats: dict[str, Any],
) -> tuple[bool, float]:
    nominal = mechanism_signal(mechanism, nominal_capture, nominal_stats)
    fault = mechanism_signal(mechanism, fault_capture, fault_stats)
    delta = fault - nominal
    threshold = {
        FaultMechanism.FORECAST_STALE: 1.0,
        FaultMechanism.FORECAST_HEADING_BIAS: 1.0,
        FaultMechanism.PLAN_CONSTRAINT_OMITTED: 2.0,
        FaultMechanism.PLAN_UNSAFE_SPEED_BIAS: 1.0,
        FaultMechanism.CONTROL_TRANSPORT_DELAY: 10.0,
        FaultMechanism.CONTROL_GAIN_BIAS: 5.0,
    }[mechanism]
    return delta >= threshold, delta


def visible_run_summary(
    metrics: dict[str, Any], capture: dict[str, Any], stats: dict[str, Any]
) -> dict[str, Any]:
    """Return only diagnosis-safe semantic fields; never copy arbitrary input."""
    return {
        "safety_event": {
            "collision_count": int(metrics.get("collision_count", 0)),
            "minimum_ttc_s": metrics.get("minimum_positive_ttc_s"),
            "minimum_separation_m": metrics.get("minimum_separation_m"),
            "forward_progress_m": metrics.get("forward_progress_m"),
            "maximum_ego_speed_mps": metrics.get("maximum_ego_speed_mps"),
            "task_failure": task_failure(metrics),
        },
        "semantic_counts": {
            "forecast": len(capture.get("forecast_samples", [])),
            "motion_plan": len(capture.get("plan_samples", [])),
            "control_target": len(capture.get("control_samples", [])),
            "prediction_messages": int(stats.get("prediction_out", 0)),
            "planning_messages": int(stats.get("planning_out", 0)),
            "control_messages": int(stats.get("control_out", 0)),
        },
        "runtime": {
            "wall_seconds": metrics.get("wall_seconds"),
            "simulation_seconds": metrics.get("simulation_seconds"),
            "non_unit_frame_gaps": int(metrics.get("non_unit_frame_gaps", 0)),
        },
    }


def evidence_payloads(
    fault_runs: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    probes: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    metrics, capture, stats = fault_runs[0]
    summaries = [visible_run_summary(*run) for run in fault_runs]
    replay_digest = hashlib.sha256(
        json.dumps(summaries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payloads = {
        "O0_failure_summary": {"schema_version": 1, **summaries[0]["safety_event"]},
        "O1_forecast_window": {
            "schema_version": 1,
            "slot": "predicted_actor_trajectories",
            "samples": capture.get("forecast_samples", []),
        },
        "O1_motion_plan_window": {
            "schema_version": 1,
            "slot": "motion_plan",
            "samples": capture.get("plan_samples", []),
        },
        "O1_tracking_window": {
            "schema_version": 1,
            "slot": "control_target",
            "samples": capture.get("control_samples", []),
        },
        "O2_timing_metadata": {"schema_version": 1, **summaries[0]["runtime"]},
        "O3_semantic_replay": {
            "schema_version": 1,
            "repeat_count": len(summaries),
            "semantic_replay_digest": replay_digest,
            "failure_votes": sum(row["safety_event"]["task_failure"] for row in summaries),
        },
    }
    for domain, run in probes.items():
        payloads[ACTION_BY_DOMAIN[domain]] = {
            "schema_version": 1,
            "probe_domain": domain,
            "effect": visible_run_summary(*run),
            "input_source": "bounded_semantic_history",
            "oracle_replacement": False,
        }
    return payloads


def forbidden_visible_tokens(oracle: dict[str, Any]) -> set[str]:
    tokens = {
        str(oracle["fault_mechanism"]),
        str(oracle["scenario_kind"]),
    }
    tokens.update(str(value) for value in oracle["runs"].values())
    return {token for token in tokens if token}
