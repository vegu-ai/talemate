from _knowledge_step_helpers import push_and_step
from talemate.knowledge.step import knowledge_step
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from talemate.agents.context import ActiveAgent
from talemate.agents.summarize.perceptions import (
    passage_provenance,
    perception_backlog,
    perception_results_current,
)
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.formatting import format_message_view, perception_body
from talemate.knowledge.memory import audience_documents
from talemate.knowledge.perspectives import select_character_view, source_reference
from talemate.knowledge.snapshots import snapshot_audience_context
from talemate.knowledge.summaries import summary_inputs
from talemate.prompts import Prompt
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    NarratorMessage,
    ReinforcementMessage,
)
from talemate.tale_mate import Actor


def complete_response(context):
    text = json.dumps(
        {
            "views": [
                {
                    "audience": [character["name"]],
                    "status": "ready",
                    "exclusions": [],
                    "text": context["passage"]["text"],
                    "knowledge_ids": [],
                    "passage_ids": [],
                }
                for character in context["cast"]
            ]
        }
    )
    return text, {"response": text}


@pytest.fixture
def audience_scene(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    scene.character_data = {
        name: Character(name=name, is_player=name == "Bob") for name in ("Alice", "Bob")
    }
    scene.active_characters = ["Alice", "Bob"]
    summarizer = get_agent("summarizer")

    async def answer(*args, **kwargs):
        return complete_response(kwargs["vars"]["context"])

    request = AsyncMock(side_effect=answer)
    monkeypatch.setattr(Prompt, "request", request)
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="cancel")
    )
    with ActiveScene(scene):
        yield scene, summarizer, request


def selected(scene, message, name):
    return select_character_view(
        scene, source_reference(scene, "message", message.id), name
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("player_analysis", [False, True])
@pytest.mark.parametrize("source", ["ai", "player"])
async def test_speaker_verbatim_and_player_opt_in(
    audience_scene, player_analysis, source
):
    scene, summarizer, request = audience_scene
    summarizer.actions["perceptions"].config["analyze_player"].value = player_analysis
    message = CharacterMessage(
        message='Alice: *I smile.* "Good morning."', source=source
    )
    await push_and_step(scene, message)

    assert request.await_count == int(player_analysis)
    if player_analysis:
        context = request.await_args.kwargs["vars"]["context"]
        assert [entry["name"] for entry in context["cast"]] == ["Bob"]
        assert context["passage"]["speaker"] == "Alice"
        assert context["passage"]["text"] == '*I smile.* "Good morning."'
    assert perception_results_current(scene, message)
    for name in ("Alice", "Bob"):
        view = selected(scene, message, name)
        assert view.status == "ready"
        assert view.text == '*I smile.* "Good morning."'
        assert format_message_view(message, view.text, "chat") == message.message
        stored = next(view for view in message.knowledge.views if name in view.audience)
        assert stored.passage_provenance == (passage_provenance(message),)


@pytest.mark.asyncio
async def test_default_and_narrator_audience_toggle(audience_scene):
    scene, summarizer, request = audience_scene
    assert summarizer.resolve_config("perceptions", "analyze_player") is False
    for enabled, names in ((False, ["Alice"]), (True, ["Alice", "Bob"])):
        summarizer.actions["perceptions"].config["analyze_player"].value = enabled
        message = NarratorMessage(message="The bell rings.")
        await push_and_step(scene, message)
        context = request.await_args.kwargs["vars"]["context"]
        assert [entry["name"] for entry in context["cast"]] == names
        assert {view.status for view in message.knowledge.views} == {"ready"}
    assert request.await_count == 2


@pytest.mark.asyncio
async def test_player_own_turn_is_verbatim_even_with_analysis_enabled(audience_scene):
    scene, summarizer, request = audience_scene
    summarizer.actions["perceptions"].config["analyze_player"].value = True
    message = CharacterMessage(
        message="Bob: I remember the hidden key.", source="player"
    )
    await push_and_step(scene, message)
    assert [
        entry["name"] for entry in request.await_args.kwargs["vars"]["context"]["cast"]
    ] == ["Alice"]
    assert selected(scene, message, "Bob").text == "I remember the hidden key."


@pytest.mark.asyncio
async def test_verb_secret_speaker_keeps_unseen_aside(audience_scene):
    scene, _, request = audience_scene
    case = json.loads(
        (Path(__file__).parent / "data/perceptions/verb_secret.json").read_text()
    )
    message = CharacterMessage(message=case["source"])
    await push_and_step(scene, message)
    view = selected(scene, message, "Alice")
    assert format_message_view(message, view.text, "chat") == case["source"]
    assert "Bob set the blue vase on the sill." in view.text
    assert "pretended to sleep, though I heard every word" in view.text
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_passthrough_backlog_needs_no_confirmation(audience_scene, monkeypatch):
    scene, summarizer, request = audience_scene
    ask = AsyncMock(side_effect=AssertionError("No analysis needs approval"))
    monkeypatch.setattr(summarizer, "_ask_backlog", ask)
    messages = [CharacterMessage(message=f"Alice: Bell {index}.") for index in range(5)]
    await asyncio.wait_for(push_and_step(scene, messages), 3)
    assert all(perception_results_current(scene, message) for message in messages)
    assert perception_backlog(scene, messages).total == 0
    request.assert_not_awaited()
    ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_skipped_views_survive_other_audience_failure(audience_scene):
    scene, summarizer, request = audience_scene
    scene.character_data["Cora"] = Character(name="Cora")
    scene.active_characters.append("Cora")
    summarizer.actions["perceptions"].config["automatic_repair"].value = False
    request.side_effect = RuntimeError("Provider unavailable")
    message = CharacterMessage(message="Alice: The bell rings.")
    with pytest.raises(GenerationCancelled):
        await push_and_step(scene, message)
    assert selected(scene, message, "Alice").status == "ready"
    assert selected(scene, message, "Bob").status == "ready"
    assert selected(scene, message, "Cora").status == "failed"


@pytest.mark.asyncio
async def test_current_prompt_and_both_context_paths_are_body_only(audience_scene):
    scene, summarizer, request = audience_scene
    first = CharacterMessage(
        message='Alice: I point at a sign reading "Alice: welcome".'
    )
    await push_and_step(scene, first)
    summarizer.actions["perceptions"].config["analyze_player"].value = True
    message = CharacterMessage(message="Alice: *I ring the bell.*")
    await push_and_step(scene, message)
    context = request.await_args.kwargs["vars"]["context"]
    assert context["passage"]["text"] == "*I ring the bell.*"
    assert context["passage"]["speaker"] == "Alice"
    for item in (
        context["prior_physical_context"][0],
        context["cast"][0]["established_knowledge"][0],
    ):
        assert item["text"] == 'I point at a sign reading "Alice: welcome".'
        assert item["speaker"] == "Alice"
    prompt = Prompt.get(
        "summarizer.perceptions", vars=request.await_args.kwargs["vars"]
    ).render()
    assert "Alice: *I ring" not in prompt
    assert "Alice: I point" not in prompt
    assert "Alice: welcome" in prompt


@pytest.mark.asyncio
async def test_body_starting_with_speaker_name_is_not_stripped_twice(audience_scene):
    scene, summarizer, request = audience_scene
    await push_and_step(
        scene, CharacterMessage(message="Alice: Alice: welcome is what my sign says.")
    )
    summarizer.actions["perceptions"].config["analyze_player"].value = True
    await push_and_step(scene, CharacterMessage(message="Alice: I point to the sign."))
    context = request.await_args.kwargs["vars"]["context"]
    assert (
        context["prior_physical_context"][0]["text"]
        == "Alice: welcome is what my sign says."
    )
    assert (
        context["cast"][0]["established_knowledge"][0]["text"]
        == "Alice: welcome is what my sign says."
    )
    message = scene.history[0]
    assert (
        format_message_view(message, selected(scene, message, "Bob").text, "chat")
        == message.message
    )


@pytest.mark.parametrize(
    "message, expected",
    [
        (
            ReinforcementMessage(
                message="A locked chest.",
                meta={
                    "arguments": {"character": "Alice", "question": "What is hidden?"}
                },
            ),
            "What is hidden?\nA locked chest.",
        ),
        (
            ContextInvestigationMessage(
                message="A locked chest.",
                sub_type="query",
                meta={"arguments": {"query": "What is hidden?"}},
            ),
            "Query: What is hidden?: A locked chest.",
        ),
        (
            NarratorMessage(message="**A sign reads Alice: welcome.**"),
            "**A sign reads Alice: welcome.**",
        ),
    ],
)
def test_host_note_wrappers_removed_without_losing_semantic_content(message, expected):
    assert perception_body(message) == expected


@pytest.mark.asyncio
async def test_player_passthrough_consumers_and_save_reload(
    audience_scene, monkeypatch
):
    scene, _, request = audience_scene
    message = CharacterMessage(message="Alice: I hide the key. A bell rings.")
    await push_and_step(scene, message)
    scene.history[0] = message = CharacterMessage.model_validate(message.model_dump())
    assert perception_results_current(scene, message)
    assert selected(scene, message, "Bob").text == "I hide the key. A bell rings."

    player_summary = summary_inputs(scene, {"start": 0, "end": 0}, 0)["Bob"]
    assert player_summary.texts == (message.message,)
    docs = audience_documents(scene, groups={("message", message.id, 0)})
    assert any(
        doc["text"] == message.message and "Bob" in doc["meta"]["knowledge_audience"]
        for doc in docs.values()
    )
    snapshot = snapshot_audience_context(scene, 4096)
    assert all(
        item["established_knowledge"][0]["text"] == message.message
        for item in snapshot["cast"]
    )

    conversation = get_agent("conversation")
    player = scene.character_data["Bob"]
    actor = Actor(player, conversation)
    actor.scene = scene
    scene.actors.append(actor)
    monkeypatch.setattr(conversation, "rag_build", AsyncMock(return_value=[]))
    with ActiveAgent(conversation, conversation.build_prompt_default):
        prompt = (await conversation.build_prompt_default(player)).render()
    assert "I hide the key. A bell rings." in prompt
    assert "ALICE\nI hide the key." in prompt
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_setting_change_during_request_retries_new_audiences(audience_scene):
    scene, summarizer, request = audience_scene
    contexts = []

    async def toggle(*args, **kwargs):
        context = kwargs["vars"]["context"]
        contexts.append(context)
        summarizer.actions["perceptions"].config["analyze_player"].value = True
        return complete_response(context)

    request.side_effect = toggle
    message = NarratorMessage(message="A bell rings.")
    await push_and_step(scene, message)
    assert [[item["name"] for item in context["cast"]] for context in contexts] == [
        ["Alice"],
        ["Alice", "Bob"],
    ]
    assert perception_results_current(scene, message)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        CharacterMessage(message="Alice: "),
        CharacterMessage(message="Alice:\n"),
        NarratorMessage(message=""),
        NarratorMessage(message=" \n"),
    ],
)
async def test_empty_body_has_omitted_records_without_analysis(audience_scene, message):
    scene, summarizer, request = audience_scene
    summarizer.actions["perceptions"].config["analyze_player"].value = True
    await push_and_step(scene, message)
    assert perception_results_current(scene, message)
    assert all(
        view.status == "omitted" and view.text is None
        for view in message.knowledge.views
    )
    assert all(
        view.passage_provenance == (passage_provenance(message),)
        for view in message.knowledge.views
    )
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("refresh", [False, True])
@pytest.mark.parametrize("change_context", [False, True])
async def test_audience_retry_preserves_manual_view_unless_context_changes(
    audience_scene, enabled, refresh, change_context
):
    from talemate.knowledge.perspectives import (
        edit_message_view,
        set_source_perspectives,
    )

    scene, summarizer, request = audience_scene
    scene.character_data["Cora"] = Character(name="Cora")
    scene.active_characters.append("Cora")
    summarizer.actions["perceptions"].config["analyze_player"].value = enabled
    message = NarratorMessage(message="The bell rings.")
    if refresh:
        message.append_version("The bell rings twice.", "regenerate")
    await push_and_step(scene, message)
    edit_message_view(scene, message.id, "Alice", "My hand-edited account.")
    outputs = [v.model_dump(exclude={"revision"}) for v in message.knowledge.views]
    for output in outputs:
        if "Alice" not in output["audience"]:
            output.update(
                status="pending", text=None, sources=(), passage_provenance=()
            )
    set_source_perspectives(scene, "message", message.id, outputs)
    manual = next(
        v for v in message.knowledge.views if "Alice" in v.audience
    ).model_dump()
    contexts = []

    async def toggle(*args, **kwargs):
        context = kwargs["vars"]["context"]
        contexts.append(context)
        summarizer.actions["perceptions"].config["analyze_player"].value = not enabled
        if change_context:
            scene.character_data[
                "Cora"
            ].description = "A changed character description."
        return complete_response(context)

    request.side_effect = toggle
    if refresh:
        from talemate.knowledge.revision_refresh import refresh_revision

        await refresh_revision(scene, message)
        assert message.revision_state.status == "clean"
    else:
        await knowledge_step(scene)
    expected = [["Bob", "Cora"], ["Cora"]] if enabled else [["Cora"], ["Bob", "Cora"]]
    if change_context:
        expected[1].insert(0, "Alice")
    assert [[c["name"] for c in context["cast"]] for context in contexts] == expected
    current = next(
        v for v in message.knowledge.views if "Alice" in v.audience
    ).model_dump()
    assert (current == manual) is not change_context
    assert current["text"] == (
        perception_body(message) if change_context else "My hand-edited account."
    )
    assert perception_results_current(scene, message)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reinforcement", "world", "investigation"])
async def test_note_subject_and_framing_reach_every_message_consumer(
    audience_scene, monkeypatch, kind
):
    from talemate.knowledge.context import project_character_history

    scene, _, _ = audience_scene
    if kind == "reinforcement":
        message = ReinforcementMessage(
            message="In the kitchen.",
            meta={"arguments": {"character": "Alice", "question": "Current location?"}},
        )
        expected = "# Internal note for Alice - Current location?\nIn the kitchen."
    elif kind == "world":
        message = ReinforcementMessage(message="The lantern is lit.")
        message.set_source(
            "world_state",
            "update_reinforcement",
            character=None,
            question="Lantern state?",
        )
        expected = "# Internal note - Lantern state?\nThe lantern is lit."
    else:
        message = ContextInvestigationMessage(
            message="A green coat.",
            sub_type="visual-character",
            meta={"arguments": {"character": "Alice"}},
        )
        expected = "# Visual description of Alice in the current moment: A green coat."
    await push_and_step(scene, message)
    assert selected(scene, message, "Bob").text == perception_body(message)
    assert expected in "\n".join(project_character_history(scene, "Bob"))
    assert summary_inputs(scene, {"start": 0, "end": 0}, 0)["Bob"].texts == (expected,)
    docs = audience_documents(scene, groups={("message", message.id, 0)})
    assert any(
        doc["text"] == expected and "Bob" in doc["meta"]["knowledge_audience"]
        for doc in docs.values()
    )
    snapshot = snapshot_audience_context(scene, 4096)
    assert (
        next(c for c in snapshot["cast"] if c["name"] == "Bob")[
            "established_knowledge"
        ][0]["text"]
        == expected
    )
    conversation = get_agent("conversation")
    monkeypatch.setattr(conversation, "rag_build", AsyncMock(return_value=[]))
    actor = Actor(scene.character_data["Bob"], conversation)
    actor.scene = scene
    scene.actors.append(actor)
    with ActiveAgent(conversation, conversation.build_prompt_default):
        rendered = (await conversation.build_prompt_default(actor.character)).render()
    assert expected in rendered


@pytest.mark.asyncio
async def test_tracker_insert_names_its_subject_in_player_prompt(audience_scene):
    from talemate.world_state import Reinforcement
    from talemate.knowledge.perspectives import edit_message_view

    scene, _, _ = audience_scene
    for character in scene.character_data.values():
        actor = Actor(character, get_agent("conversation"))
        actor.scene = scene
        scene.actors.append(actor)
    tracker = Reinforcement(
        question="Secret destination?", character="Alice", insert="conversation-context"
    )
    scene.world_state.reinforce.append(tracker)
    world = get_agent("world_state")
    await world._apply_reinforcement(
        tracker, world._prepare_reinforcement(tracker, False), "In the kitchen.", False
    )
    source = tracker.source_for(scene)
    edit_message_view(scene, source.id, "Bob", "In the kitchen.")
    rendered = Prompt.get(
        "common.extra-context-static",
        vars={
            "scene": scene,
            "knowledge_viewer": "Bob",
            "reinforcement_character": "Alice",
            "reinforcement_character_inserts": ["conversation-context"],
        },
    ).render()
    assert "# Internal note for Alice - In the kitchen." in rendered
    assert "Secret destination?" not in rendered
    docs = audience_documents(scene, groups={("authored",)})
    assert any(
        doc["text"] == "# Internal note for Alice - In the kitchen."
        and "Bob" in doc["meta"]["knowledge_audience"]
        for doc in docs.values()
    )
