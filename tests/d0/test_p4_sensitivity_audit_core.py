#!/usr/bin/env python3
"""Compact regression tests for the common persistent-sensitivity audit schema."""

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
BENCH = ROOT / "benchmarks/apollo_d0/pr826_reference_v1"


class PersistentAuditCoreRegressionTest(unittest.TestCase):
    def test_v4_adapter_and_compact_regression_conclusion(self) -> None:
        contract = yaml.safe_load((BENCH / "contracts/P4_SENS_V4_CONTRACT.yaml").read_bytes())
        normalized = CORE.adapt_contract(contract)
        compact = json.loads((BENCH / "reports/P4_SENS_PAIR_A.json").read_text())
        self.assertEqual(normalized.version, "p4-sens-boundary-v4-persistent-screen")
        self.assertEqual(compact["contract_version"], normalized.version)
        self.assertEqual(compact["status"], "PERSISTENT_INTERFACE_PAIR_PASS")
        self.assertTrue(compact["persistent_s1_cancels_overtake"])

    def test_v5_pair_b_compact_metrics_and_repeat_hashes(self) -> None:
        contract = yaml.safe_load((BENCH / "P4_SENS_V5_CONFIRMATION_CONTRACT.yaml").read_bytes())
        normalized = CORE.adapt_contract(contract)
        pair_a = json.loads((BENCH / "reports/P4_SENS_PAIR_A.json").read_text())
        pair_b = json.loads((BENCH / "reports/P4_SENS_PAIR_B.json").read_text())
        self.assertEqual(normalized.version, "p4-sens-boundary-v5-persistent-confirmation")
        self.assertEqual(pair_b["status"], "PERSISTENT_INTERFACE_PAIR_PASS")
        for arm in ("S0", "S1"):
            self.assertEqual(
                pair_a["runs"][arm]["files"]["normalized_repeat_manifest_sha256"],
                pair_b["runs"][arm]["files"]["normalized_repeat_manifest_sha256"],
            )
            self.assertTrue(pair_b["runs"][arm]["validity"]["transport_valid"])
            self.assertTrue(pair_b["runs"][arm]["validity"]["semantic_valid"])

    def test_unfrozen_contract_is_rejected(self) -> None:
        contract = yaml.safe_load((BENCH / "P4_SENS_V5_CONFIRMATION_CONTRACT.yaml").read_bytes())
        contract["status"] = "DRAFT"
        with self.assertRaisesRegex(ValueError, "not frozen"):
            CORE.adapt_contract(contract)


if __name__ == "__main__":
    unittest.main()
