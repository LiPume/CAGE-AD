from __future__ import annotations

import math
from pathlib import Path

import pytest

from cage_ad.protocol_v1.loader import ProtocolValidationError, load_protocol
from cage_ad.protocol_v1.probes import (
    ActorHistorySample,
    ControlProbe,
    probe_suite_config,
    run_forecasting_probe,
    run_planning_probe,
)
from cage_ad.protocol_v1.transformers import TrajectoryPoint, kinematic_residuals


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def config():
    return probe_suite_config(load_protocol(ROOT))


def _constant_acceleration_history() -> list[ActorHistorySample]:
    return [
        ActorHistorySample(
            timestamp=index * 0.2,
            x=3.0 * index * 0.2 + 0.5 * 2.0 * (index * 0.2) ** 2,
            y=0.0,
            speed=3.0 + 2.0 * index * 0.2,
            heading=0.0,
        )
        for index in range(6)
    ]


def test_probe_parameters_are_loaded_from_yaml_without_scene_tuning(config):
    assert config.forecasting.history_window_s == 1.0
    assert config.forecasting.minimum_history_samples == 5
    assert config.forecasting.horizon_s == 5.0
    assert config.forecasting.step_s == 0.2
    assert config.planning == pytest.approx(
        type(config.planning)(5.0, 0.1, 2.0, 4.0, 5.0, 0.0)
    )
    assert config.control.lookahead_floor_m == 3.0
    assert config.control.lookahead_speed_factor == 0.8
    assert config.control.maximum_steering_angle_deg == 70.0


def test_forecasting_probe_selects_constant_acceleration_and_starts_at_current_pose(config):
    history = _constant_acceleration_history()
    result = run_forecasting_probe(history, config.forecasting)
    assert result.selected_model == "constant_acceleration"
    assert result.rolling_ade["constant_acceleration"] < result.rolling_ade[
        "constant_turn_rate_and_velocity"
    ]
    assert len(result.trajectory) == 26
    assert result.trajectory[0].relative_time == 0.0
    assert (result.trajectory[0].x, result.trajectory[0].y) == (
        history[-1].x,
        history[-1].y,
    )
    assert result.trajectory[-1].relative_time == pytest.approx(5.0)
    assert all(
        right.relative_time > left.relative_time
        for left, right in zip(result.trajectory, result.trajectory[1:])
    )


def test_forecasting_probe_selects_ctrv_for_turning_history(config):
    yaw_rate = 0.4
    speed = 4.0
    radius = speed / yaw_rate
    history = []
    for index in range(6):
        timestamp = index * 0.2
        heading = yaw_rate * timestamp
        history.append(
            ActorHistorySample(
                timestamp,
                radius * math.sin(heading),
                radius * (1.0 - math.cos(heading)),
                speed,
                heading,
            )
        )
    result = run_forecasting_probe(history, config.forecasting)
    assert result.selected_model == "constant_turn_rate_and_velocity"
    assert result.rolling_ade[result.selected_model] == pytest.approx(0.0, abs=1e-10)
    assert result.trajectory[-1].heading > result.trajectory[0].heading


def test_forecasting_probe_tie_breaks_to_ca_and_rejects_future_or_bad_history(config):
    history = [
        ActorHistorySample(index * 0.2, index * 0.8, 0.0, 4.0, 0.0)
        for index in range(6)
    ]
    result = run_forecasting_probe(history, config.forecasting)
    assert result.selected_model == "constant_acceleration"
    with pytest.raises(ProtocolValidationError, match="insufficient"):
        run_forecasting_probe(history[:4], config.forecasting)
    malformed = history[:]
    malformed[-1] = ActorHistorySample(malformed[-2].timestamp, 9.0, 0.0, 4.0, 0.0)
    with pytest.raises(ProtocolValidationError, match="not strict"):
        run_forecasting_probe(malformed, config.forecasting)


def _straight_nominal_path() -> list[TrajectoryPoint]:
    return [
        TrajectoryPoint(index * 0.1, index * 0.5, 0.0, index * 0.5, 0.0, 5.0, 0.0)
        for index in range(61)
    ]


def test_planning_probe_generates_all_fields_with_jerk_and_kinematic_limits(config):
    path = _straight_nominal_path()
    obstacle = [
        TrajectoryPoint(index * 0.1, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        for index in range(51)
    ]
    result = run_planning_probe(path, obstacle, 5.0, 0.0, config.planning)
    assert len(result) == 51
    assert [point.relative_time for point in result] == pytest.approx(
        [index * 0.1 for index in range(51)]
    )
    assert all(right.s >= left.s for left, right in zip(result, result[1:]))
    assert all(point.v >= 0.0 for point in result)
    assert all(-4.0 <= point.a <= 0.0 for point in result)
    assert all(
        abs(right.a - left.a) <= 5.0 * 0.1 + 1e-12
        for left, right in zip(result, result[1:])
    )
    position_residual, speed_residual = kinematic_residuals(list(result))
    assert position_residual <= 0.25
    assert speed_residual <= 0.50
    assert result[-1].v == pytest.approx(0.0)


def test_planning_probe_without_conflict_preserves_speed_and_path(config):
    path = _straight_nominal_path()
    far_obstacle = [TrajectoryPoint(0.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0)]
    result = run_planning_probe(path, far_obstacle, 5.0, 0.0, config.planning)
    assert [point.v for point in result] == pytest.approx([5.0] * 51)
    assert result[-1].s == pytest.approx(25.0)
    assert result[-1].x == pytest.approx(25.0)


def test_control_probe_obeys_pure_pursuit_pid_bounds_and_mutual_exclusion(config):
    plan = _straight_nominal_path()
    controller = ControlProbe(config.control)
    accelerate = controller.command(
        timestamp=1.0,
        ego_x=0.0,
        ego_y=1.0,
        ego_heading=0.0,
        current_speed_mps=2.0,
        target_plan=plan,
        dt=0.05,
        gear=1,
    )
    assert accelerate.throttle > 0.0
    assert accelerate.brake == 0.0
    assert -70.0 <= accelerate.steering_target < 0.0
    assert accelerate.gear == 1
    brake = controller.command(
        timestamp=1.05,
        ego_x=0.0,
        ego_y=-1.0,
        ego_heading=0.0,
        current_speed_mps=9.0,
        target_plan=plan,
        dt=0.05,
        gear=1,
    )
    assert brake.throttle == 0.0
    assert brake.brake > 0.0
    assert brake.steering_target > 0.0
    assert brake.timestamp == 1.05
    controller.reset()
    assert controller.integral_error == 0.0 and controller.previous_error is None


def test_control_probe_fails_closed_on_invalid_input(config):
    controller = ControlProbe(config.control)
    with pytest.raises(ProtocolValidationError, match="invalid"):
        controller.command(
            timestamp=0.0,
            ego_x=0.0,
            ego_y=0.0,
            ego_heading=0.0,
            current_speed_mps=0.0,
            target_plan=[],
            dt=0.0,
            gear=0,
        )
