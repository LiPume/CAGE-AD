from __future__ import annotations

import json
from pathlib import Path

import pytest

from cage_ad.active_diagnosis.budget import BudgetProfile
from cage_ad.active_diagnosis.catalog import ActionCatalog, ActionDefinition
from cage_ad.active_diagnosis.contracts import (
    AccessRegime,
    ActionProposal,
    ActionType,
    CostVector,
    EpisodeSpec,
    FailureWindow,
    ResponsibilityDomain,
)


@pytest.fixture
def roots(tmp_path: Path) -> dict[str, Path]:
    values = {
        "visible": tmp_path / "visible",
        "private": tmp_path / "private_oracle",
        "state": tmp_path / "state",
    }
    for path in values.values():
        path.mkdir()
    values["private"].chmod(0o700)
    return values


@pytest.fixture
def episode() -> EpisodeSpec:
    return EpisodeSpec(
        episode_id="opaque-episode-0001",
        scenario_template="opaque-scenario-a",
        failure_type="safety_violation",
        failure_window=FailureWindow(start_s=1, end_s=4),
        observable_regime=AccessRegime.L1,
        allowed_action_ids=["O1_motion", "I2_control"],
        budget_profile="B3",
        seed=7,
    )


@pytest.fixture
def catalog() -> ActionCatalog:
    return ActionCatalog(
        [
            ActionDefinition(
                action_id="O1_motion",
                action_type=ActionType.OBSERVATION,
                semantic_slot="motion_plan",
                required_regime=AccessRegime.L1,
                maximum_cost=CostVector(access="L1", bytes=4096, signals=1, runtime_seconds=1),
            ),
            ActionDefinition(
                action_id="I2_control",
                action_type=ActionType.INTERVENTION,
                semantic_slot="control_target",
                required_regime=AccessRegime.L1,
                maximum_cost=CostVector(
                    access="L1", bytes=4096, runtime_seconds=2, risk=2, intervention_count=1
                ),
                intervention=True,
            ),
        ]
    )


@pytest.fixture
def budget_profile() -> BudgetProfile:
    return BudgetProfile(
        profile_id="B3",
        limit=CostVector(
            access="L2",
            bytes=100_000,
            signals=10,
            replay_count=1,
            intervention_count=1,
            runtime_seconds=20,
            compute_seconds=20,
            human_minutes=0,
            risk=2,
            tokens=1000,
            api_cost_usd=1,
        ),
    )


def proposal(action_id: str, action_type: ActionType = ActionType.OBSERVATION) -> ActionProposal:
    return ActionProposal(
        proposal_id=f"proposal-{action_id}",
        proposed_by="test_policy",
        action_id=action_id,
        target_hypotheses=[ResponsibilityDomain.MOTION_PLANNING],
        required_regime="L1",
        action_type=action_type,
    )


def write_visible(path: Path, value: dict | None = None) -> Path:
    path.write_text(json.dumps(value or {"metric": "nominal", "value": 1}) + "\n")
    return path
