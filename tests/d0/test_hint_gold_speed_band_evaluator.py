from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[2]
    / "scripts/d0/hint_gold/evaluate_speed_band_smoke.py"
)
SPEC = importlib.util.spec_from_file_location("hint_gold_speed_band_evaluator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_detects_actual_apollo_piecewise_jerk_failure_wording():
    assert MODULE.has_speed_optimizer_failure(
        "E0826 piecewise_jerk_speed_optimizer.cc:191] "
        "[planning]Piecewise jerk speed optimizer failed!.try to fallback."
    )


def test_detects_supported_failure_wording_case_insensitively():
    assert MODULE.has_speed_optimizer_failure("Speed optimization FAILED")
    assert MODULE.has_speed_optimizer_failure("failed to optimize speed")


def test_does_not_flag_success_log():
    assert not MODULE.has_speed_optimizer_failure(
        "Piecewise jerk speed optimizer completed successfully"
    )
