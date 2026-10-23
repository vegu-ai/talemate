"""Unit tests for the conversation websocket handler.

Covers ``handle_request_actor_action``'s unbound-actor path (no character in
the payload): an NPC-less scene must be refused with an error status instead
of raising out of ``random.choice`` on an empty list, and a scene with NPCs
must still pick one and generate.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from conftest import MockScene, bootstrap_scene
from _director_test_helpers import add_character_to_scene

from talemate.agents.conversation.websocket_handler import ConversationWebsocketHandler
from talemate.context import ActiveScene


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def player_only_scene():
    """Bootstrapped scene whose only actor is the player."""
    scene = MockScene()
    bootstrap_scene(scene)

    await add_character_to_scene(scene, "Bob", is_player=True, description="Player.")

    with ActiveScene(scene):
        yield scene


@pytest.fixture
async def npc_scene(player_only_scene):
    """The player-only scene with a single NPC added."""
    await add_character_to_scene(
        player_only_scene, "Alice", description="Test character."
    )
    return player_only_scene


def _handler(scene) -> ConversationWebsocketHandler:
    ws = SimpleNamespace(scene=scene, queue_put=Mock())
    return ConversationWebsocketHandler(websocket_handler=ws)


# ---------------------------------------------------------------------------
# handle_request_actor_action - unbound actor
# ---------------------------------------------------------------------------


class TestRequestActorActionWithoutCharacter:
    async def test_no_npcs_is_refused(self, player_only_scene):
        handler = _handler(player_only_scene)

        with patch.object(
            type(handler.agent), "converse", autospec=True
        ) as mock_converse:
            task = await handler.handle_request_actor_action(
                {"character": "", "instructions": "Say something"}
            )
            await task

        mock_converse.assert_not_called()

        (payload,) = [
            call.args[0] for call in handler.websocket_handler.queue_put.call_args_list
        ]
        assert payload["type"] == "conversation"
        assert payload["action"] == "operation_done"
        assert payload["error"]["message"] == "No NPCs in the scene — nothing to direct"

    async def test_npc_is_picked(self, npc_scene):
        handler = _handler(npc_scene)

        with patch.object(
            type(handler.agent), "converse", autospec=True, return_value=[]
        ) as mock_converse:
            task = await handler.handle_request_actor_action(
                {
                    "character": "",
                    "instructions": "Say something",
                    "instructions_through_director": False,
                }
            )
            await task

        actor = mock_converse.await_args.args[1]
        assert actor.character.name == "Alice"
        assert mock_converse.await_args.kwargs["instruction"] == "Say something"
        handler.websocket_handler.queue_put.assert_not_called()
