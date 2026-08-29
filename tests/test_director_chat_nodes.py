"""Unit tests for talemate.agents.director.chat.nodes.InsertChatMessage.

Regression coverage for issue #129: after the multi-chat refactor,
`DirectorMixin.chat_create()` always creates a NEW chat. InsertChatMessage
kept calling it unconditionally, so messages produced by async director
actions (e.g. a completed `create_image` generation) landed in a fresh
orphan chat the user was not viewing - the image never appeared in the
director chat.

The node must resolve the target chat via the active DirectorChatContext
(the chat that initiated the action) and only fall back to the active
chat / creation as a last resort.
"""

from __future__ import annotations

import pytest

from conftest import MockScene, bootstrap_scene
from _node_test_helpers import run_node

from talemate.agents.director.chat.context import (
    DirectorChatContext,
    director_chat_context,
)
from talemate.agents.director.chat.nodes import InsertChatMessage
from talemate.agents.director.chat.settings import ChatModeSettings
from talemate.game.engine.nodes.registry import import_talemate_node_definitions
from talemate.instance import get_agent


@pytest.fixture(scope="session", autouse=True)
def _import_node_definitions():
    import_talemate_node_definitions()


@pytest.fixture
def scene():
    """Real Scene with bootstrapped agents (mock memory + mock client)."""
    s = MockScene()
    bootstrap_scene(s)
    return s


@pytest.fixture
def director(scene):
    return get_agent("director")


async def _run_node(
    node,
    scene,
    *,
    inputs: dict | None = None,
    chat_ctx: DirectorChatContext | None = None,
) -> dict:
    """Wrap the shared run_node helper with optional director chat context."""
    token = None
    if chat_ctx is not None:
        token = director_chat_context.set(chat_ctx)
    try:
        return await run_node(node, scene=scene, inputs=inputs)
    finally:
        if token is not None:
            director_chat_context.reset(token)


def _chat_ctx(chat_id: str) -> DirectorChatContext:
    return DirectorChatContext(chat_id=chat_id, modes=ChatModeSettings())


class TestInsertChatMessageChatResolution:
    @pytest.mark.asyncio
    async def test_inserts_into_context_chat_not_active_chat(self, scene, director):
        """The message must land in the chat that initiated the action,
        even when another chat is currently marked active."""
        active_chat = director.chat_create()
        context_chat = director.chat_create()
        # chat_create sets last-active to the most recent; force the other
        # chat active so the two resolution targets diverge.
        director.chat_set_last_active_id(active_chat.id)

        chat_count_before = len(director.chat_get_all_chats())

        node = InsertChatMessage()
        out = await _run_node(
            node,
            scene,
            inputs={"message": "Image Generated.", "source": "director"},
            chat_ctx=_chat_ctx(context_chat.id),
        )

        # no new chat must have been created
        assert len(director.chat_get_all_chats()) == chat_count_before

        context_chat_after = director.chat_get(context_chat.id)
        active_chat_after = director.chat_get(active_chat.id)

        assert context_chat_after.messages[-1].message == "Image Generated."
        assert active_chat_after.messages[-1].message != "Image Generated."
        assert out["message"] == "Image Generated."
        assert out["source"] == "director"

    @pytest.mark.asyncio
    async def test_falls_back_to_active_chat_without_context(self, scene, director):
        """Without a chat context the active chat receives the message and
        no orphan chat is created."""
        chat = director.chat_create()
        chat_count_before = len(director.chat_get_all_chats())

        node = InsertChatMessage()
        await _run_node(
            node,
            scene,
            inputs={"message": "hello", "source": "director"},
        )

        assert len(director.chat_get_all_chats()) == chat_count_before
        chat_after = director.chat_get(chat.id)
        assert chat_after.messages[-1].message == "hello"

    @pytest.mark.asyncio
    async def test_falls_back_when_context_chat_was_deleted(self, scene, director):
        """A stale context chat id must not lose the message - it goes to
        the active chat instead."""
        chat = director.chat_create()
        chat_count_before = len(director.chat_get_all_chats())

        node = InsertChatMessage()
        await _run_node(
            node,
            scene,
            inputs={"message": "recovered", "source": "director"},
            chat_ctx=_chat_ctx("no-such-chat-id"),
        )

        assert len(director.chat_get_all_chats()) == chat_count_before
        chat_after = director.chat_get(chat.id)
        assert chat_after.messages[-1].message == "recovered"

    @pytest.mark.asyncio
    async def test_creates_chat_only_when_none_exists(self, scene, director):
        """With no chats at all, one is created as a last resort."""
        assert director.chat_get_all_chats() == {}

        node = InsertChatMessage()
        await _run_node(
            node,
            scene,
            inputs={"message": "first", "source": "director"},
        )

        chats = director.chat_get_all_chats()
        assert len(chats) == 1
        chat = director.chat_get(next(iter(chats)))
        assert chat.messages[-1].message == "first"

    @pytest.mark.asyncio
    async def test_asset_message_inserted_as_asset_view(
        self, scene, director, monkeypatch
    ):
        """An asset_id produces an asset_view message in the context chat."""
        chat = director.chat_create()

        monkeypatch.setattr(
            type(scene.assets), "validate_asset_id", lambda self, aid: True
        )

        node = InsertChatMessage()
        out = await _run_node(
            node,
            scene,
            inputs={
                "message": "Image Generated.",
                "source": "director",
                "asset_id": "director_abc123",
            },
            chat_ctx=_chat_ctx(chat.id),
        )

        chat_after = director.chat_get(chat.id)
        message = chat_after.messages[-1]
        assert message.type == "asset_view"
        assert message.asset_id == "director_abc123"
        assert out["asset_id"] == "director_abc123"

    @pytest.mark.asyncio
    async def test_unknown_asset_id_raises(self, scene, director, monkeypatch):
        """An asset id that does not validate still raises."""
        director.chat_create()

        monkeypatch.setattr(
            type(scene.assets), "validate_asset_id", lambda self, aid: False
        )

        node = InsertChatMessage()
        with pytest.raises(ValueError, match="Asset not found"):
            await _run_node(
                node,
                scene,
                inputs={
                    "message": "Image Generated.",
                    "source": "director",
                    "asset_id": "missing_asset",
                },
            )
