from __future__ import annotations

from cage_ad.adapters.apollo_d0.semantics import FaultMechanism


def test_result_export_script_is_present_and_covers_all_faults():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    text = (root / "scripts/d0/export_smoke_results.py").read_text()
    assert "write_parquet" in text
    assert "write_svg" in text
    # Fault strings come from evaluator rows, so the exporter must not hard-code
    # a subset or silently discard an unfamiliar mechanism.
    assert "fault_mechanism" in text
    assert len(list(FaultMechanism)) == 6
