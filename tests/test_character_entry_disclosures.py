"""Perspectives lifecycle tests for generated character-entry briefings."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from talemate.agents.conversation.entry_context import (
    ENTRY_BRIEFING_DISCLOSURE_ORIGIN,
    consume_entry_turn,
    entry_briefings,
    entry_windows,
    start_entry_window,
)
from talemate.agents.context import active_agent
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.events import CharacterActivatedEvent
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.schema import Fact
from talemate.knowledge.perspectives import set_source_perspectives
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage
from talemate.server.world_state_manager import WorldStateManagerPlugin
from talemate.tale_mate import Actor


@pytest.fixture
def perspectives_entry_scene(scene):
    conversation = get_agent("conversation")
    alice = Character(name="Alice", description="An observant courier.")
    actor = Actor(alice, conversation)
    actor.scene = scene
    scene.actors.append(actor)
    scene.active_characters.append(alice.name)
    scene.character_data[alice.name] = alice
    scene.knowledge_eligibility = "perception"
    conversation.actions["character_knowledge"].config[
        "brief_characters_on_entry"
    ].value = True
    conversation.history_context = AsyncMock(return_value=["Alice saw the harbor."])
    conversation.absence_block = AsyncMock(return_value=[])
    with ActiveScene(scene):
        yield scene, conversation, alice


def activation(scene, character):
    return CharacterActivatedEvent(
        scene=scene,
        character=character,
        event_type="character.activated",
    )


async def generate_on_entry(scene, conversation, character, text="I scan the room."):
    with patch.object(Prompt, "request", new_callable=AsyncMock) as request:
        request.return_value = ("", {"briefing": text, "offscreen": None})
        await conversation.on_character_activated(activation(scene, character))
    request.assert_awaited_once()
    return scene.knowledge.disclosures[0]


@pytest.mark.asyncio
async def test_perspectives_activation_stores_targeted_origin_disclosure(
    perspectives_entry_scene,
):
    scene, conversation, alice = perspectives_entry_scene

    disclosure = await generate_on_entry(scene, conversation, alice)

    assert disclosure.origin == ENTRY_BRIEFING_DISCLOSURE_ORIGIN
    assert disclosure.audience == ("Alice",)
    assert entry_briefings(conversation) == {}
    rendered = conversation.character_entry_context(alice)
    assert "Character entry briefing" in rendered
    assert "I scan the room." in rendered


@pytest.mark.asyncio
async def test_regenerate_replaces_in_place_restarts_window_and_keeps_offscreen_fact(
    perspectives_entry_scene, monkeypatch
):
    scene, conversation, alice = perspectives_entry_scene
    original = await generate_on_entry(scene, conversation, alice)
    original_window = entry_windows(conversation)["Alice"].model_copy(deep=True)
    for _ in range(conversation.knowledge_character_entry_turns - 1):
        consume_entry_turn(conversation, alice.name)
    scene.world_state.facts["offscreen-life"] = Fact(
        id="offscreen-life", text="Alice traded along the coast."
    )
    offscreen = scene.world_state.facts["offscreen-life"].model_copy(deep=True)
    scene.ts += 60
    message = NarratorMessage("The harbor bell rings.", present=["Alice"])
    scene.history.append(message)
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [{"audience": ["Alice"], "status": "ready", "text": str(message)}],
    )
    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)
    summarizer = get_agent("summarizer")
    monkeypatch.setattr(
        summarizer, "rebuild_supported_facts", AsyncMock(return_value=None)
    )

    async def request_with_active_agent(*args, **kwargs):
        assert active_agent.get().agent is conversation
        assert "The harbor bell rings" in kwargs["vars"]["arrival"]
        assert "Time since entry: 1 Minute" in kwargs["vars"]["arrival"]
        return "", {"briefing": "I reassess everyone here.", "offscreen": None}

    with patch.object(
        Prompt, "request", new_callable=AsyncMock, side_effect=request_with_active_agent
    ) as request:
        task = await plugin.handle_regenerate_entry_briefing(
            {
                "name": "Alice",
                "disclosure_id": original.id,
                "request_id": "regen-1",
            }
        )
        await task

    request.assert_awaited_once()
    current = scene.knowledge.disclosures[0]
    assert current.id == original.id
    assert current.revision == original.revision + 1
    assert current.text == "I reassess everyone here."
    assert current.acquired.order > original.acquired.order
    restarted = entry_windows(conversation)["Alice"]
    assert restarted.remaining_turns == 3
    assert restarted.boundary_message_id == original_window.boundary_message_id
    assert restarted.entry_scene_time == original_window.entry_scene_time
    assert restarted.briefing_disclosure_id == original.id
    assert current.message_id_boundary == original.message_id_boundary
    assert current.origin_scene_ts == original.origin_scene_ts
    assert scene.world_state.facts["offscreen-life"] == offscreen
    summarizer.rebuild_supported_facts.assert_awaited_once()
    messages = [call.args[0] for call in websocket.queue_put.call_args_list]
    assert any(message["action"] == "entry_briefing_indexed" for message in messages)
    assert all(
        message.get("request_id") == "regen-1"
        for message in messages
        if message["action"] in {"character_knowledge", "entry_briefing_indexed"}
    )


@pytest.mark.asyncio
async def test_regenerate_old_disclosure_rebuilds_over_unbound_newer_window(
    perspectives_entry_scene, monkeypatch
):
    scene, conversation, alice = perspectives_entry_scene
    original = await generate_on_entry(scene, conversation, alice)
    original_window = entry_windows(conversation)[alice.name].model_copy(deep=True)
    for _ in range(conversation.knowledge_character_entry_turns):
        consume_entry_turn(conversation, alice.name)

    later = NarratorMessage("The room changes before another entry.", present=["Alice"])
    scene.history.append(later)
    set_source_perspectives(
        scene,
        "message",
        later.id,
        [{"audience": ["Alice"], "status": "ready", "text": str(later)}],
    )
    scene.ts = 900
    newer = start_entry_window(conversation, alice)
    assert newer.boundary_message_id == later.id
    assert newer.briefing_disclosure_id is None

    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)
    monkeypatch.setattr(
        get_agent("summarizer"),
        "rebuild_supported_facts",
        AsyncMock(return_value=None),
    )

    async def request_from_original_boundary(*args, **kwargs):
        assert "The room changes before another entry" in kwargs["vars"]["arrival"]
        return "", {"briefing": "I reconstruct my earlier arrival.", "offscreen": None}

    with patch.object(
        Prompt,
        "request",
        new_callable=AsyncMock,
        side_effect=request_from_original_boundary,
    ):
        task = await plugin.handle_regenerate_entry_briefing(
            {
                "name": "Alice",
                "disclosure_id": original.id,
                "request_id": "regen-old-entry",
            }
        )
        await task

    restarted = entry_windows(conversation)[alice.name]
    assert restarted.boundary_message_id == original_window.boundary_message_id
    assert restarted.entry_scene_time == original_window.entry_scene_time
    assert restarted.briefing_disclosure_id == original.id


@pytest.mark.asyncio
async def test_regenerate_after_expiry_restores_fixed_away_duration(
    perspectives_entry_scene, monkeypatch
):
    scene, conversation, alice = perspectives_entry_scene
    scene.archived_history = [
        {"id": "a1", "text": "Alice was present.", "ts": 100, "present": ["Alice"]},
        {"id": "a2", "text": "Alice was away.", "ts": 1000, "present": ["Bob"]},
    ]
    scene.ts = 173800
    original = await generate_on_entry(scene, conversation, alice)
    assert original.away_scene_ts == 1000
    for _ in range(conversation.knowledge_character_entry_turns):
        consume_entry_turn(conversation, alice.name)
    scene.ts += 86400

    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)
    monkeypatch.setattr(
        get_agent("summarizer"),
        "rebuild_supported_facts",
        AsyncMock(return_value=None),
    )

    async def request_with_fixed_away_time(*args, **kwargs):
        assert "Time away before entry: 2 Days" in kwargs["vars"]["arrival"]
        assert "Time away before entry: 3 Days" not in kwargs["vars"]["arrival"]
        return "", {
            "briefing": "I remember returning two days later.",
            "offscreen": None,
        }

    with patch.object(
        Prompt,
        "request",
        new_callable=AsyncMock,
        side_effect=request_with_fixed_away_time,
    ):
        task = await plugin.handle_regenerate_entry_briefing(
            {
                "name": "Alice",
                "disclosure_id": original.id,
                "request_id": "regen-away",
            }
        )
        await task

    restarted = entry_windows(conversation)[alice.name]
    assert restarted.away_scene_time == 1000
    assert scene.knowledge.disclosures[0].away_scene_ts == 1000


@pytest.mark.asyncio
async def test_regenerate_reports_generation_cancelled_to_panel(
    perspectives_entry_scene,
):
    scene, conversation, alice = perspectives_entry_scene
    original = await generate_on_entry(scene, conversation, alice)
    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)

    with patch.object(
        conversation,
        "generate_entry_briefing",
        new_callable=AsyncMock,
        side_effect=GenerationCancelled("Perception is pending"),
    ):
        task = await plugin.handle_regenerate_entry_briefing(
            {
                "name": "Alice",
                "disclosure_id": original.id,
                "request_id": "regen-pending",
            }
        )
        await task

    failure = next(
        call.args[0]
        for call in websocket.queue_put.call_args_list
        if call.args[0].get("failed_action") == "regenerate_entry_briefing"
    )
    assert failure["request_id"] == "regen-pending"


@pytest.mark.asyncio
async def test_remove_reveals_fallback_only_while_original_window_remains(
    perspectives_entry_scene,
):
    scene, conversation, alice = perspectives_entry_scene
    disclosure = await generate_on_entry(scene, conversation, alice)
    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)

    await plugin.handle_remove_entry_briefing(
        {
            "name": "Alice",
            "disclosure_id": disclosure.id,
            "request_id": "remove-1",
        }
    )

    assert scene.knowledge.disclosures == ()
    assert "Character entry orientation" in conversation.character_entry_context(alice)
    for _ in range(conversation.knowledge_character_entry_turns):
        consume_entry_turn(conversation, alice.name)
    assert conversation.character_entry_context(alice) is None
    messages = [call.args[0] for call in websocket.queue_put.call_args_list]
    knowledge = next(
        message for message in messages if message["action"] == "character_knowledge"
    )
    assert knowledge["request_id"] == "remove-1"


@pytest.mark.asyncio
async def test_failed_regenerate_removes_stale_briefing_and_keeps_fallback(
    perspectives_entry_scene,
):
    scene, conversation, alice = perspectives_entry_scene
    disclosure = await generate_on_entry(scene, conversation, alice)
    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)

    with patch.object(Prompt, "request", new_callable=AsyncMock) as request:
        request.return_value = ("", {"briefing": None, "offscreen": None})
        task = await plugin.handle_regenerate_entry_briefing(
            {
                "name": "Alice",
                "disclosure_id": disclosure.id,
                "request_id": "regen-failed",
            }
        )
        await task

    request.assert_awaited_once()
    assert scene.knowledge.disclosures == ()
    assert "Character entry orientation" in conversation.character_entry_context(alice)
    messages = [call.args[0] for call in websocket.queue_put.call_args_list]
    failure = next(
        message
        for message in messages
        if message.get("failed_action") == "regenerate_entry_briefing"
    )
    assert failure["request_id"] == "regen-failed"
    failure_index = messages.index(failure)
    refresh_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("action") == "character_knowledge"
    )
    assert failure_index < refresh_index


@pytest.mark.asyncio
async def test_old_disclosure_is_not_reused_or_deleted_by_failed_reentry(
    perspectives_entry_scene,
):
    scene, conversation, alice = perspectives_entry_scene
    original = await generate_on_entry(scene, conversation, alice)
    for _ in range(conversation.knowledge_character_entry_turns):
        consume_entry_turn(conversation, alice.name)
    assert alice.name not in entry_windows(conversation)

    with patch.object(Prompt, "request", new_callable=AsyncMock) as request:
        request.return_value = ("", {"briefing": None, "offscreen": None})
        await conversation.on_character_activated(activation(scene, alice))

    assert scene.knowledge.disclosures == (original,)
    window = entry_windows(conversation)[alice.name]
    assert window.briefing_disclosure_id is None
    rendered = conversation.character_entry_context(alice)
    assert "Character entry orientation" in rendered
    assert original.text not in rendered


@pytest.mark.asyncio
async def test_new_window_does_not_render_previous_disclosure_when_briefing_disabled(
    perspectives_entry_scene,
):
    scene, conversation, alice = perspectives_entry_scene
    original = await generate_on_entry(scene, conversation, alice)
    for _ in range(conversation.knowledge_character_entry_turns):
        consume_entry_turn(conversation, alice.name)
    conversation.actions["character_knowledge"].config[
        "brief_characters_on_entry"
    ].value = False

    await conversation.on_character_activated(activation(scene, alice))

    assert scene.knowledge.disclosures == (original,)
    rendered = conversation.character_entry_context(alice)
    assert "Character entry orientation" in rendered
    assert original.text not in rendered


@pytest.mark.asyncio
async def test_successful_reentry_rebinds_disclosure_to_new_boundary(
    perspectives_entry_scene,
):
    scene, conversation, alice = perspectives_entry_scene
    original = await generate_on_entry(scene, conversation, alice)
    for _ in range(conversation.knowledge_character_entry_turns):
        consume_entry_turn(conversation, alice.name)
    scene.ts = 300
    boundary = NarratorMessage("A new arrival moment.", present=["Alice"])
    scene.history.append(boundary)
    set_source_perspectives(
        scene,
        "message",
        boundary.id,
        [{"audience": ["Alice"], "status": "ready", "text": str(boundary)}],
    )

    current = await generate_on_entry(
        scene, conversation, alice, text="I take in the changed room."
    )

    assert current.id == original.id
    assert current.message_id_boundary == boundary.id
    assert current.origin_scene_ts == 300
    window = entry_windows(conversation)[alice.name]
    assert window.boundary_message_id == boundary.id
    assert window.briefing_disclosure_id == current.id


@pytest.mark.asyncio
async def test_controls_reject_another_character_or_non_entry_disclosure(
    perspectives_entry_scene,
):
    scene, conversation, alice = perspectives_entry_scene
    disclosure = await generate_on_entry(scene, conversation, alice)
    bob = Character(name="Bob")
    scene.character_data[bob.name] = bob
    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)

    await plugin.handle_remove_entry_briefing(
        {"name": "Bob", "disclosure_id": disclosure.id, "request_id": "bad-1"}
    )

    assert scene.knowledge.disclosures == (disclosure,)
    failure = websocket.queue_put.call_args.args[0]
    assert failure["failed_action"] == "remove_entry_briefing"
    assert failure["request_id"] == "bad-1"
