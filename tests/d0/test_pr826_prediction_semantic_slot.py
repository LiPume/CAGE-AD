from __future__ import annotations

from types import SimpleNamespace

from cage_ad.adapters.apollo_d0.prediction_semantic_slot import (
    contains_forbidden_visible_term,
    evaluate_prediction_smoke,
    prediction_message_to_slot,
)


def test_prediction_message_maps_to_bounded_slot() -> None:
    point = SimpleNamespace(
        relative_time=1.0,
        path_point=SimpleNamespace(x=1.0, y=2.0, theta=0.1),
        v=3.0,
        a=0.0,
    )
    trajectory = SimpleNamespace(probability=0.8, trajectory_point=[point])
    predicted = SimpleNamespace(
        perception_obstacle=SimpleNamespace(id=1001),
        is_static=False,
        timestamp=10.0,
        trajectory=[trajectory],
    )
    message = SimpleNamespace(
        header=SimpleNamespace(timestamp_sec=10.1), prediction_obstacle=[predicted]
    )
    slot = prediction_message_to_slot(message, target_obstacle_id=1001)
    assert slot["semantic_slot"] == "predicted_actor_motion"
    assert slot["actors"][0]["is_target"] is True
    assert slot["actors"][0]["trajectories"][0]["points"][0]["v"] == 3.0


def test_smoke_gate_requires_real_target_trajectory() -> None:
    passed = evaluate_prediction_smoke(
        input_count=160,
        output_count=160,
        target_output_count=160,
        target_trajectory_count=160,
        target_frames_with_trajectory=160,
        timestamps_monotonic=True,
        source_timestamps_monotonic=True,
        source_timestamps_match_input=True,
        probabilities_in_range=True,
        observed_ids=[1001],
        critical_input_error_count=0,
    )
    assert passed["passed"] is True
    missing = evaluate_prediction_smoke(
        input_count=160,
        output_count=80,
        target_output_count=80,
        target_trajectory_count=0,
        target_frames_with_trajectory=0,
        timestamps_monotonic=True,
        source_timestamps_monotonic=True,
        source_timestamps_match_input=True,
        probabilities_in_range=True,
        observed_ids=[1001],
        critical_input_error_count=0,
    )
    assert missing["passed"] is False

    degraded = evaluate_prediction_smoke(
        input_count=160,
        output_count=160,
        target_output_count=160,
        target_trajectory_count=160,
        target_frames_with_trajectory=160,
        timestamps_monotonic=True,
        source_timestamps_monotonic=True,
        source_timestamps_match_input=True,
        probabilities_in_range=True,
        observed_ids=[1001],
        critical_input_error_count=1,
    )
    assert degraded["passed"] is False

    sparse = evaluate_prediction_smoke(
        input_count=160,
        output_count=160,
        target_output_count=160,
        target_trajectory_count=64,
        target_frames_with_trajectory=64,
        timestamps_monotonic=True,
        source_timestamps_monotonic=True,
        source_timestamps_match_input=True,
        probabilities_in_range=True,
        observed_ids=[1001],
        critical_input_error_count=0,
    )
    assert sparse["passed"] is False


def test_visible_leakage_scan_rejects_answer_bearing_terms() -> None:
    assert contains_forbidden_visible_term({"semantic_slot": "predicted_actor_motion"}) is False
    assert contains_forbidden_visible_term({"root_module": "prediction"}) is True
    assert contains_forbidden_visible_term({"note": "contains fix_commit metadata"}) is True
