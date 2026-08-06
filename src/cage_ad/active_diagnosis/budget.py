"""Atomic multidimensional budget ledger."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .contracts import AccessRegime, CostVector


NUMERIC_COST_FIELDS = tuple(name for name in CostVector.model_fields if name != "access")


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetProfile:
    profile_id: str
    limit: CostVector


class BudgetLedger:
    def __init__(self, profile: BudgetProfile, spent: CostVector | None = None) -> None:
        self.profile = profile
        self._spent = spent or CostVector()
        self._reservations: dict[str, CostVector] = {}
        self._lock = threading.RLock()
        self._assert_within(self._spent)

    @property
    def spent(self) -> CostVector:
        return self._spent

    @property
    def remaining(self) -> CostVector:
        values = {"access": self.profile.limit.access}
        for name in NUMERIC_COST_FIELDS:
            values[name] = max(0, getattr(self.profile.limit, name) - getattr(self._spent, name))
        return CostVector(**values)

    def _with_reservations(self) -> CostVector:
        total = self._spent
        for reserved in self._reservations.values():
            total = total.plus(reserved)
        return total

    def _assert_within(self, total: CostVector) -> None:
        if total.access.rank > self.profile.limit.access.rank:
            raise BudgetExceeded("access regime exceeds profile")
        exceeded = [
            name
            for name in NUMERIC_COST_FIELDS
            if getattr(total, name) > getattr(self.profile.limit, name) + 1e-9
        ]
        if exceeded:
            raise BudgetExceeded(f"budget exceeded: {', '.join(exceeded)}")

    def affordable(self, cost: CostVector) -> bool:
        with self._lock:
            try:
                self._assert_within(self._with_reservations().plus(cost))
            except BudgetExceeded:
                return False
            return True

    def reserve(self, transaction_id: str, maximum_cost: CostVector) -> None:
        with self._lock:
            if transaction_id in self._reservations:
                if self._reservations[transaction_id] != maximum_cost:
                    raise ValueError("transaction reservation changed")
                return
            self._assert_within(self._with_reservations().plus(maximum_cost))
            self._reservations[transaction_id] = maximum_cost

    def commit(self, transaction_id: str, measured_cost: CostVector) -> None:
        with self._lock:
            maximum = self._reservations.get(transaction_id)
            if maximum is None:
                raise KeyError("unknown budget reservation")
            for name in NUMERIC_COST_FIELDS:
                if getattr(measured_cost, name) > getattr(maximum, name) + 1e-9:
                    raise BudgetExceeded(f"measured {name} exceeds reserved maximum")
            if measured_cost.access.rank > maximum.access.rank:
                raise BudgetExceeded("measured access exceeds reserved maximum")
            new_total = self._spent.plus(measured_cost)
            self._assert_within(new_total)
            self._spent = new_total
            del self._reservations[transaction_id]

    def rollback(self, transaction_id: str) -> None:
        with self._lock:
            self._reservations.pop(transaction_id, None)

    def snapshot(self) -> dict:
        return {
            "profile_id": self.profile.profile_id,
            "limit": self.profile.limit.model_dump(mode="json"),
            "spent": self._spent.model_dump(mode="json"),
            "reservations": {
                key: value.model_dump(mode="json") for key, value in self._reservations.items()
            },
        }
