import asyncio
from types import SimpleNamespace

import pytest

from talemate.agents.base import background_processing, set_processing
from talemate.agents.context import active_agent
from talemate.character import Character
from talemate.client.context import ClientContext, client_context_attribute
from talemate.config import get_config
from talemate.config.schema import AgentActionOverride
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent


@pytest.fixture
def conversation(scene, monkeypatch):
    agent = get_agent("conversation")
    agent.processing = 0
    monkeypatch.setattr(scene, "context_history", lambda **kwargs: [])
    return agent


@pytest.mark.parametrize(
    "failure", [None, RuntimeError, GenerationCancelled, asyncio.CancelledError]
)
async def test_memory_pass_owns_context_and_restores_outer_action(
    scene, conversation, monkeypatch, failure
):
    alice = Character(name="Alice")
    scene.character_data = {"Alice": alice}
    scene.active_characters = ["Alice"]
    config = get_config()
    monkeypatch.setitem(
        config.agent_actions.overrides,
        "conversation.memory_pass",
        AgentActionOverride(disable_reasoning=True),
    )
    seen = []

    async def request(*args, **kwargs):
        seen.append(
            (active_agent.get().action, client_context_attribute("disable_reasoning"))
        )
        assert active_agent.get().previous.action == "converse"
        assert conversation.processing == 2
        assert conversation.meta["current_action"] == "memory_pass"
        if failure:
            raise failure("request failed")
        return "", {"none": "<NONE/>", "items": []}

    monkeypatch.setattr(
        "talemate.agents.conversation.knowledge.Prompt.request", request
    )

    @set_processing
    async def converse(self):
        try:
            return await self.memory_pass(alice, ["A memory."])
        finally:
            assert self.processing == 1
            assert self.status == "busy"
            assert self.meta["current_action"] == "converse"
            assert active_agent.get().action == "converse"
            assert client_context_attribute("disable_reasoning") is False

    with ActiveScene(scene), ClientContext(disable_reasoning=False):
        if failure:
            with pytest.raises(failure):
                await converse(conversation)
        else:
            assert await converse(conversation) == []
    assert seen == [("memory_pass", True)]
    assert conversation.processing == 0
    assert conversation._current_action is None
    assert conversation._processing_actions == {}


@pytest.mark.parametrize("finish_first", [0, 1])
async def test_concurrent_actions_restore_only_still_running_actions(
    conversation, finish_first
):
    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]

    @set_processing
    async def first(self):
        entered[0].set()
        await release[0].wait()

    @set_processing
    async def second(self):
        entered[1].set()
        await release[1].wait()

    tasks = []
    async with asyncio.timeout(3):
        try:
            for index, fn in enumerate((first, second)):
                tasks.append(asyncio.create_task(fn(conversation)))
                await entered[index].wait()
            assert conversation.processing == 2
            assert conversation._current_action == "second"
            release[finish_first].set()
            await tasks[finish_first]
            assert conversation.processing == 1
            assert conversation._current_action == (
                "second" if finish_first == 0 else "first"
            )
            release[1 - finish_first].set()
            await tasks[1 - finish_first]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert conversation.processing == 0
    assert conversation._current_action is None


async def test_background_nested_action_does_not_replace_foreground_status(
    conversation, monkeypatch
):
    emitted = []

    async def emit():
        emitted.append((conversation.processing, conversation._current_action))

    monkeypatch.setattr(conversation, "_do_emit_status", emit)

    @set_processing
    async def background(self):
        assert active_agent.get().action == "background"
        assert self._current_action == "foreground"
        assert self.processing == 1

    @set_processing
    async def foreground(self):
        token = background_processing.set(True)
        try:
            await background(self)
        finally:
            background_processing.reset(token)
        assert self._current_action == "foreground"
        assert self.processing == 1

    await foreground(conversation)
    if conversation._emit_status_debounce_task:
        await conversation._emit_status_debounce_task
    assert emitted == [(1, "foreground"), (0, None)]


@pytest.mark.parametrize("agent_name", ["director", "help"])
async def test_title_generation_owns_action_without_changing_title(
    scene, monkeypatch, agent_name
):
    agent = get_agent(agent_name)
    chat = SimpleNamespace(id="title-test")

    monkeypatch.setattr(agent, "chat_get", lambda chat_id: SimpleNamespace(messages=[]))
    update = []
    monkeypatch.setattr(agent, "chat_update_title", lambda *args: update.append(args))

    async def title(*args, **kwargs):
        assert active_agent.get().action == "chat_generate_title"
        assert active_agent.get().agent is agent
        return "The bell"

    module = (
        "talemate.agents.director.chat.mixin"
        if agent_name == "director"
        else "talemate.agents.help.chat"
    )
    monkeypatch.setattr(f"{module}.generate_chat_title", title)
    with ActiveScene(scene):
        assert await agent.chat_generate_title(chat.id) == "The bell"
    assert update == [(chat.id, "The bell")]
