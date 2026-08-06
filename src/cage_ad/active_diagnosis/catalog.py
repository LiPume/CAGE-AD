"""Action definitions and deterministic legality checks."""

from __future__ import annotations

from pydantic import Field, model_validator

from .contracts import AccessRegime, ActionProposal, ActionType, CostVector, StrictModel


class ActionDefinition(StrictModel):
    action_id: str = Field(min_length=1)
    action_type: ActionType
    semantic_slot: str = Field(min_length=1)
    required_regime: AccessRegime
    maximum_cost: CostVector
    allowed_parameter_keys: set[str] = Field(default_factory=set)
    repeatable: bool = False
    intervention: bool = False

    @model_validator(mode="after")
    def kind_matches(self) -> "ActionDefinition":
        if self.intervention != (self.action_type == ActionType.INTERVENTION):
            raise ValueError("intervention flag must match action type")
        if self.intervention and self.maximum_cost.intervention_count < 1:
            raise ValueError("intervention maximum cost must count the intervention")
        return self


class IllegalAction(RuntimeError):
    pass


class ActionCatalog:
    def __init__(self, definitions: list[ActionDefinition]) -> None:
        self._items = {definition.action_id: definition for definition in definitions}
        if len(self._items) != len(definitions):
            raise ValueError("duplicate action definition")

    def get(self, action_id: str) -> ActionDefinition:
        try:
            return self._items[action_id]
        except KeyError as exc:
            raise IllegalAction("action is absent from catalog") from exc

    def validate(
        self,
        proposal: ActionProposal,
        *,
        allowed_action_ids: set[str],
        observable_regime: AccessRegime,
        executed_actions: set[str],
    ) -> ActionDefinition:
        definition = self.get(proposal.action_id)
        if proposal.action_id not in allowed_action_ids:
            raise IllegalAction("action is not allowed for this episode")
        if proposal.action_type != definition.action_type:
            raise IllegalAction("proposal action type differs from catalog")
        if proposal.required_regime != definition.required_regime:
            raise IllegalAction("proposal regime differs from catalog")
        if definition.required_regime.rank > observable_regime.rank:
            raise IllegalAction("episode regime cannot authorize action")
        if proposal.action_id in executed_actions and not definition.repeatable:
            raise IllegalAction("non-repeatable action already executed")
        unexpected = set(proposal.requested_parameters) - definition.allowed_parameter_keys
        if unexpected:
            raise IllegalAction(
                "proposal contains parameters not declared by catalog: "
                + ", ".join(sorted(unexpected))
            )
        return definition

    def public_view(self, action_ids: set[str]) -> list[dict]:
        return [
            self._items[action_id].model_dump(mode="json")
            for action_id in sorted(action_ids)
            if action_id in self._items
        ]
