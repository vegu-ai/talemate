"""
The facts-only prompt: facts for content whose summary already exists, with
the stored summary as context and the same facts shape as the summary call.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import talemate.emit.async_signals as async_signals
from conftest import MockScene, bootstrap_scene
from talemate.agents.base import DynamicInstruction
from talemate.agents.summarize.response_specs import (
    FACTS_SPEC,
    SUMMARY_WITH_FACTS_SPEC,
)
from talemate.context import ActiveScene
from talemate.knowledge.schema import Fact, ParsedFact
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, TimePassageMessage

CONTENT = "[11] Mara: The lamp is out.\n\n[12] Edwin: I will fix it at dawn."
STORED = "Mara reports the lamp is out; Edwin promises a repair."


@pytest.fixture
def summarizer_scene():
    scene = MockScene()
    agents = bootstrap_scene(scene)
    with ActiveScene(scene):
        yield scene, agents["summarizer"]


def render(scene, uid, **values):
    variables = {
        "scene": scene,
        "dialogue": CONTENT,
        "summary": STORED,
        "max_tokens": 8192,
        "num_extra_context": 0,
        "extra_context": [],
        "summarization_method": "balanced",
        "extract_facts": True,
        "line_ids": True,
        "audience_summary": None,
        "fact_evidence": "",
        "previous_facts": [Fact(id="F1", text="The lamp was lit.")],
        **values,
    }
    with ActiveScene(scene):
        return Prompt.get(uid, vars=variables).render()


def facts_section(rendered):
    start = rendered.index("Record a fact only when")
    return rendered[start : rendered.index("</FACTS>", start)]


def test_prompt_reads_the_lines_with_the_stored_summary_as_context(summarizer_scene):
    scene, _ = summarizer_scene
    rendered = render(scene, "summarizer.extract-facts")
    assert CONTENT in rendered
    assert "## Stored summary of chapter 1" in rendered and STORED in rendered
    assert "Take every fact from the content of chapter 1" in rendered
    assert "valid even when the summary leaves it out" in rendered
    assert (
        "When the summary and the content disagree, the content is correct." in rendered
    )
    assert "consistent with" not in rendered
    assert "Do not write a new summary." in rendered
    assert "SUMMARY:" not in rendered and "ANALYSIS:" not in rendered
    assert "[F1] Fact: The lamp was lit." in rendered
    assert '"message_id"' in rendered


def test_prompt_without_a_stored_summary_reads_only_the_content(summarizer_scene):
    scene, _ = summarizer_scene
    rendered = render(scene, "summarizer.extract-facts", summary="", line_ids=False)
    assert "stored summary" not in rendered.lower()
    assert '"message_id"' not in rendered


@pytest.mark.parametrize("audience", [None, ("Mara",)])
@pytest.mark.parametrize("line_ids", [False, True])
def test_both_prompts_ask_for_the_same_facts_shape(
    summarizer_scene, audience, line_ids
):
    scene, _ = summarizer_scene
    values = {
        "audience_summary": audience,
        "line_ids": line_ids,
        "fact_evidence": "M11R1S0: the lamp is out" if audience else "",
    }
    combined = facts_section(render(scene, "summarizer.summarize-dialogue", **values))
    facts_only = facts_section(render(scene, "summarizer.extract-facts", **values))
    assert (
        combined.replace(" Preserve this phrase in the summary too.", "") == facts_only
    )
    assert "Between 0 and 12 items" in facts_only
    assert ("evidence_id" in facts_only) is bool(audience)


async def test_request_uses_the_facts_prompt_and_extractor(summarizer_scene):
    scene, summarizer = summarizer_scene
    scene.world_state.facts["F1"] = Fact(id="F1", text="The lamp was lit.")
    response = (
        "<FACTS>\n"
        '[{"text": "Mara reports the lamp is out.", "message_id": 11,'
        ' "supersedes": "F1"}]\n</FACTS>'
    )
    with patch.object(
        Prompt,
        "request",
        AsyncMock(return_value=(response, FACTS_SPEC.extract_all(response))),
    ) as request:
        parsed = await summarizer.extract_facts(CONTENT, summary=STORED, line_ids=True)
    assert [(fact.text, fact.message_id, fact.supersedes) for fact in parsed] == [
        ("Mara reports the lamp is out.", 11, "F1")
    ]
    assert request.call_args.args[0] == "summarizer.extract-facts"
    assert request.call_args.args[2] == "summarize_2048"
    assert request.call_args.kwargs["response_spec"] is FACTS_SPEC
    values = request.call_args.kwargs["vars"]
    assert values["dialogue"] == CONTENT and values["summary"] == STORED
    assert values["line_ids"] is True
    assert [fact.id for fact in values["previous_facts"]] == ["F1"]


async def test_summary_that_is_the_content_is_not_repeated(summarizer_scene):
    _, summarizer = summarizer_scene
    with patch.object(
        Prompt, "request", AsyncMock(return_value=("", {"facts": "[]"}))
    ) as request:
        assert await summarizer.extract_facts(STORED, summary=STORED) == []
    assert request.call_args.kwargs["vars"]["summary"] == ""


async def test_unreadable_facts_are_none_and_unoffered_restatements_drop(
    summarizer_scene,
):
    scene, summarizer = summarizer_scene
    scene.world_state.facts["F1"] = Fact(id="F1", text="Stored, not offered.")
    with patch.object(
        Prompt, "request", AsyncMock(return_value=("prose", {"facts": "no list"}))
    ):
        assert await summarizer.extract_facts(CONTENT) is None
    restated = {"facts": json.dumps([{"text": "Repeat.", "restates": "F1"}])}
    with patch.object(Prompt, "request", AsyncMock(return_value=("", restated))):
        parsed = await summarizer.extract_facts(CONTENT, include_previous_facts=False)
    assert [fact.restates for fact in parsed] == [None]


async def test_audience_facts_require_perception_mode(summarizer_scene):
    _, summarizer = summarizer_scene
    with pytest.raises(ValueError, match="perception"):
        await summarizer.extract_facts(CONTENT, audience=("Mara",))


async def test_fresh_summarization_keeps_the_combined_call(summarizer_scene):
    scene, summarizer = summarizer_scene
    summarizer.actions["archive"].config["threshold"].value = 100000
    both = ["Mara", "Edwin"]
    scene.history = [
        CharacterMessage(message="Mara: one", present=both),
        CharacterMessage(message="Edwin: two", present=both),
        TimePassageMessage(ts=60, message="A minute passes", present=both),
        CharacterMessage(message="Mara: trailing", present=both),
    ]
    response = "ANALYSIS: x\nSUMMARY: They met.\n<FACTS>\n[]\n</FACTS>"
    summarizer.extract_facts = AsyncMock(side_effect=AssertionError("facts only"))
    with (
        patch.object(
            Prompt,
            "request",
            AsyncMock(
                return_value=(response, SUMMARY_WITH_FACTS_SPEC.extract_all(response))
            ),
        ) as request,
        patch("talemate.agents.summarize.refresh_topics", AsyncMock()),
    ):
        assert await summarizer.build_archive(scene) is True
    assert request.call_args.args[0] == "summarizer.summarize-dialogue"
    assert request.call_args.kwargs["response_spec"] is SUMMARY_WITH_FACTS_SPEC
    assert scene.archived_history[0]["text"] == "They met."


async def test_author_hooks_can_steer_and_replace_the_facts(summarizer_scene):
    _, summarizer = summarizer_scene
    seen = []

    async def before(emission):
        seen.append(("before", emission.summary))
        emission.dynamic_instructions.append(
            DynamicInstruction(title="Names", content="Spell out every name.")
        )

    async def after(emission):
        seen.append(("after", [fact.text for fact in emission.facts]))
        emission.facts = [ParsedFact(text="Replaced by a hook.")]

    before_signal = async_signals.get("agent.summarization.extract_facts.before")
    after_signal = async_signals.get("agent.summarization.extract_facts.after")
    before_signal.connect(before)
    after_signal.connect(after)
    try:
        with patch.object(
            Prompt,
            "request",
            AsyncMock(return_value=("", {"facts": '[{"text": "Model fact."}]'})),
        ) as request:
            parsed = await summarizer.extract_facts(CONTENT, summary=STORED)
            instructions = request.call_args.kwargs["vars"]["dynamic_instructions"]
            assert [item.content for item in instructions] == ["Spell out every name."]
            assert [fact.text for fact in parsed] == ["Replaced by a hook."]
            seen.clear()
            parsed = await summarizer.extract_facts(
                CONTENT, summary=STORED, skip_author_hooks=True
            )
            assert seen == [] and [fact.text for fact in parsed] == ["Model fact."]
    finally:
        before_signal.disconnect(before)
        after_signal.disconnect(after)
