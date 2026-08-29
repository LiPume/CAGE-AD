"""Visible gray-box adapter for Apollo Prediction observations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


FORBIDDEN_VISIBLE_TERMS = (
    "fault_label",
    "root_module",
    "injector",
    "fix_commit",
    "ground_truth_answer",
)


def prediction_message_to_slot(message: Any, *, target_obstacle_id: int) -> dict[str, Any]:
    """Convert one native PredictionObstacles message to a bounded semantic slot."""

    actors: list[dict[str, Any]] = []
    for predicted in message.prediction_obstacle:
        obstacle_id = int(predicted.perception_obstacle.id)
        trajectories = []
        for trajectory in predicted.trajectory:
            points = [
                {
                    "relative_time": float(point.relative_time),
                    "x": float(point.path_point.x),
                    "y": float(point.path_point.y),
                    "theta": float(point.path_point.theta),
                    "v": float(point.v),
                    "a": float(point.a),
                }
                for point in trajectory.trajectory_point
            ]
            trajectories.append(
                {"probability": float(trajectory.probability), "points": points}
            )
        actors.append(
            {
                "obstacle_id": obstacle_id,
                "is_target": obstacle_id == target_obstacle_id,
                "is_static": bool(predicted.is_static),
                "source_timestamp_sec": float(predicted.timestamp),
                "trajectories": trajectories,
            }
        )
    return {
        "schema_version": 1,
        "semantic_slot": "predicted_actor_motion",
        "native_channel": "/apollo/prediction",
        "native_type": "apollo.prediction.PredictionObstacles",
        "timestamp_sec": float(message.header.timestamp_sec),
        "actors": actors,
    }


def contains_forbidden_visible_term(value: Any) -> bool:
    """Return True when a visible artifact contains an answer-bearing key or string."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(term in lowered for term in FORBIDDEN_VISIBLE_TERMS):
                return True
            if contains_forbidden_visible_term(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(contains_forbidden_visible_term(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(term in lowered for term in FORBIDDEN_VISIBLE_TERMS)
    return False


def evaluate_prediction_smoke(
    *,
    input_count: int,
    output_count: int,
    target_output_count: int,
    target_trajectory_count: int,
    target_frames_with_trajectory: int,
    timestamps_monotonic: bool,
    source_timestamps_monotonic: bool,
    source_timestamps_match_input: bool,
    probabilities_in_range: bool,
    observed_ids: list[int],
    critical_input_error_count: int = 0,
) -> dict[str, Any]:
    """Apply the frozen P1 stock-Prediction smoke checks."""

    checks = {
        "input_messages_at_least_100": input_count >= 100,
        "prediction_messages_nonzero": output_count > 0,
        "target_obstacle_observed": target_output_count > 0,
        "target_trajectory_nonzero": target_trajectory_count > 0,
        "output_coverage_at_least_0_80": output_count >= 0.8 * input_count,
        "target_trajectory_frame_coverage_at_least_0_80": (
            target_output_count > 0
            and target_frames_with_trajectory >= 0.8 * target_output_count
        ),
        "timestamps_monotonic": timestamps_monotonic,
        "source_timestamps_monotonic": source_timestamps_monotonic,
        "source_timestamps_match_input": source_timestamps_match_input,
        "probabilities_in_range": probabilities_in_range,
        "only_expected_obstacle_id": sorted(set(observed_ids)) in ([], [1001]),
        "critical_input_errors_zero": critical_input_error_count == 0,
    }
    return {"checks": checks, "passed": all(checks.values())}
