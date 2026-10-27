"""Shipped defaults for the settings whose defaults changed in 0.40.0."""

from unittest.mock import AsyncMock

import pytest

from talemate.agents.creator.assistant import ContextualGenerateEmission
from talemate.agents.editor.revision import Issues
from talemate.agents.visual.schema import PROMPT_TYPE, BackendBase, VisualPrompt
from talemate.decisions.service import DecisionService
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage


def test_fast_character_generation_is_on_by_default(scene):
    creator = get_agent("creator")

    assert creator.cc_fast is True


def test_long_term_memory_number_of_queries_defaults_to_five(scene):
    field = (
        get_agent("narrator")
        .actions["use_long_term_memory"]
        .config["number_of_queries"]
    )

    assert field.value == 5
    assert (field.min, field.max) == (1, 10)


def test_every_rag_agent_shares_the_number_of_queries_default(scene):
    for agent_type in (
        "conversation",
        "narrator",
        "director",
        "editor",
        "creator",
        "summarizer",
        "world_state",
    ):
        agent = get_agent(agent_type)
        assert agent.long_term_memory_number_of_queries == 5, agent_type


def test_editor_revision_is_on_with_automatic_revision_off(scene):
    editor = get_agent("editor")

    assert editor.revision_enabled is True
    assert editor.revision_automatic_enabled is False


def test_visual_prompt_models_default_to_descriptive():
    assert VisualPrompt().prompt_type == PROMPT_TYPE.DESCRIPTIVE
    assert BackendBase().prompt_type == PROMPT_TYPE.DESCRIPTIVE


def test_visual_agent_prompt_types(scene):
    visual = get_agent("visual")

    assert visual.fallback_prompt_type == PROMPT_TYPE.DESCRIPTIVE
    created = {
        key: action.config["prompt_type"].value
        for key, action in visual.actions.items()
        if "prompt_type" in (action.config or {})
    }
    assert created == {
        "comfyui_image_create": PROMPT_TYPE.DESCRIPTIVE,
        "comfyui_image_edit": PROMPT_TYPE.DESCRIPTIVE,
        "sdnext_image_create": PROMPT_TYPE.DESCRIPTIVE,
        "sdnext_image_edit": PROMPT_TYPE.DESCRIPTIVE,
        "automatic1111_image_create": PROMPT_TYPE.KEYWORDS,
    }


class RequestProbe:
    """Records every LLM request and decision-model evaluation a test makes."""

    def __init__(self, monkeypatch, scene):
        self.prompts: list[str] = []
        self.decisions: list[str] = []
        self.client = scene.mock_client

        async def prompt_request(template, *args, **kwargs):
            self.prompts.append(template)
            return "", {
                "revision": "He checked the lantern.",
                "fix": "He checked the lantern.",
            }

        async def decision_evaluate(service, *args, **kwargs):
            self.decisions.append("evaluate")
            raise AssertionError("the decision model must not be called")

        monkeypatch.setattr(Prompt, "request", prompt_request)
        monkeypatch.setattr(DecisionService, "evaluate", decision_evaluate)

    @property
    def total(self) -> int:
        return len(self.prompts) + len(self.decisions) + len(self.client.prompt_history)


@pytest.fixture
def probe(scene, monkeypatch, isolate_signals):
    editor = get_agent("editor")
    monkeypatch.setattr(
        editor,
        "revision_collect_issues",
        AsyncMock(return_value=Issues(repetition_log=["Repeated phrasing."])),
    )
    monkeypatch.setattr(editor, "_emit_revision_diff", AsyncMock())
    isolate_signals("push_history", "push_history.after", "game_loop_new_message")
    scene.signals["push_history"].connect(editor.revision_on_push)
    return RequestProbe(monkeypatch, scene)


async def play_turn(scene, editor):
    """A normal turn: a character line and narration pushed to history, a
    regenerated message, and a contextual generation."""
    character = CharacterMessage(message="Bob: A raw response with repeated wording.")
    narration = NarratorMessage(message="Rain fell on the harbour, again.")
    await scene.push_history(character)
    await scene.push_history(narration)
    regenerated = await editor.maybe_revise_inplace(
        CharacterMessage(message="Bob: Another response with repeated wording.")
    )
    emission = ContextualGenerateEmission(
        agent=editor, template="x", response="A generated description."
    )
    await editor.revision_on_generation(emission)
    return character, narration, regenerated, emission


@pytest.mark.asyncio
@pytest.mark.parametrize("decision_checks", [False, True])
async def test_default_revision_settings_add_no_request_to_a_turn(
    scene, probe, decision_checks
):
    editor = get_agent("editor")
    revision_config = editor.actions["revision"].config
    revision_config["revision_method"].value = "rewrite"
    revision_config["decision_checks"].value = decision_checks

    assert editor.revision_enabled is True
    assert editor.revision_automatic_enabled is False
    assert editor.revision_decision_checks_active is decision_checks

    character, narration, regenerated, emission = await play_turn(scene, editor)

    assert probe.total == 0, (probe.prompts, probe.decisions)
    assert regenerated is False
    assert [len(m.versions) for m in (character, narration)] == [1, 1]
    assert emission.response == "A generated description."


@pytest.mark.asyncio
async def test_switching_automatic_revision_on_sends_requests(scene, probe):
    """The probe sees a revision once Automatic revision is on."""
    editor = get_agent("editor")
    editor.actions["revision"].config["automatic_revision"].value = True
    editor.actions["revision"].config["min_issues"].value = 1

    character, *_ = await play_turn(scene, editor)

    assert probe.total > 0
    assert character.versions[-1].source == "revision"
