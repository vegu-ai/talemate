from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock
import json
import asyncio

import pytest
from structlog.testing import capture_logs

import talemate.emit.async_signals

import test_actor_perspective_history
from test_actor_perspective_history import PRIVATE, PUBLIC

from talemate.agents.base import AgentTemplateEmission
from talemate.agents.context import ActiveAgent
from talemate.agents.editor.revision import RevisionEmission, RevisionInformation
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.advice import (
    advice_context,
    advice_record_metadata,
)
from talemate.knowledge.perspectives import (
    set_source_perspectives,
    PerspectiveReadContext,
    source_reference,
    select_character_view,
)
from talemate.knowledge.schema import EntryVisibility
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage
from talemate.agents.narrator import NarratorAgentEmission
from talemate.agents.director.action_core.utils import reverse_trim_history

from talemate.knowledge.memory import audience_documents
from talemate.knowledge.perspective_models import PerspectiveOutput
from talemate.knowledge.snapshot_models import SnapshotPerspectives
from talemate.knowledge.snapshots import snapshot_for, snapshot_digest
from talemate.world_state.templates.content import WritingStyle
from talemate.agents.director.chat.nodes import DirectorChatAction
from talemate.agents.director.action_core import utils as action_utils
from talemate.agents.director.action_core.exceptions import ActionRejected
from talemate.util import count_tokens

from talemate.agents.director.chat.schema import (
    DirectorChatBudgets,
    DirectorChatMessage,
)
from talemate.agents.director.scene_direction.schema import SceneDirectionBudgets

from talemate.game.engine.nodes.core import GraphState

cast = test_actor_perspective_history.cast


@pytest.fixture
def advice(cast, monkeypatch):
    scene, message = cast
    monkeypatch.setattr(get_agent("memory"), "query", AsyncMock(return_value=[]))
    for name in ("director", "summarizer"):
        agent = get_agent(name)
        monkeypatch.setattr(agent, "rag_build", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent, "rag_build_for_author", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent, "emit_message", AsyncMock())
    return scene, message


def capture(monkeypatch, *, investigate=""):
    rendered = []

    async def request(template, client, kind, vars, **kwargs):
        rendered.append((template, Prompt.get(template, vars=vars).render(), vars))
        return "", {
            "analysis": "Ask who witnessed the event.",
            "guidance": "Ask for an account.",
            "investigate": investigate,
        }

    monkeypatch.setattr(Prompt, "request", request)
    return rendered


@pytest.mark.asyncio
async def test_character_analysis_uses_evidence_not_reader_current_moment(
    advice, monkeypatch
):
    scene, _ = advice
    summarizer = get_agent("summarizer")
    rendered = capture(monkeypatch)
    await summarizer.analyze_scene_for_next_action(
        "conversation", scene.character_data["Bob"]
    )
    assert len(rendered) == 1
    text = rendered[0][1]
    assert PUBLIC in text
    assert PRIVATE not in text
    assert "UNSEEN-VAULT-CODE" not in text
    assert "UNTRACKED-PRIVATE-HISTORY" not in text
    assert "who claimed what" in text
    assert "reader-only current moment" in text


@pytest.mark.asyncio
async def test_actor_guidance_separates_author_goal_and_target_evidence(
    advice, monkeypatch
):
    scene, _ = advice
    director = get_agent("director")
    rendered = capture(monkeypatch)
    await director.guide_actor_off_of_scene_analysis(
        "Author knows SECRET-HIDING-PLACE; advance the search.",
        scene.character_data["Bob"],
    )
    text = rendered[0][1]
    evidence = (
        text.lower()
        .split("character evidence for bob", 1)[1]
        .split("author analysis", 1)[0]
    )
    assert PUBLIC.lower() in evidence and PRIVATE.lower() not in evidence
    assert "SECRET-HIDING-PLACE" not in evidence
    assert "SECRET-HIDING-PLACE" in text
    assert "not evidence of what Bob knows" in text
    assert "Do not manufacture" in text
    get_agent("director").rag_build.assert_awaited_once()
    assert get_agent("director").rag_build.call_args.kwargs["character"].name == "Bob"


@pytest.mark.asyncio
async def test_contradictory_testimony_stays_attributed_in_analysis_input(
    advice, monkeypatch
):
    scene, message = advice
    testimony = "Alice says the door was locked. Cara says it was open. Bob does not know which account is correct."
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [{"audience": ["Bob"], "status": "ready", "text": testimony}],
    )
    rendered = capture(monkeypatch)
    await get_agent("summarizer").analyze_scene_for_next_action(
        "conversation", scene.character_data["Bob"]
    )
    assert testimony in rendered[0][1]
    assert "do not resolve contradictory testimony" in rendered[0][1]


def test_authored_visibility_and_private_motive_in_evidence(advice):
    scene, _ = advice
    alice = scene.character_data["Alice"]
    alice.base_attributes = {"name": "Alice", "plan": "PRIVATE-MOTIVE"}
    alice.visibility["plan"] = EntryVisibility(mode="owner")
    bob = advice_context(scene, scene.character_data["Bob"], 4096)
    owner = advice_context(scene, alice, 4096)
    assert "PRIVATE-MOTIVE" not in str(bob)
    assert "PRIVATE-MOTIVE" in str(owner)


@pytest.mark.asyncio
async def test_author_planning_keeps_reader_context_and_evidence_boundary(
    advice, monkeypatch
):
    scene, message = advice
    rendered = capture(monkeypatch)
    await get_agent("director").guide_narrator_off_of_scene_analysis("Reader planning.")
    text = rendered[0][1]
    assert "sapphire is hidden in her boot" in text
    assert "character evidence for bob" in text.lower()
    assert "author planning boundary" in text.lower()
    set_source_perspectives(
        scene, "message", message.id, [{"audience": ["Bob"], "status": "pending"}]
    )
    await get_agent("director").guide_narrator_off_of_scene_analysis("Reader planning.")
    # the empty view is left out; the rest of Bob's evidence stays available
    assert "Evidence is unavailable" not in rendered[-1][1]
    assert "character evidence for bob" in rendered[-1][1].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["guidance", "analysis"])
async def test_cache_and_direct_insert_reject_other_audience_and_edited_evidence(
    advice, operation
):
    scene, message = advice
    bob = scene.character_data["Bob"]
    alice = scene.character_data["Alice"]
    agent = get_agent("director" if operation == "guidance" else "summarizer")
    with ActiveAgent(
        agent, test_cache_and_direct_insert_reject_other_audience_and_edited_evidence
    ):
        if operation == "guidance":
            agent.actions["guide_scene"].config["cache_guidance"].value = True
            await agent.set_cached_guidance(
                "analysis", "BOB-ADVICE", "conversation", bob
            )
            assert await agent.get_cached_character_guidance("Bob") == "BOB-ADVICE"
            assert await agent.get_cached_character_guidance("Alice") is None
            assert (
                await agent.get_cached_guidance(
                    "analysis", character=alice, analysis_type="conversation"
                )
                is None
            )
        else:
            await agent.set_cached_analysis("conversation", "BOB-ADVICE", bob)
            assert await agent.get_cached_analysis("conversation", bob) == "BOB-ADVICE"
            assert await agent.get_cached_analysis("conversation", alice) is None
        emission = RevisionEmission(
            agent=get_agent("editor"), info=RevisionInformation(character=bob)
        )
        await agent.on_editor_revision_analysis_before(emission)
        assert [str(item) for item in emission.dynamic_instructions]
        scene.edit_message(message.id, "Alice: Revised private reader content.")
        emission.dynamic_instructions.clear()
        await agent.on_editor_revision_analysis_before(emission)
        assert not emission.dynamic_instructions
        if operation == "guidance":
            assert await agent.get_cached_character_guidance("Bob") is None


@pytest.mark.asyncio
async def test_deep_analysis_queries_character_evidence_and_clears_empty_result(
    advice, monkeypatch
):
    scene, _ = advice
    summarizer = get_agent("summarizer")
    summarizer.actions["analyze_scene"].config["deep_analysis"].value = True
    capture(monkeypatch, investigate="What did Alice say?")
    summarizer.rag_build.return_value = ["Alice claimed the door was locked."]
    bob = scene.character_data["Bob"]
    with ActiveAgent(
        summarizer,
        test_deep_analysis_queries_character_evidence_and_clears_empty_result,
    ):
        await summarizer.analyze_scene_for_next_action("conversation", bob)
        summarizer.rag_build.assert_awaited_once_with(
            character=bob,
            sub_instruction="What did Alice say?",
            retrieval_method="questions",
            include_raw_semantic=False,
        )
        summarizer.rag_build_for_author.assert_not_awaited()
        emission = AgentTemplateEmission(
            agent=get_agent("director"), template_vars={"character": bob}
        )
        summarizer._inject_deep_analysis_context(emission)
        assert "Alice claimed" in str(emission.dynamic_instructions)
        emission.template_vars["character"] = scene.character_data["Alice"]
        emission.dynamic_instructions.clear()
        summarizer._inject_deep_analysis_context(emission)
        assert not emission.dynamic_instructions
        summarizer.rag_build.return_value = []
        await summarizer.analyze_scene_for_next_action("conversation", bob)
        emission.template_vars["character"] = bob
        summarizer._inject_deep_analysis_context(emission)
        assert not emission.dynamic_instructions


@pytest.mark.asyncio
@pytest.mark.parametrize("typ", ["guidance", "analysis"])
async def test_evidence_change_during_generation_is_logged_without_retry(
    advice, monkeypatch, typ
):
    from structlog.testing import capture_logs

    scene, message = advice
    calls = []

    async def request(*args, **kwargs):
        calls.append(args)
        scene.edit_message(message.id, "Alice: Changed.")
        return "", {"guidance": "Old advice.", "analysis": "Old analysis."}

    monkeypatch.setattr(Prompt, "request", request)
    with capture_logs() as logs:
        if typ == "guidance":
            await get_agent("director").guide_actor_off_of_scene_analysis(
                "analysis", scene.character_data["Bob"]
            )
        else:
            await get_agent("summarizer").analyze_scene_for_next_action(
                "conversation", scene.character_data["Bob"]
            )
    assert {
        (log["character"], log["changed"])
        for log in logs
        if log["event"] == "advice evidence changed during generation"
    } == {("Bob", "evidence")}
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("typ", ["guidance", "analysis"])
async def test_scene_released_during_generation_stops_the_advice(
    advice, monkeypatch, typ
):
    scene, _ = advice
    agent = get_agent("director" if typ == "guidance" else "summarizer")
    state = dict(scene.agent_state.get(agent.agent_type, {}))

    async def request(*args, **kwargs):
        monkeypatch.setattr(agent, "scene", SimpleNamespace())
        return "", {"guidance": "Old advice.", "analysis": "Old analysis."}

    monkeypatch.setattr(Prompt, "request", request)
    generated = AsyncMock()
    signal = talemate.emit.async_signals.get(
        "agent.director.guide.generated"
        if typ == "guidance"
        else "agent.summarization.scene_analysis.after"
    )
    signal.connect(generated)
    try:
        with pytest.raises(GenerationCancelled):
            if typ == "guidance":
                await agent.guide_actor_off_of_scene_analysis(
                    "analysis", scene.character_data["Bob"]
                )
            else:
                await agent.analyze_scene_for_next_action(
                    "conversation", scene.character_data["Bob"]
                )
    finally:
        signal.disconnect(generated)
    generated.assert_not_awaited()
    assert scene.agent_state.get(agent.agent_type, {}) == state


@pytest.mark.asyncio
@pytest.mark.parametrize("released", [False, True])
async def test_scene_released_mid_batch_stops_the_next_call(
    advice, monkeypatch, released
):
    scene, _ = advice
    director = get_agent("director")
    node = DirectorChatAction()
    monkeypatch.setattr(action_utils, "get_node", lambda registry: lambda: node)

    async def execute(**kwargs):
        if released:
            monkeypatch.setattr(director, "scene", SimpleNamespace())
        return "executed"

    wrapper = AsyncMock(side_effect=execute)
    wrapper.get_argument_nodes = AsyncMock(return_value=[])
    monkeypatch.setattr(action_utils, "FunctionWrapper", lambda *args: wrapper)
    scene.nodegraph_state = GraphState()
    scene.nodegraph_state.shared["_director_chat_actions"] = {
        "direct_actor": "test/action"
    }
    call = {
        "function": "direct_actor",
        "arguments": {"character": "Bob", "direction": "Old advice"},
    }

    second = {**call, "arguments": {"character": "Bob", "direction": "More advice"}}

    async def request(*args, **kwargs):
        return "\n".join(
            "```json\n" + json.dumps(item) + "\n```" for item in (call, second)
        ), {}

    monkeypatch.setattr(Prompt, "request", request)
    with ActiveAgent(director, test_scene_released_mid_batch_stops_the_next_call):
        if released:
            with pytest.raises(GenerationCancelled):
                await action_utils.execute_actions(
                    director.client, scene, [{"name": "direct_actor"}], [], Mock()
                )
        else:
            await action_utils.execute_actions(
                director.client, scene, [{"name": "direct_actor"}], [], Mock()
            )
    assert wrapper.await_count == (1 if released else 2)


@pytest.mark.asyncio
async def test_scene_released_during_deep_analysis_sends_no_after_event(
    advice, monkeypatch
):
    scene, _ = advice
    summarizer = get_agent("summarizer")
    summarizer.actions["analyze_scene"].config["deep_analysis"].value = True
    capture(monkeypatch, investigate="What did Alice say?")

    async def released(**kwargs):
        monkeypatch.setattr(summarizer, "scene", SimpleNamespace())
        return ["Alice claimed the door was locked."]

    summarizer.rag_build.side_effect = released
    after = AsyncMock()
    signal = talemate.emit.async_signals.get(
        "agent.summarization.scene_analysis.after_deep_analysis"
    )
    signal.connect(after)
    try:
        with (
            ActiveAgent(
                summarizer,
                test_scene_released_during_deep_analysis_sends_no_after_event,
            ),
            pytest.raises(GenerationCancelled),
        ):
            await summarizer.analyze_scene_for_next_action(
                "conversation", scene.character_data["Bob"]
            )
    finally:
        signal.disconnect(after)
    summarizer.rag_build.assert_awaited_once()
    after.assert_not_awaited()


@pytest.mark.asyncio
async def test_dialogue_uses_validated_guidance_instead_of_unscoped_context(advice):
    scene, _ = advice
    conversation = get_agent("conversation")
    director = get_agent("director")
    bob = scene.character_data["Bob"]
    with ActiveAgent(conversation, conversation.build_prompt_default):
        director.set_context_states(actor_guidance="STALE-AUTHOR-SECRET")
        director.set_scene_states(
            cached_guidance={
                "character": "Bob",
                "analysis_type": "conversation",
                "guidance": "STALE-CACHE-SECRET",
            }
        )
        text = (await conversation.build_prompt_default(bob)).render()
        assert "STALE-AUTHOR-SECRET" not in text
        assert "STALE-CACHE-SECRET" not in text
        await director.set_cached_guidance(
            "analysis", "CURRENT-BOB-GUIDANCE", "conversation", bob
        )
        text = (await conversation.build_prompt_default(bob)).render()
        assert "CURRENT-BOB-GUIDANCE" in text
        text = (
            await conversation.build_prompt_default(scene.character_data["Cara"])
        ).render()
        assert "CURRENT-BOB-GUIDANCE" not in text


@pytest.mark.asyncio
async def test_narrator_emission_resolves_character_target_from_context(
    advice, monkeypatch
):
    scene, _ = advice
    summarizer = get_agent("summarizer")
    narrator = get_agent("narrator")
    summarizer.actions["analyze_scene"].enabled = True
    rendered = capture(monkeypatch)
    with ActiveAgent(
        narrator, test_narrator_emission_resolves_character_target_from_context
    ):
        narrator.set_context_states(character=scene.character_data["Bob"])
        emission = NarratorAgentEmission(agent=narrator)
        await summarizer.on_inject_instructions(emission)
    assert rendered[0][2]["character"].name == "Bob"
    assert PUBLIC in rendered[0][1]
    assert "sapphire is hidden in her boot" in rendered[0][1]
    assert emission.dynamic_instructions


@pytest.mark.asyncio
async def test_director_function_arguments_receive_character_evidence(advice):
    scene, _ = advice
    director = get_agent("director")
    with ActiveAgent(
        director, test_director_function_arguments_receive_character_evidence
    ):
        text = Prompt.get(
            "director.chat-execute-actions",
            vars={
                "scene": scene,
                "max_tokens": 8192,
                "history": [],
                "trim_action_history": reverse_trim_history,
                "selections": [
                    {"name": "direct_actor", "instructions": "Advance Bob's search."}
                ],
                "callbacks_unique": [],
                "focal": SimpleNamespace(render_instructions=lambda: "Call functions."),
            },
        ).render()
    assert "character evidence for bob" in text.lower()
    assert PUBLIC in text
    assert "author planning boundary" in text.lower()
    assert "direct_actor" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state_key,analysis_instruction,guidance_instruction",
    [
        (
            "visual_narration",
            "compelling visual description of Bob",
            "visual description of Bob",
        ),
        ("fn_narrate_character_entry", "bringing Bob into", "progress the scene"),
        ("fn_narrate_character_exit", "crafting Bob's exit", "progress the scene"),
        (
            "sensory_narration",
            "generate sensory details",
            "sensory details of the current moment",
        ),
    ],
)
async def test_narration_retains_reader_context_subtype_and_writing_style(
    advice, monkeypatch, state_key, analysis_instruction, guidance_instruction
):
    scene, _ = advice
    summarizer = get_agent("summarizer")
    director = get_agent("director")
    narrator = get_agent("narrator")
    summarizer.actions["analyze_scene"].config["deep_analysis"].value = True
    rendered = capture(monkeypatch, investigate="What happened earlier?")
    get_agent("world_state").actions["update_world_state"].config[
        "inject_as_scene_memory"
    ].value = True
    scene.world_state.location = "READER-ONLY-LOCATION"
    monkeypatch.setattr(
        type(scene),
        "writing_style",
        PropertyMock(
            return_value=WritingStyle(
                name="Regression", instructions="STYLE-REGRESSION"
            )
        ),
    )
    character = scene.character_data["Bob"]
    with ActiveAgent(
        narrator, test_narration_retains_reader_context_subtype_and_writing_style
    ):
        narrator.set_context_states(
            **{state_key: True, "character": character, "writing_style": True}
        )
        await summarizer.analyze_scene_for_next_action("narration", character)
        await director.guide_narrator_off_of_scene_analysis("Reader analysis.")
    assert rendered[0][0] == "summarizer.analyze-scene-for-next-narration"
    assert rendered[1][0] == "director.guide-narration"
    assert analysis_instruction in rendered[0][1]
    assert guidance_instruction in rendered[1][1]
    assert "READER-ONLY-LOCATION" in rendered[0][1]
    assert "STYLE-REGRESSION" in rendered[1][1]
    for _, text, _ in rendered:
        assert "sapphire is hidden in her boot" in text
        bob_evidence = (
            text.lower()
            .split("character evidence for bob", 1)[1]
            .split("character evidence for cara", 1)[0]
        )
        assert PUBLIC.lower() in bob_evidence
        assert "sapphire" not in bob_evidence
        assert "author planning boundary" in text.lower()
    assert all(
        call.kwargs.get("character") is None
        for call in summarizer.rag_build.await_args_list
    )
    summarizer.rag_build_for_author.assert_awaited_once()


@pytest.mark.asyncio
async def test_planning_batch_reuses_one_read_and_authored_derivation(
    advice, monkeypatch
):
    scene, _ = advice
    scene.active_characters.remove("Cara")
    read_factory = Mock(wraps=PerspectiveReadContext)
    authored = Mock(wraps=audience_documents)
    monkeypatch.setattr(
        "talemate.agents.director.guide.PerspectiveReadContext", read_factory
    )
    monkeypatch.setattr("talemate.agents.director.guide.audience_documents", authored)
    for module in ("advice", "context", "snapshots", "memory"):
        monkeypatch.setattr(
            f"talemate.knowledge.{module}.PerspectiveReadContext",
            Mock(side_effect=AssertionError("duplicate read")),
        )
    evidence = await get_agent("director").guidance_context()
    assert [item["character"] for item in evidence] == ["Alice", "Bob"]
    read_factory.assert_called_once_with(scene)
    authored.assert_called_once()
    assert PUBLIC in str(evidence)


def test_advice_snapshot_budget_omits_oversized_whole_entries(advice):
    scene, message = advice
    source = source_reference(scene, "message", message.id)
    source = select_character_view(scene, source, "Bob").source
    text = "OVERSIZED-SNAPSHOT " * 2000
    scene.world_state.location = text
    scene.world_state.location_perspectives = SnapshotPerspectives(
        content_digest=snapshot_digest("location", text),
        views=[
            PerspectiveOutput(
                audience=["Bob"], status="ready", text=text, sources=[source]
            )
        ],
    )
    assert snapshot_for(scene, "Bob")["location"] == text
    context = advice_context(scene, "Bob", 600)
    assert "OVERSIZED-SNAPSHOT" not in json.dumps(context)
    assert count_tokens(json.dumps(context["snapshot"])) <= 200
    assert PUBLIC in str(context)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_action_arguments_validate_evidence_before_callback(
    advice, monkeypatch, changed
):
    scene, message = advice
    director = get_agent("director")
    node = DirectorChatAction()
    monkeypatch.setattr(action_utils, "get_node", lambda registry: lambda: node)
    wrapper = AsyncMock(return_value="executed")
    wrapper.get_argument_nodes = AsyncMock(return_value=[])
    monkeypatch.setattr(action_utils, "FunctionWrapper", lambda *args: wrapper)
    scene.nodegraph_state = GraphState()
    scene.nodegraph_state.shared["_director_chat_actions"] = {
        "direct_actor": "test/action"
    }
    calls = []

    async def request(*args, **kwargs):
        calls.append(args)
        if changed:
            scene.edit_message(message.id, "Alice: Changed supporting evidence.")
        return (
            '```json\n{"function": "direct_actor", "arguments": {"character": "Bob", "direction": "Old advice"}}\n```',
            {},
        )

    monkeypatch.setattr(Prompt, "request", request)
    result_factory = Mock(return_value="result")
    with (
        ActiveAgent(director, test_action_arguments_validate_evidence_before_callback),
        capture_logs() as logs,
    ):
        result = await action_utils.execute_actions(
            director.client, scene, [{"name": "direct_actor"}], [], result_factory
        )
        assert result == ["result"]
        assert len(
            [
                log
                for log in logs
                if log["event"] == "advice evidence changed during generation"
            ]
        ) == int(changed)
        focal_call = wrapper.await_args.kwargs["_focal_call"]
        assert focal_call.name == "direct_actor"
        assert focal_call.arguments == {
            "character": "Bob",
            "direction": "Old advice",
        }
        wrapper.assert_awaited_once_with(
            _focal_call=focal_call, character="Bob", direction="Old advice"
        )
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("character", "Alice"),
        ("analysis_type", "narration"),
        ("context_fp", "stale"),
        ("evidence_fp", "stale"),
    ],
)
async def test_all_advice_cache_consumers_reject_mismatched_metadata(
    advice, field, value
):
    scene, _ = advice
    bob = scene.character_data["Bob"]
    director = get_agent("director")
    summarizer = get_agent("summarizer")
    director.actions["guide_scene"].config["cache_guidance"].value = True
    summarizer.actions["analyze_scene"].config["deep_analysis"].value = True
    with ActiveAgent(
        director, test_all_advice_cache_consumers_reject_mismatched_metadata
    ):
        await director.set_cached_guidance("analysis", "guidance", "conversation", bob)
        await summarizer.set_cached_analysis("conversation", "analysis", bob)
        metadata = advice_record_metadata(summarizer, bob, "conversation")
        metadata[field] = value
        summarizer.set_scene_states(
            deep_analysis_context="deep", deep_analysis_evidence=metadata
        )
        director.get_scene_state("cached_guidance")[field] = value
        summarizer.get_scene_state("cached_analysis_conversation")[field] = value
        assert (
            await director.get_cached_guidance(
                character=bob, analysis_type="conversation"
            )
            is None
        )
        assert await director.get_cached_character_guidance("Bob") is None
        assert await summarizer.get_cached_analysis("conversation", bob) is None
        emission = AgentTemplateEmission(
            agent=director,
            template_vars={"character": bob, "analysis_type": "conversation"},
        )
        summarizer._inject_deep_analysis_context(emission)
        assert not emission.dynamic_instructions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template",
    [
        "director.chat",
        "director.scene-direction",
        "director.guide-narration",
        "summarizer.analyze-scene-for-next-narration",
        "director.chat-execute-actions",
    ],
)
async def test_planning_evidence_is_reserved_before_history(
    advice, monkeypatch, template
):
    scene, _ = advice
    director = get_agent("director")
    scene_history = Mock(wraps=scene.context_history)
    monkeypatch.setattr(scene, "context_history", scene_history)
    history_trim = Mock(wraps=reverse_trim_history)
    budgets = (
        DirectorChatBudgets(max_tokens=8192, scene_context_ratio=0.5)
        if template == "director.chat"
        else SceneDirectionBudgets(max_tokens=8192, scene_context_ratio=0.5)
    )
    variables = {
        "scene": scene,
        "max_tokens": 8192,
        "budgets": budgets,
        "history": [DirectorChatMessage(source="user", message="Suggest a next step.")],
        "director_history_trim": history_trim,
        "direction_history_trim": history_trim,
        "trim_action_history": history_trim,
        "analysis": "Reader analysis.",
        "length": 256,
        "response_length": 256,
        "mode": "normal",
        "selections": [],
        "callbacks_unique": [],
        "focal": SimpleNamespace(render_instructions=lambda: "Call functions."),
    }
    with ActiveAgent(director, test_planning_evidence_is_reserved_before_history):
        text = Prompt.get(template, vars=variables).render()
        gated_budget = (
            history_trim.call_args.args[1]
            if template == "director.chat-execute-actions"
            else scene_history.call_args.kwargs["budget"]
        )
        reserved = budgets.reserved
        scene.knowledge_eligibility = "legacy"
        Prompt.get(template, vars=variables).render()
        if template in ("director.chat", "director.scene-direction"):
            assert reserved > budgets.reserved + 100
            assert gated_budget < scene_history.call_args.kwargs["budget"] - 50
        elif template in (
            "director.guide-narration",
            "summarizer.analyze-scene-for-next-narration",
        ):
            assert gated_budget < scene_history.call_args.kwargs["budget"] - 100
        else:
            assert gated_budget < 8192 - 300 - 100
    assert "character evidence for bob" in text.lower()
    assert count_tokens(text) < 8192


@pytest.mark.asyncio
async def test_planning_skips_missing_active_character_records(advice):
    scene, _ = advice
    scene.active_characters.append("Deleted character")
    context = await get_agent("director").guidance_context()
    assert [item["character"] for item in context] == ["Alice", "Bob", "Cara"]
    assert PUBLIC in str(context)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_point", ["chat", "direction"])
@pytest.mark.parametrize("concurrent", [False, True])
@pytest.mark.parametrize("changed", [False, True])
async def test_action_batch_admission_through_callers(
    advice, monkeypatch, entry_point, concurrent, changed
):
    scene, source = advice
    director = get_agent("director")
    node = DirectorChatAction()
    node.set_property("allow_concurrent", concurrent)
    monkeypatch.setattr(
        type(director.client),
        "supports_concurrent_inference",
        PropertyMock(return_value=concurrent),
    )
    monkeypatch.setattr(action_utils, "get_node", lambda registry: lambda: node)
    second_started = asyncio.Event()
    mutations = []

    async def act(**kwargs):
        mutations.append(kwargs["direction"])
        scene.history.append(NarratorMessage(message=f"Action: {kwargs['direction']}"))
        scene.ts += 1
        if concurrent and len(mutations) == 1:
            await asyncio.wait_for(second_started.wait(), 1)
        else:
            second_started.set()
        return "completed " + kwargs["direction"]

    wrapper = AsyncMock(side_effect=act)
    wrapper.get_argument_nodes = AsyncMock(return_value=[])
    monkeypatch.setattr(action_utils, "FunctionWrapper", lambda *args: wrapper)
    scene.nodegraph_state = GraphState()
    scene.nodegraph_state.shared["_director_chat_actions"] = {
        "direct_actor": "test/actor",
        "advance": "test/advance",
    }
    selections = [{"name": "direct_actor"}, {"name": "advance"}]
    decisions = AsyncMock(side_effect=[("Act now.", selections, ""), ("Done.", [], "")])
    monkeypatch.setattr(action_utils, "request_and_parse", decisions)
    monkeypatch.setattr(action_utils, "build_prompt_vars", AsyncMock(return_value={}))
    monkeypatch.setattr(director, "_chat_compact_if_needed", AsyncMock())
    monkeypatch.setattr(director, "_direction_compact_if_needed", AsyncMock())
    argument_requests = []

    async def request(template, *args, **kwargs):
        argument_requests.append(template)
        assert template == "director.chat-execute-actions"
        if changed:
            scene.edit_message(source.id, "Alice: Changed during argument generation.")
        calls = [
            {
                "function": name,
                "arguments": {"character": "Bob", "direction": str(index)},
            }
            for index, name in enumerate(("direct_actor", "advance", "direct_actor"))
        ]
        return "\n".join("```json\n" + json.dumps(call) + "\n```" for call in calls), {}

    monkeypatch.setattr(Prompt, "request", request)
    chat = director.chat_create()
    chat.title = "Regression"
    director._chat_save(chat)

    async def generate():
        if entry_point == "chat":
            return await director.chat_send(chat.id, "Carry out the plan.")
        return await director.direction_execute_turn(always_on=True, max_actions=2)

    with capture_logs() as logs:
        await generate()
    assert len(
        [
            log
            for log in logs
            if log["event"] == "advice evidence changed during generation"
        ]
    ) == int(changed)
    assert wrapper.await_count == 3
    assert sorted(mutations) == ["0", "1", "2"]
    assert decisions.await_count == (2 if entry_point == "chat" else 1)
    messages = (
        director.chat_get(chat.id).messages
        if entry_point == "chat"
        else director.direction_get().messages
    )
    results = [item for item in messages if item.type == "action_result"]
    assert len(results) == 3
    assert all(item.status == "success" for item in results)
    assert argument_requests == ["director.chat-execute-actions"]


@pytest.mark.asyncio
async def test_chat_persists_completed_actions_before_later_cancellation(
    advice, monkeypatch
):
    scene, _ = advice
    scene.nodegraph_state = GraphState()
    director = get_agent("director")
    chat = director.chat_create()
    chat.title = "Regression"
    director._chat_save(chat)
    decisions = AsyncMock(return_value=("Act now.", [{"name": "direct_actor"}], ""))
    monkeypatch.setattr(action_utils, "request_and_parse", decisions)
    monkeypatch.setattr(action_utils, "build_prompt_vars", AsyncMock(return_value={}))

    async def execute(*, create_result, on_action_complete, **kwargs):
        await on_action_complete(create_result(name="direct_actor", result="completed"))
        raise GenerationCancelled("Later generation cancelled")

    monkeypatch.setattr(action_utils, "execute_actions", execute)
    with pytest.raises(GenerationCancelled, match="Later generation cancelled"):
        await director.chat_send(chat.id, "Carry out the plan.")
    results = [
        item
        for item in director.chat_get(chat.id).messages
        if item.type == "action_result"
    ]
    assert [(item.name, item.result, item.status) for item in results] == [
        ("direct_actor", "completed", "success")
    ]
    decisions.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["perception", "legacy"])
@pytest.mark.parametrize("outcome", ["complete", "reject", "interrupt"])
async def test_chat_retains_action_inserted_message(advice, monkeypatch, mode, outcome):
    scene, _ = advice
    scene.nodegraph_state = GraphState()
    scene.knowledge_eligibility = mode
    director = get_agent("director")
    chat = director.chat_create()
    chat.title = "Regression"
    director._chat_save(chat)
    decisions = AsyncMock(
        side_effect=[
            ("Act now.", [{"name": "create_image"}, {"name": "direct_actor"}], ""),
            ("Done.", [], ""),
        ]
    )
    monkeypatch.setattr(action_utils, "request_and_parse", decisions)
    monkeypatch.setattr(action_utils, "build_prompt_vars", AsyncMock(return_value={}))
    monkeypatch.setattr(director, "_chat_compact_if_needed", AsyncMock())

    async def execute(*, create_result, on_action_complete, **kwargs):
        await director.chat_append_message(
            chat.id,
            DirectorChatMessage(
                source="director",
                type="asset_view",
                asset_id="generated-image",
                message="Generated image.",
            ),
        )
        await on_action_complete(create_result(name="create_image", result="created"))
        if outcome == "reject":
            raise ActionRejected("direct_actor", "Continue the scene")
        if outcome == "interrupt":
            raise GenerationCancelled("User interrupted")

    monkeypatch.setattr(action_utils, "execute_actions", execute)
    if outcome == "interrupt":
        with pytest.raises(GenerationCancelled, match="User interrupted"):
            await director.chat_send(chat.id, "Create an image, then continue.")
    else:
        await director.chat_send(chat.id, "Create an image, then continue.")
    messages = director.chat_get(chat.id).messages
    assert [item.asset_id for item in messages if item.type == "asset_view"] == [
        "generated-image"
    ]
    results = [
        (item.name, item.result, item.status)
        for item in messages
        if item.type == "action_result"
    ]
    assert results[0] == ("create_image", "created", "success")
    if outcome == "reject":
        assert results[1][0] == "direct_actor" and results[1][2] == "rejected"
    else:
        assert len(results) == 1
    assert decisions.await_count == (2 if outcome == "complete" else 1)
