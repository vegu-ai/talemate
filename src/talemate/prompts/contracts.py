"""
Template contracts that code enforces when it uses a rendered prompt.

Code that rejects a result unless the template made a certain call on a
context value declares that call with `require_template_call`, in its own
module next to the check that enforces it.
The override compatibility check then grades an override as incompatible when
the shipped default makes the call and the override does not.
"""

from pydantic import BaseModel, field_validator

__all__ = [
    "TemplateContract",
    "require_template_call",
    "template_contracts",
]


class TemplateContract(BaseModel):
    # `name.attribute` as the template writes it, e.g. `snapshot_request.context_history`
    call: str
    reason: str

    @field_validator("call")
    @classmethod
    def _one_attribute(cls, value: str) -> str:
        name, _, attribute = value.partition(".")
        if not name or not attribute or "." in attribute:
            raise ValueError(f"expected `name.attribute`, got {value!r}")
        return value


_contracts: dict[str, TemplateContract] = {}


def require_template_call(call: str, reason: str) -> TemplateContract:
    contract = TemplateContract(call=call, reason=reason)
    _contracts[contract.call] = contract
    return contract


def template_contracts() -> list[TemplateContract]:
    return list(_contracts.values())
