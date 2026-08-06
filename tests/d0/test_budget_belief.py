from __future__ import annotations

import math
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cage_ad.active_diagnosis.belief import BeliefState
from cage_ad.active_diagnosis.budget import BudgetExceeded, BudgetLedger, BudgetProfile
from cage_ad.active_diagnosis.contracts import CostVector, ResponsibilityDomain


def test_budget_reservation_commit_and_rollback(budget_profile) -> None:
    ledger = BudgetLedger(budget_profile)
    maximum = CostVector(access="L1", bytes=100, runtime_seconds=2)
    ledger.reserve("tx", maximum)
    assert ledger.affordable(maximum)
    ledger.commit("tx", CostVector(access="L1", bytes=80, runtime_seconds=1))
    assert ledger.spent.bytes == 80
    ledger.reserve("rollback", maximum)
    ledger.rollback("rollback")
    assert ledger.spent.bytes == 80


def test_measured_cost_cannot_exceed_reservation(budget_profile) -> None:
    ledger = BudgetLedger(budget_profile)
    ledger.reserve("tx", CostVector(access="L1", bytes=10))
    with pytest.raises(BudgetExceeded):
        ledger.commit("tx", CostVector(access="L1", bytes=11))


def test_property_budget_never_becomes_negative(budget_profile) -> None:
    rng = random.Random(20260806)
    ledger = BudgetLedger(budget_profile)
    for index in range(500):
        cost = CostVector(access="L1", bytes=rng.randrange(0, 500), runtime_seconds=rng.random())
        if ledger.affordable(cost):
            ledger.reserve(str(index), cost)
            ledger.commit(str(index), cost)
        remaining = ledger.remaining
        assert remaining.bytes >= 0
        assert remaining.runtime_seconds >= 0


def test_belief_update_is_normalized_and_deterministic() -> None:
    prior = {domain: 1 / 3 for domain in ResponsibilityDomain}
    likelihood = {
        ResponsibilityDomain.INTERACTION_FORECASTING: 0.1,
        ResponsibilityDomain.MOTION_PLANNING: 0.8,
        ResponsibilityDomain.TRACKING_EXECUTION: 0.1,
    }
    first = BeliefState(prior)
    second = BeliefState(prior)
    assert first.update(likelihood) == second.update(likelihood)
    assert math.isclose(sum(first.posterior.values()), 1.0)
    assert first.prediction_set(0.75) == [ResponsibilityDomain.MOTION_PLANNING]


@settings(max_examples=100, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=2_000), min_size=1, max_size=100))
def test_property_arbitrary_budget_sequences_are_atomic(byte_costs) -> None:
    budget_profile = BudgetProfile(
        profile_id="property",
        limit=CostVector(access="L1", bytes=100_000),
    )
    ledger = BudgetLedger(budget_profile)
    for index, byte_cost in enumerate(byte_costs):
        cost = CostVector(access="L1", bytes=byte_cost)
        before = ledger.spent
        if ledger.affordable(cost):
            ledger.reserve(str(index), cost)
            ledger.commit(str(index), cost)
            assert ledger.spent.bytes == before.bytes + byte_cost
        else:
            with pytest.raises(BudgetExceeded):
                ledger.reserve(str(index), cost)
            assert ledger.spent == before
        assert ledger.remaining.bytes >= 0
