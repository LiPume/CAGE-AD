from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "scripts/d0/pr826/run_p3_semantic_fixture.py"


def test_p3_semantic_fixture_controls(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(RUNNER), "--output-dir", str(tmp_path)],
        check=True,
        cwd=REPO,
    )
    diff = json.loads((tmp_path / "semantic_fixture_diff.json").read_text())
    assert diff["status"] == "PASS"
    assert diff["changed_candidate_ids"] == ["A"]
    assert all(diff["controls"].values())
    fixed = json.loads((tmp_path / "semantic_fixture_fixed.json").read_text())
    faulty = json.loads((tmp_path / "semantic_fixture_faulty.json").read_text())
    assert fixed["final_selected_candidate"] == "A"
    assert faulty["final_selected_candidate"] == "B"
