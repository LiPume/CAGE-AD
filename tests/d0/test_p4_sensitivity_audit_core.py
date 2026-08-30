#!/usr/bin/env python3
"""Regression tests for the common persistent-sensitivity audit core."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = ROOT / "scripts/d0/pr826/p4_sensitivity_audit_core.py"
SPEC = importlib.util.spec_from_file_location("p4_sensitivity_audit_core", CORE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
BUNDLE = Path("/root/autodl_apollo10_g0_bundle")
BENCH = ROOT / "benchmarks/apollo_d0/pr826_reference_v1"
RUNS = BUNDLE / "runtime/runs/pr826_greybox_demo_v1"


class PersistentAuditCoreRegressionTest(unittest.TestCase):
    def test_v4_pair_a_matches_frozen_logical_conclusion(self) -> None:
        contract_path = BENCH / "P4_SENS_V4_CONTRACT.yaml"
        contract = yaml.safe_load(contract_path.read_bytes())
        result = CORE.audit_pair(contract, contract_path, RUNS / "PY0_A", RUNS / "PY1_A")
        frozen = json.loads((BENCH / "P4_SENS_V4_PERSISTENT_SCREEN_AUDIT.json").read_text())
        self.assertTrue(frozen["persistent_s1_cancels_overtake"])
        self.assertTrue(result["persistent_s1_cancels_overtake"])
        self.assertEqual(result["runs"]["S0"]["outcome"]["overtake_success"], True)
        self.assertEqual(result["runs"]["S1"]["outcome"]["overtake_success"], False)
        self.assertFalse(result["runs"]["S0"]["validity"]["admission_valid"])

    def test_v5_pair_b_passes_frozen_confirmation_gate(self) -> None:
        contract_path = BENCH / "P4_SENS_V5_CONFIRMATION_CONTRACT.yaml"
        contract = yaml.safe_load(contract_path.read_bytes())
        result = CORE.audit_pair(contract, contract_path, RUNS / "PZ0_B", RUNS / "PZ1_B")
        self.assertEqual(result["status"], "PERSISTENT_INTERFACE_PAIR_PASS")
        self.assertTrue(result["runs"]["S0"]["validity"]["transport_valid"])
        self.assertTrue(result["runs"]["S1"]["validity"]["transport_valid"])
        self.assertTrue(result["runs"]["S1"]["validity"]["semantic_valid"])

    def test_unfrozen_contract_is_rejected_before_measurement(self) -> None:
        contract = yaml.safe_load((BENCH / "P4_SENS_V5_CONFIRMATION_CONTRACT.yaml").read_bytes())
        contract["status"] = "DRAFT"
        with self.assertRaisesRegex(ValueError, "not frozen"):
            CORE.adapt_contract(contract)


if __name__ == "__main__":
    unittest.main()
