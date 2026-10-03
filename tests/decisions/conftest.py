import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import TypeAdapter

from talemate.decisions import (
    ActionBudget,
    DecisionService,
    PolicyAction,
    PolicyInvocation,
    ProviderResponse,
)
from talemate.prompts.base import PrependTemplateDirectories, Prompt

from _decision_test_helpers import FakeDecisionProvider


class FakeProvider(FakeDecisionProvider):
    def __init__(self):
        super().__init__()
        self.answers = {"repeats": {"type": "noul", "p_true": 0.93}}
        self.raw = {"repeats": {"noul": 0.93}}

    def respond(self, request):
        return ProviderResponse(
            answers=copy.deepcopy(self.answers), response_body=copy.deepcopy(self.raw)
        )


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def policy_factory(tmp_path, monkeypatch, provider):
    import talemate.instance as instance

    template = Path(__file__).parents[1] / "data/decisions/editor-repetition.jinja2"
    (tmp_path / "policy.jinja2").write_text(template.read_text())
    editor = SimpleNamespace(
        threshold=0.80,
        revision_rewrite=AsyncMock(return_value="rewritten"),
    )
    editor.resolve_config = lambda action, setting: {("revision", "min_issues"): 1}[
        (action, setting)
    ]
    monkeypatch.setitem(instance.AGENTS, "editor", editor)
    generative = AsyncMock(side_effect=AssertionError("A policy called Prompt.send"))
    monkeypatch.setattr(Prompt, "send", generative)
    service = DecisionService(provider, enabled=True)
    fallback = AsyncMock(return_value="disabled result")
    events = []
    service.log.subscribe(events.append)
    adapter = TypeAdapter(str)

    def create(source=None, uid="editor.policy", **kwargs):
        if source is not None:
            (tmp_path / f"{uid.split('.', 1)[1]}.jinja2").write_text(source)
        budget = ActionBudget(limit=1)
        variables = kwargs.pop(
            "variables",
            {
                "passage": "original",
                "decision_checks": [editor],
                "last3": ["earlier"],
                "info": SimpleNamespace(text="original"),
            },
        )
        info = variables.get("info")

        async def revise(findings):
            return await editor.revision_rewrite(info=info, decision_findings=findings)

        defaults = {
            "service": service,
            "variables": variables,
            "validate_result": lambda value: adapter.validate_python(
                value, strict=True
            ),
            "disabled_path": fallback,
            "original_result": "original",
            "can_keep": True,
            "actions": {
                "revise": PolicyAction(
                    name="editor.revision_rewrite",
                    call=revise,
                    enabled=lambda: True,
                    budget=budget,
                    serialize_arguments=lambda arguments: {
                        "info": {"text": info.text},
                        "decision_findings": arguments["findings"],
                    },
                )
            },
        }
        return PolicyInvocation(uid, **{**defaults, **kwargs})

    with PrependTemplateDirectories(str(tmp_path)):
        yield SimpleNamespace(
            create=create,
            editor=editor,
            service=service,
            fallback=fallback,
            generative=generative,
            events=events,
            directory=tmp_path,
        )
