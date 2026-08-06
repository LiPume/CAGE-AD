"""Shared deterministic Bayesian responsibility belief."""

from __future__ import annotations

import math

from .contracts import ResponsibilityDomain


class BeliefState:
    def __init__(self, posterior: dict[ResponsibilityDomain, float]) -> None:
        self._posterior = self._normalize(posterior)

    @staticmethod
    def _normalize(values: dict[ResponsibilityDomain, float]) -> dict[ResponsibilityDomain, float]:
        if not values or any(not math.isfinite(value) or value < 0 for value in values.values()):
            raise ValueError("belief weights must be finite, non-negative, and non-empty")
        total = sum(values.values())
        if total <= 0:
            raise ValueError("belief weights must have positive mass")
        return {domain: value / total for domain, value in values.items()}

    @property
    def posterior(self) -> dict[ResponsibilityDomain, float]:
        return dict(self._posterior)

    def update(self, likelihoods: dict[ResponsibilityDomain, float]) -> dict[ResponsibilityDomain, float]:
        if set(likelihoods) != set(self._posterior):
            raise ValueError("likelihood domains must exactly match belief domains")
        smoothed = {
            domain: self._posterior[domain] * max(float(likelihoods[domain]), 1e-12)
            for domain in self._posterior
        }
        self._posterior = self._normalize(smoothed)
        return self.posterior

    def entropy(self) -> float:
        return -sum(value * math.log(value) for value in self._posterior.values() if value > 0)

    def prediction_set(self, mass: float = 0.9) -> list[ResponsibilityDomain]:
        if not 0 < mass <= 1:
            raise ValueError("prediction-set mass must be in (0, 1]")
        selected: list[ResponsibilityDomain] = []
        cumulative = 0.0
        for domain, probability in sorted(
            self._posterior.items(), key=lambda item: (-item[1], item[0].value)
        ):
            selected.append(domain)
            cumulative += probability
            if cumulative + 1e-12 >= mass:
                break
        return selected
