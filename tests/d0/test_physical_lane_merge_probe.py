import math
import sys
import types

# The pure helpers only need CARLA data containers; production imports the real module.
try:
    import carla  # noqa: F401
except ModuleNotFoundError:
    carla = types.SimpleNamespace(Transform=object, Location=object)
    sys.modules["carla"] = carla

from scripts.d0.pr826.probe_physical_lane_merge import smoothstep, wrap_radians


def test_smoothstep_is_bounded_and_has_expected_midpoint():
    assert smoothstep(-1.0) == 0.0
    assert smoothstep(0.0) == 0.0
    assert smoothstep(0.5) == 0.5
    assert smoothstep(1.0) == 1.0
    assert smoothstep(2.0) == 1.0


def test_wrap_radians_is_principal():
    assert math.isclose(wrap_radians(3.0 * math.pi), -math.pi)
    assert -math.pi <= wrap_radians(17.0) < math.pi
