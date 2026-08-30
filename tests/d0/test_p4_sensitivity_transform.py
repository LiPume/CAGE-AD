#!/usr/bin/env python3
"""Pure protobuf controls for the private P4-SENS boundary transform."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import unittest

from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/d0/pr826/p4_sensitivity_interposer.py"
SPEC = importlib.util.spec_from_file_location("p4_sensitivity_interposer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def example_message() -> PredictionObstacles:
    message = PredictionObstacles()
    message.header.module_name = "prediction"
    message.header.sequence_num = 17
    message.header.timestamp_sec = 1234.5
    other = message.prediction_obstacle.add()
    other.perception_obstacle.id = 7
    other.perception_obstacle.position.x = 99.0
    target = message.prediction_obstacle.add()
    target.perception_obstacle.id = 1001
    target.perception_obstacle.position.x = 9.0
    target.perception_obstacle.position.y = -100.0
    target.timestamp = 42.0
    target.predicted_period = 6.0
    target.is_static = False
    trajectory = target.trajectory.add()
    trajectory.probability = 0.72
    for index in range(60):
        point = trajectory.trajectory_point.add()
        point.relative_time = index / 10.0
        point.path_point.x = 9.0
        point.path_point.y = -100.0 + index / 10.0
        point.path_point.theta = math.pi / 2.0
        point.path_point.s = index / 10.0
        point.path_point.kappa = 0.0
        point.v = 1.1
        point.a = 0.0
    return message


class P4SensitivityTransformTest(unittest.TestCase):
    def test_identity_is_byte_exact(self) -> None:
        message = example_message()
        self.assertEqual(MODULE.sha256_message(message), MODULE.sha256_message(message))

    def test_left_merge_changes_only_declared_path_semantics(self) -> None:
        source = example_message()
        output = PredictionObstacles()
        output.CopyFrom(source)
        before = MODULE.preservation_snapshot(source, 1001)
        result = MODULE.transform_left_merge(output, 1001, 3.5, 2.0, 4.0)
        after = MODULE.preservation_snapshot(output, 1001)
        self.assertEqual(before, after)
        self.assertEqual(result["trajectory_count"], 1)
        self.assertAlmostEqual(result["endpoint_delta_m_min"], 3.5, places=9)
        target = MODULE.target_obstacles(output, 1001)[0]
        self.assertAlmostEqual(target.trajectory[0].trajectory_point[0].path_point.x, 9.0)
        self.assertAlmostEqual(target.trajectory[0].trajectory_point[-1].path_point.x, 5.5)
        self.assertEqual(
            MODULE.sha256_message(source.prediction_obstacle[0]),
            MODULE.sha256_message(output.prediction_obstacle[0]),
        )

    def test_no_trajectory_clears_only_declared_repeated_field(self) -> None:
        source = example_message()
        output = PredictionObstacles()
        output.CopyFrom(source)
        expected = MODULE.preservation_snapshot(source, 1001)
        result = MODULE.clear_target_trajectories(output, 1001)
        expected["targets"][0]["trajectory_count"] = 0
        expected["targets"][0]["probabilities"] = []
        expected["targets"][0]["points"] = []
        self.assertEqual(result["removed_trajectories"], 1)
        self.assertEqual(expected, MODULE.preservation_snapshot(output, 1001))
        self.assertEqual(
            MODULE.sha256_message(source.prediction_obstacle[0]),
            MODULE.sha256_message(output.prediction_obstacle[0]),
        )


if __name__ == "__main__":
    unittest.main()
