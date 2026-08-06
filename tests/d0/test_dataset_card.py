from __future__ import annotations

from pathlib import Path

import yaml

from cage_ad.adapters.apollo_d0.semantics import FaultMechanism, ScenarioKind


ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "docs/dataset/CAGE_AD_D0_DATASET_CARD.md"
DRAFT = ROOT / "benchmarks/apollo_d0/draft"


def test_dataset_card_covers_every_registered_scene_fault_and_action():
    """A registry change cannot silently leave the public dataset card stale."""
    text = CARD.read_text()
    required = {item.value for item in ScenarioKind} | {
        item.value for item in FaultMechanism
    }
    actions = yaml.safe_load((DRAFT / "actions.yaml").read_text())["actions"]
    required |= {item["id"] for item in actions}
    missing = sorted(identifier for identifier in required if f"`{identifier}`" not in text)
    assert missing == []


def test_dataset_card_does_not_claim_release_readiness_or_a_license():
    text = CARD.read_text()
    assert "尚不具备公开发布为正式 benchmark 的条件" in text
    assert "当前尚未选择数据集许可证" in text
