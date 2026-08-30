from __future__ import annotations

from dataclasses import asdict
import math
from pathlib import Path

import pytest

from cage_ad.protocol_v1.loader import ProtocolValidationError, load_protocol
from cage_ad.protocol_v1.scenario import scenario_candidate
from cage_ad.protocol_v1.transformers import (
    ActuatorCommand,
    AtomicDelayQueue,
    TrajectoryPoint,
    attenuate_braking_suffix,
    attenuate_lateral_maneuver,
    compress_trajectory_time,
    kinematic_residuals,
    scale_actuator_effectiveness,
    window_active,
)


@pytest.fixture(scope="module")
def protocol():
    return load_protocol(Path(__file__).resolve().parents[2])


def _straight_braking_path() -> list[TrajectoryPoint]:
    return [
        TrajectoryPoint(0.0, 0.0, 0.0, 0.0, 0.0, 10.0, -2.0, 0.0),
        TrajectoryPoint(1.0, 9.0, 0.0, 9.0, 0.0, 8.0, -2.0, 0.0),
        TrajectoryPoint(2.0, 16.0, 0.0, 16.0, 0.0, 6.0, -2.0, 0.0),
    ]


def test_all_declared_scenario_candidates_are_loaded_without_hidden_defaults(protocol):
    expected_ids = {
        "lead_brake_close": ["LBC0", "LBC1", "LBC2"],
        "lead_brake_moderate": ["LBM0", "LBM1", "LBM2"],
        "cut_in_early": ["CIE0", "CIE1", "CIE2"],
        "cut_in_late": ["CIL0", "CIL1", "CIL2"],
    }
    for scenario_id, candidate_ids in expected_ids.items():
        actual = [scenario_candidate(protocol, scenario_id, index) for index in range(3)]
        assert [candidate.candidate_id for candidate in actual] == candidate_ids
        declared = protocol.scenarios["scenarios"][scenario_id]["candidate_order"]
        assert [dict(candidate.values) for candidate in actual] == [
            {key: value for key, value in item.items() if key != "candidate_id"} for item in declared
        ]


def test_lead_brake_velocity_and_window_boundaries(protocol):
    candidate = scenario_candidate(protocol, "lead_brake_close", 0)
    assert candidate.conflict_onset_s == 6.0
    assert candidate.trigger_window == (5.0, 9.0)
    assert candidate.spawn_offsets_m == (30.0, 0.0)
    assert candidate.velocity(5.999) == (5.0, 0.0)
    assert candidate.velocity(6.0) == (5.0, 0.0)
    assert candidate.velocity(7.0) == (2.0, 0.0)
    assert candidate.velocity(8.0) == (0.0, 0.0)
    assert candidate.displacement(5.0, 3.0) == pytest.approx((5.0 + 25.0 / 6.0, 0.0))


def test_cut_in_velocity_and_window_boundaries(protocol):
    candidate = scenario_candidate(protocol, "cut_in_early", 0)
    assert candidate.conflict_onset_s == 3.0
    assert candidate.trigger_window == (2.0, 6.0)
    assert candidate.spawn_offsets_m == (25.0, -3.5)
    assert candidate.velocity(2.999) == (3.0, 0.0)
    assert candidate.velocity(3.0) == (3.0, 0.0)
    assert candidate.velocity(4.0) == pytest.approx((3.0, 0.6))
    assert candidate.velocity(10.0) == (3.0, 1.5)
    assert candidate.displacement(2.0, 4.0) == pytest.approx((12.0, 2.625))
    with pytest.raises(ProtocolValidationError, match="nonnegative"):
        candidate.displacement(-1.0, 1.0)


def test_scenario_lookup_fails_closed(protocol):
    with pytest.raises(ProtocolValidationError, match="unknown scenario"):
        scenario_candidate(protocol, "not-declared", 0)
    with pytest.raises(ProtocolValidationError, match="out of range"):
        scenario_candidate(protocol, "lead_brake_close", 3)


def test_fault_window_is_inclusive_and_rejects_reversal():
    assert not window_active(4.999, 5.0, 9.0)
    assert window_active(5.0, 5.0, 9.0)
    assert window_active(9.0, 5.0, 9.0)
    assert not window_active(9.001, 5.0, 9.0)
    with pytest.raises(ProtocolValidationError, match="end precedes start"):
        window_active(1.0, 2.0, 1.0)


def test_forecast_maneuver_attenuation_preserves_t0_and_non_target_state():
    points = [
        TrajectoryPoint(0.0, 10.0, 20.0, 0.0, 0.0, 5.0, 0.0, 0.01),
        TrajectoryPoint(1.0, 15.0, 21.0, 5.1, 0.2, 5.0, 0.0, 0.01),
        TrajectoryPoint(2.0, 20.0, 24.0, 10.8, 0.4, 5.0, 0.0, 0.01),
    ]
    result = attenuate_lateral_maneuver(points, 0.5)
    assert (result[0].x, result[0].y) == (10.0, 20.0)
    assert [point.y for point in result] == pytest.approx([20.0, 20.5, 22.0])
    for before, after in zip(points, result):
        assert (after.relative_time, after.s, after.v, after.a, after.curvature) == (
            before.relative_time,
            before.s,
            before.v,
            before.a,
            before.curvature,
        )
    assert result[0].heading == pytest.approx(math.atan2(0.5, 5.0))
    assert result[1].heading == pytest.approx(math.atan2(1.5, 5.0))


def test_forecast_maneuver_full_attenuation_removes_lateral_future():
    points = [
        TrajectoryPoint(0.0, 0.0, 0.0, 0.0, math.pi / 2, 2.0, 0.0),
        TrajectoryPoint(1.0, -1.0, 2.0, 2.2, 2.0, 2.0, 0.0),
    ]
    result = attenuate_lateral_maneuver(points, 1.0)
    assert result[1].x == pytest.approx(0.0, abs=1e-12)
    assert result[1].y == pytest.approx(2.0)
    assert result[0].heading == pytest.approx(math.pi / 2)


def test_atomic_delay_queue_preserves_whole_content_and_stable_order():
    first = {"header": {"timestamp": 1.0}, "objects": [1]}
    second = {"header": {"timestamp": 1.0}, "objects": [2]}
    queue: AtomicDelayQueue[dict] = AtomicDelayQueue(maximum_delay_s=2.0)
    queue.buffer(1.0, first)
    queue.buffer(1.0, second)
    first["objects"].append(99)
    assert queue.select_content(1.4, 0.5) is None
    selected = queue.select_content(1.5, 0.5)
    assert selected == second
    selected["objects"].append(100)
    assert queue.select_content(1.5, 0.5) == second
    assert queue.release_due(1.49, 0.5) == []
    assert queue.release_due(1.5, 0.5) == [
        {"header": {"timestamp": 1.0}, "objects": [1]},
        second,
    ]
    assert len(queue) == 0


def test_atomic_delay_queue_rejects_invalid_time_and_clears_at_window_end():
    queue: AtomicDelayQueue[int] = AtomicDelayQueue(maximum_delay_s=0.8)
    queue.buffer(2.0, 1)
    with pytest.raises(ProtocolValidationError, match="moved backwards"):
        queue.buffer(1.9, 2)
    with pytest.raises(ProtocolValidationError, match="outside"):
        queue.select_content(2.0, 0.0)
    queue.clear()
    assert len(queue) == 0


def test_planning_braking_attenuation_reintegrates_all_coupled_fields():
    points = _straight_braking_path()
    result = attenuate_braking_suffix(points, 0.5)
    assert (
        result[0].relative_time,
        result[0].x,
        result[0].y,
        result[0].s,
        result[0].heading,
        result[0].v,
        result[0].curvature,
    ) == (
        points[0].relative_time,
        points[0].x,
        points[0].y,
        points[0].s,
        points[0].heading,
        points[0].v,
        points[0].curvature,
    )
    assert [(point.relative_time, point.v, point.a, point.s, point.x, point.y) for point in result] == pytest.approx(
        [
            (0.0, 10.0, -1.0, 0.0, 0.0, 0.0),
            (1.0, 9.0, -1.0, 9.5, 9.5, 0.0),
            (2.0, 8.0, -1.0, 18.0, 18.0, 0.0),
        ]
    )
    position_residual, speed_residual = kinematic_residuals(result)
    assert position_residual == pytest.approx(0.0)
    assert speed_residual == pytest.approx(0.0)


def test_planning_time_compression_changes_only_declared_fields():
    points = _straight_braking_path()
    result = compress_trajectory_time(points, 0.8)
    assert [point.relative_time for point in result] == pytest.approx([0.0, 0.8, 1.6])
    assert [point.v for point in result] == pytest.approx([12.5, 10.0, 7.5])
    assert [point.a for point in result] == pytest.approx([-3.125, -3.125, -3.125])
    for before, after in zip(points, result):
        assert (after.x, after.y, after.s, after.heading, after.curvature) == (
            before.x,
            before.y,
            before.s,
            before.heading,
            before.curvature,
        )


def test_control_effectiveness_has_no_bias_or_brake_clear_side_effect():
    command = ActuatorCommand(timestamp=12.5, throttle=0.0, brake=0.7, steering_target=-0.4, gear=3)
    result = scale_actuator_effectiveness(command, 0.6)
    assert asdict(result) == pytest.approx(
        {"timestamp": 12.5, "throttle": 0.0, "brake": 0.42, "steering_target": -0.24, "gear": 3}
    )


@pytest.mark.parametrize("transform,args", [
    (attenuate_lateral_maneuver, (-0.1,)),
    (attenuate_braking_suffix, (1.1,)),
    (compress_trajectory_time, (0.0,)),
])
def test_trajectory_transformers_reject_out_of_contract_doses(transform, args):
    with pytest.raises(ProtocolValidationError):
        transform(_straight_braking_path(), *args)
