import json
import math

import pytest

from cage_ad.diagnostics.ttc_null import (
    DiagnosticOBB,
    DiagnosticTraceRow,
    DiagnosticValidationError,
    RootCause,
    classify_root_cause,
    classify_tick_disagreement,
    closest_approach,
    fine_step_ttc,
    has_stable_true,
    relative_state_in_ego_frame,
    sampled_prediction_geometry,
    sat_separation_m,
    summarize_trace,
    world_obb_from_carla_state,
)
from cage_ad.protocol_v1.evaluator import OrientedBox, minimum_run_ttc, oriented_box_ttc


def _production(box: DiagnosticOBB) -> OrientedBox:
    return OrientedBox(
        box.x,
        box.y,
        box.heading_rad,
        box.length_m,
        box.width_m,
        box.velocity_x_mps,
        box.velocity_y_mps,
        box.object_id,
    )


def test_same_lane_known_closing_ttc() -> None:
    ego = DiagnosticOBB(0, 0, 0, 4, 2, 10, 0)
    actor = DiagnosticOBB(14, 0, 0, 4, 2, 5, 0)
    # 边界初始相距 10 m，相对速度 5 m/s。
    assert fine_step_ttc(ego, actor) == pytest.approx(2.0)
    assert oriented_box_ttc(_production(ego), _production(actor)) == pytest.approx(2.0)


def test_same_direction_same_speed_has_no_ttc() -> None:
    ego = DiagnosticOBB(0, 0, 0, 4, 2, 5, 0)
    actor = DiagnosticOBB(14, 0, 0, 4, 2, 5, 0)
    assert fine_step_ttc(ego, actor) is None
    assert oriented_box_ttc(_production(ego), _production(actor)) is None


def test_perpendicular_equal_arrival_has_finite_ttc() -> None:
    horizontal = DiagnosticOBB(-10, 0, 0, 4, 2, 5, 0)
    vertical = DiagnosticOBB(0, -10, math.pi / 2, 4, 2, 0, 5)
    assert fine_step_ttc(horizontal, vertical) is not None
    assert oriented_box_ttc(_production(horizontal), _production(vertical)) is not None


def test_crossing_at_different_times_has_no_ttc() -> None:
    horizontal = DiagnosticOBB(-10, 0, 0, 4, 2, 10, 0)
    vertical = DiagnosticOBB(0, -30, math.pi / 2, 4, 2, 0, 5)
    assert fine_step_ttc(horizontal, vertical) is None
    assert oriented_box_ttc(_production(horizontal), _production(vertical)) is None


def test_overlap_is_zero_but_run_minimum_ignores_zero() -> None:
    overlap = DiagnosticOBB(0, 0, 0, 4, 2, 0, 0)
    assert fine_step_ttc(overlap, overlap) == 0.0
    assert oriented_box_ttc(_production(overlap), _production(overlap)) == 0.0
    assert minimum_run_ttc([(_production(overlap), _production(overlap))]) is None


def test_carla_local_box_offset_and_yaws_are_composed() -> None:
    state = {
        "actor_id": 17,
        "location": {"x": 10.0, "y": 20.0, "z": 0.0},
        "yaw_deg": 90.0,
        "velocity": {"x": 1.0, "y": 2.0, "z": 0.0},
        "bounding_box": {
            "location": {"x": 2.0, "y": 1.0, "z": 0.0},
            "yaw_deg": 15.0,
            "extent": {"x": 2.0, "y": 1.0, "z": 0.5},
        },
    }
    box = world_obb_from_carla_state(state)
    assert box.x == pytest.approx(9.0)
    assert box.y == pytest.approx(22.0)
    assert box.heading_rad == pytest.approx(math.radians(105.0))
    assert (box.length_m, box.width_m) == (4.0, 2.0)


def test_independent_separation_and_closest_approach() -> None:
    left = DiagnosticOBB(0, 0, 0, 4, 2, 1, 0)
    right = DiagnosticOBB(14, 0, 0, 4, 2, 0, 0)
    assert sat_separation_m(left, right) == pytest.approx(10.0)
    approach = closest_approach(left, right, horizon_s=5.0)
    assert approach.time_s == pytest.approx(5.0)
    assert approach.separation_m == pytest.approx(5.0)
    sampled_ttc, sampled_approach = sampled_prediction_geometry(left, right, horizon_s=5.0)
    assert sampled_ttc is None
    assert sampled_approach.time_s == pytest.approx(5.0)
    assert sampled_approach.separation_m == pytest.approx(5.0)


def test_optimized_geometry_matches_golden_ttc() -> None:
    ego = DiagnosticOBB(0, 0, 0, 4, 2, 10, 0)
    actor = DiagnosticOBB(14, 0, 0, 4, 2, 5, 0)
    sampled_ttc, approach = sampled_prediction_geometry(ego, actor)
    assert sampled_ttc == fine_step_ttc(ego, actor) == pytest.approx(2.0)
    assert approach.separation_m == 0.0


@pytest.mark.parametrize(
    ("ego", "actor"),
    [
        (DiagnosticOBB(0, 0, 0.1, 4.8, 2.1, 0.5, 0.1), DiagnosticOBB(8, 4, -0.2, 4.2, 2, -0.2, -0.3)),
        (DiagnosticOBB(-2, 3, -0.7, 4, 1.8, 2, 1), DiagnosticOBB(12, -1, 1.2, 5, 2.2, -1, 0.2)),
        (DiagnosticOBB(1, -4, 2.4, 4.5, 2, -0.5, 1.5), DiagnosticOBB(-8, 7, -1.1, 4, 2, 0.8, -1.2)),
    ],
)
def test_optimized_closest_approach_matches_exhaustive_scan(
    ego: DiagnosticOBB, actor: DiagnosticOBB
) -> None:
    expected_ttc = fine_step_ttc(ego, actor, horizon_s=2.0)
    expected_approach = closest_approach(ego, actor, horizon_s=2.0)
    actual_ttc, actual_approach = sampled_prediction_geometry(ego, actor, horizon_s=2.0)
    assert actual_ttc == expected_ttc
    assert actual_approach.time_s == pytest.approx(expected_approach.time_s)
    assert actual_approach.separation_m == pytest.approx(expected_approach.separation_m)


def test_relative_state_uses_ego_frame() -> None:
    ego = DiagnosticOBB(1, 2, math.pi / 2, 4, 2, 0, 3)
    actor = DiagnosticOBB(3, 7, 0, 4, 2, 0, 1)
    relative = relative_state_in_ego_frame(ego, actor)
    assert relative["forward_m"] == pytest.approx(5.0)
    assert relative["right_m"] == pytest.approx(2.0)
    assert relative["closing_mps"] == pytest.approx(2.0)


def test_disagreement_classes() -> None:
    assert classify_tick_disagreement(None, None) == "both_null"
    assert classify_tick_disagreement(None, 1.0) == "production_null_independent_finite"
    assert classify_tick_disagreement(1.0, None) == "production_finite_independent_null"
    assert classify_tick_disagreement(1.0, 1.05) == "agree"
    assert classify_tick_disagreement(1.0, 1.2) == "finite_value_mismatch"
    assert has_stable_true([False, True, True, True])
    assert not has_stable_true([True, True, False, True])
    with pytest.raises(DiagnosticValidationError, match="positive"):
        has_stable_true([True], consecutive=0)


def _trace_row(frame: int, sim: float) -> dict:
    state = {
        "actor_id": 1,
        "role_name": "ego_vehicle",
        "type_id": "vehicle.test",
        "location": {"x": sim, "y": 0.0, "z": 0.0},
        "yaw_deg": 0.0,
        "velocity": {"x": 1.0, "y": 0.0, "z": 0.0},
        "acceleration": {"x": 0.0, "y": 0.0, "z": 0.0},
        "bounding_box": {
            "location": {"x": 0.0, "y": 0.0, "z": 0.0},
            "yaw_deg": 0.0,
            "extent": {"x": 2.0, "y": 1.0, "z": 1.0},
        },
    }
    actor = json.loads(json.dumps(state))
    actor.update(actor_id=2, role_name="cage_interaction_actor")
    actor["location"]["x"] += 10.0
    return {
        "frame": frame,
        "sim_time_s": sim,
        "wall_time_s": sim,
        "route_epoch_elapsed_s": sim,
        "ego": state,
        "interaction_actor": actor,
        "actor_program": {},
        "relative": {"center_distance_m": 10.0, "closing_mps": 0.0},
        "geometry": {
            "production_ttc_s": None,
            "production_ttc_s_missing_reason": "no predicted overlap in horizon",
            "independent_ttc_s": None,
            "independent_ttc_s_missing_reason": "no predicted overlap in horizon",
            "predicted_min_obb_separation_m": 6.0,
            "closest_approach_time_s": 0.0,
            "current_obb_separation_m": 6.0,
        },
        "apollo": {},
        "road": {},
    }


def test_trace_schema_rejects_null_without_reason() -> None:
    row = _trace_row(1, 0.0)
    del row["geometry"]["independent_ttc_s_missing_reason"]
    with pytest.raises(DiagnosticValidationError, match="lacks missing reason"):
        DiagnosticTraceRow.from_dict(row)


def test_trace_summary_and_root_cause(tmp_path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text("\n".join(json.dumps(_trace_row(index, index * 0.05)) for index in range(1, 4)) + "\n")
    summary = summarize_trace(trace)
    assert summary["trace_frames"] == 3
    assert summary["unique_ego_actor_ids"] == ["1"]
    assert classify_root_cause({**summary, "trigger_too_early": True}) is RootCause.PROTOCOL_SCENARIO_OR_ADMISSION_DESIGN_FAILURE
