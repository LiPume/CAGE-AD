from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts/d0/hint_gold/build_candidate_evidence.py"
SPEC = importlib.util.spec_from_file_location("hint_gold_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_semantic_time_compression_activation_is_confirmed():
    activation, detail = MODULE._semantic_mechanism_activation(
        {
            "injector_exception": None,
            "fault_applications": 11,
            "activation_observations": [
                {
                    "simulator_time_s": 2.1,
                    "metric_value": 0.6000000001,
                    "transform_residual": 0.0,
                }
            ],
        }
    )
    assert activation == 2.1
    assert detail["observed_time_scale"] == 0.6000000001


def test_semantic_activation_fails_closed_on_injector_exception():
    activation, detail = MODULE._semantic_mechanism_activation(
        {
            "injector_exception": "bad transform",
            "fault_applications": 11,
            "activation_observations": [
                {"simulator_time_s": 2.1, "metric_value": 0.6, "transform_residual": 0.0}
            ],
        }
    )
    assert activation is None
    assert detail is None
