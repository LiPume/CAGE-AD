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
        },
        "HGV1-P02-CIE0",
    )
    assert activation == 2.1
    assert detail["activation_metric_value"] == 0.6000000001


def test_semantic_activation_fails_closed_on_injector_exception():
    activation, detail = MODULE._semantic_mechanism_activation(
        {
            "injector_exception": "bad transform",
            "fault_applications": 11,
            "activation_observations": [
                {"simulator_time_s": 2.1, "metric_value": 0.6, "transform_residual": 0.0}
            ],
        },
        "HGV1-P02-CIE0",
    )
    assert activation is None
    assert detail is None


def test_braking_omission_activation_requires_valid_reintegration():
    activation, detail = MODULE._semantic_mechanism_activation(
        {
            "injector_exception": None,
            "fault_applications": 9,
            "activation_observations": [
                {
                    "simulator_time_s": 5.2,
                    "metric_value": 0.8,
                    "transform_residual": 0.05,
                    "position_residual_m": 0.12,
                }
            ],
        },
        "HGV1-P03-LBC1",
    )
    assert activation == 5.2
    assert detail["activation_metric_value"] == 0.8
