"""Tests for optional generated character-entry briefings."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from talemate.agents.conversation.entry_context import entry_briefings, entry_windows
from talemate.agents.conversation.response_specs import ENTRY_BRIEFING_SPEC
from talemate.character import Character
from talemate.context import ActiveScene, SceneIsLoading
from talemate.events import CharacterActivatedEvent
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.tale_mate import Actor, Player


@pytest.fixture
def briefing_scene(scene):
    conversation = get_agent("conversation")
    alice = Character(name="Alice", description="Alice is an observant courier.")
    bob = Character(name="Bob", is_player=True)
    for character, actor_type, agent in (
        (alice, Actor, conversation),
        (bob, Player, None),
    ):
        actor = actor_type(character, agent)
        actor.scene = scene
        scene.actors.append(actor)
        scene.active_characters.append(character.name)
        scene.character_data[character.name] = character
    scene.context_history = Mock(return_value=["Alice: I remember the old harbor."])
    conversation.absence_block = AsyncMock(
        return_value=["The changed vault code is unknown to Alice."]
    )
    scene.description = "READER-ONLY SCENE DESCRIPTION"
    with ActiveScene(scene):
        yield scene, conversation, alice, bob


def activation(scene, character):
    return CharacterActivatedEvent(
        scene=scene,
        character=character,
        event_type="character.activated",
    )


class TestEntryBriefing:
    def test_off_by_default(self, briefing_scene):
        _, conversation, _, _ = briefing_scene
        config = conversation.actions["character_knowledge"].config
        assert config["brief_characters_on_entry"].value is False

    @pytest.mark.asyncio
    async def test_npc_briefing_uses_one_scoped_request_and_replaces_block(
        self, briefing_scene
    ):
        scene, conversation, alice, _ = briefing_scene
        conversation.actions["character_knowledge"].config[
            "brief_characters_on_entry"
        ].value = True
        conversation.actions["character_knowledge"].config[
            "perspective_filter"
        ].value = False
        with patch.object(Prompt, "request", new_callable=AsyncMock) as request:
            request.return_value = (
                "",
                {
                    "briefing": "I take in Bob and the familiar harbor around me.",
                    "offscreen": None,
                },
            )
            await conversation.on_character_activated(activation(scene, alice))

        request.assert_awaited_once()
        assert request.call_args.args[0] == "conversation.character-entry-briefing"
        variables = request.call_args.kwargs["vars"]
        assert "scene" not in variables
        assert "READER-ONLY SCENE DESCRIPTION" not in variables["arrival"]
        assert variables["perceived_history"] == ["Alice: I remember the old harbor."]
        assert scene.context_history.call_args.kwargs == {
            "budget": int(scene.mock_client.max_token_length * 0.35),
            "perspective": "Alice",
            "keep_director": False,
        }
        assert variables["unknown_fact_reminders"] == [
            "The changed vault code is unknown to Alice."
        ]
        assert entry_briefings(conversation)["Alice"].startswith("I take in Bob")
        assert scene.agent_state["conversation"]["character_entry_briefings"] == {
            "Alice": "I take in Bob and the familiar harbor around me."
        }
        rendered = conversation.character_entry_context(alice)
        assert "Character entry briefing" in rendered
        assert "I take in Bob" in rendered
        assert "Known facts about characters present now" not in rendered

    @pytest.mark.asyncio
    async def test_player_gets_zero_request_orientation_only(self, briefing_scene):
        scene, conversation, _, bob = briefing_scene
        conversation.actions["character_knowledge"].config[
            "brief_characters_on_entry"
        ].value = True
        with patch.object(Prompt, "request", new_callable=AsyncMock) as request:
            await conversation.on_character_activated(activation(scene, bob))

        request.assert_not_awaited()
        assert "Bob" in entry_windows(conversation)
        assert "Bob" not in entry_briefings(conversation)
        assert "Character entry orientation" in conversation.character_entry_context(
            bob
        )

    @pytest.mark.asyncio
    async def test_perspectives_mode_uses_stored_character_history(
        self, briefing_scene
    ):
        scene, conversation, alice, _ = briefing_scene
        scene.knowledge_eligibility = "perception"
        conversation.actions["character_knowledge"].config[
            "brief_characters_on_entry"
        ].value = True
        conversation.history_context = AsyncMock(
            return_value=["Alice's stored perception of the harbor."]
        )
        with patch.object(Prompt, "request", new_callable=AsyncMock) as request:
            request.return_value = (
                "",
                {"briefing": "I know this harbor.", "offscreen": None},
            )
            await conversation.on_character_activated(activation(scene, alice))

        conversation.history_context.assert_awaited_once_with(
            alice,
            budget=int(scene.mock_client.max_token_length * 0.35),
            keep_director=False,
        )
        scene.context_history.assert_not_called()
        assert request.call_args.kwargs["vars"]["perceived_history"] == [
            "Alice's stored perception of the harbor."
        ]

    @pytest.mark.asyncio
    async def test_pending_perception_does_not_escape_activation_signal(
        self, briefing_scene
    ):
        scene, conversation, alice, _ = briefing_scene
        scene.knowledge_eligibility = "perception"
        conversation.actions["character_knowledge"].config[
            "brief_characters_on_entry"
        ].value = True
        conversation.history_context = AsyncMock(
            side_effect=GenerationCancelled("Perception is pending")
        )
        with (
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
            patch("talemate.agents.conversation.knowledge.emit") as emit,
        ):
            result = await conversation.on_character_activated(activation(scene, alice))

        assert result is None
        request.assert_not_awaited()
        assert "Alice" in entry_windows(conversation)
        emit.assert_called_once_with(
            "status",
            status="error",
            message="Character entry briefing for Alice failed.",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", ["unreadable", "cancelled"])
    async def test_failure_keeps_zero_request_fallback_and_stores_nothing(
        self, briefing_scene, failure
    ):
        scene, conversation, alice, _ = briefing_scene
        conversation.actions["character_knowledge"].config[
            "brief_characters_on_entry"
        ].value = True
        with (
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
            patch("talemate.agents.conversation.knowledge.emit") as emit,
        ):
            if failure == "cancelled":
                request.side_effect = GenerationCancelled("cancelled")
            else:
                request.return_value = ("", {"briefing": None, "offscreen": None})
            assert (
                await conversation.on_character_activated(activation(scene, alice))
                is None
            )

        assert "Alice" in entry_windows(conversation)
        assert "Alice" not in entry_briefings(conversation)
        assert "Character entry orientation" in conversation.character_entry_context(
            alice
        )
        emit.assert_called_once_with(
            "status",
            status="error",
            message="Character entry briefing for Alice failed.",
        )
        assert scene.world_state.facts == {}

    @pytest.mark.asyncio
    async def test_scene_load_starts_neither_window_nor_request(self, briefing_scene):
        scene, conversation, alice, _ = briefing_scene
        conversation.actions["character_knowledge"].config[
            "brief_characters_on_entry"
        ].value = True
        with (
            SceneIsLoading(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            await conversation.on_character_activated(activation(scene, alice))

        assert entry_windows(conversation) == {}
        request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_analysis_client_uses_fallback_without_raising(
        self, briefing_scene
    ):
        scene, conversation, alice, _ = briefing_scene
        conversation.actions["character_knowledge"].config[
            "brief_characters_on_entry"
        ].value = True
        world_state = get_agent("world_state")
        world_state.client = None
        with patch("talemate.agents.conversation.knowledge.emit") as emit:
            assert (
                await conversation.on_character_activated(activation(scene, alice))
                is None
            )

        assert "Alice" in entry_windows(conversation)
        assert "Alice" not in entry_briefings(conversation)
        emit.assert_called_once()


def test_entry_briefing_response_spec_extracts_combined_result():
    extracted = ENTRY_BRIEFING_SPEC.extract_all(
        "<BRIEFING>I scan the room.</BRIEFING>"
        "<OFFSCREEN>I traded along the coast.</OFFSCREEN>"
    )
    assert extracted == {
        "briefing": "I scan the room.",
        "offscreen": "I traded along the coast.",
    }


@pytest.mark.parametrize(
    "response,missing",
    [
        (
            "<BRIEFING>I scan the room.<OFFSCREEN>I sailed.</OFFSCREEN>",
            "briefing",
        ),
        (
            "<BRIEFING>I scan the room.</BRIEFING>I sailed.</OFFSCREEN>",
            "offscreen",
        ),
        (
            "<BRIEFING>I scan the room.</BRIEFING><OFFSCREEN>I sai",
            "offscreen",
        ),
    ],
)
def test_entry_briefing_response_spec_rejects_incomplete_sections(response, missing):
    extracted = ENTRY_BRIEFING_SPEC.extract_all(response)
    assert extracted[missing] is None


@pytest.mark.parametrize(
    "response,unreadable",
    [
        (
            "<BRIEFING>I see Alice.<OFFSCREEN>I sailed.</BRIEFING></OFFSCREEN>",
            {"briefing", "offscreen"},
        ),
        (
            "<BRIEFING>I see Alice.<OFFSCREEN>I sailed.</OFFSCREEN></BRIEFING>",
            {"briefing"},
        ),
        (
            "<OFFSCREEN>I sailed.<BRIEFING>I see Alice.</BRIEFING></OFFSCREEN>",
            {"offscreen"},
        ),
    ],
)
def test_entry_briefing_response_spec_rejects_crossed_or_nested_sections(
    response, unreadable
):
    extracted = ENTRY_BRIEFING_SPEC.extract_all(response)
    assert {name for name, value in extracted.items() if value is None} == unreadable
