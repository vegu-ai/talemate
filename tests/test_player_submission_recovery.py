import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import test_player_submission
from talemate.emit.async_signals import AsyncSignal
from talemate.game.engine.nodes.core import Listen
from talemate.agents.conversation.entry_context import (
    CharacterEntryWindow,
    entry_windows,
    save_entry_windows,
)
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.revision_refresh import (
    catch_up_revisions,
    revision_requires_refresh,
)
from talemate.load import load_scene_from_data
from talemate.scene_message import CharacterMessage
from talemate.server.scene_message import SceneMessagePlugin

submission = test_player_submission.submission


@pytest.mark.asyncio
async def test_distinct_node_listener_checkpoints_survive_reinstantiation(monkeypatch):
    completed, calls = [], []

    async def execute(self, event):
        calls.append(self.id)
        if self.id == "second" and calls.count("second") == 1:
            raise GenerationCancelled("second listener interrupted")

    monkeypatch.setattr(Listen, "execute_from_event", execute)
    signal = AsyncSignal("game_loop_new_message")
    first, second = Listen(id="first"), Listen(id="second")
    signal.connect(first.execute_from_event)
    signal.connect(second.execute_from_event)
    with pytest.raises(GenerationCancelled):
        await signal.send(None, completed=completed)
    restored = json.loads(json.dumps(completed))
    signal.receivers.clear()
    signal.connect(Listen(id="first").execute_from_event)
    signal.connect(Listen(id="second").execute_from_event)
    await signal.send(None, completed=restored)
    assert calls == ["first", "second", "second"]


@pytest.mark.asyncio
async def test_edited_pending_submission_is_ready_at_conversation_prompt(
    submission, monkeypatch
):
    t = submission
    t.summarizer.summarize.side_effect = GenerationCancelled("older refresh cancelled")
    message = CharacterMessage(message="Alice: I take the key.", source="player")
    with pytest.raises(GenerationCancelled):
        await t.scene.push_history(message, emit_message=True)
    plugin = SceneMessagePlugin(
        SimpleNamespace(scene=t.scene, queue_put=lambda frame: None)
    )
    await plugin.handle_edit({"id": message.id, "text": "Alice: I take the ruby key."})
    assert message.history_dispatch_pending
    assert revision_requires_refresh(t.scene, message)
    conversation = get_agent("conversation")
    assert not conversation.knowledge_ledger
    t.summarizer.summarize.side_effect = None
    t.summarizer.summarize.return_value = ("The key is ruby.", [])
    prompts = []

    async def build_prompt(*args, **kwargs):
        assert not revision_requires_refresh(t.scene, message)
        assert not message.history_dispatch_pending
        prompts.append(message.id)
        raise GenerationCancelled("prompt boundary reached")

    monkeypatch.setattr(conversation, "build_prompt", build_prompt)
    with pytest.raises(GenerationCancelled, match="prompt boundary reached"):
        await conversation.converse(t.scene.get_character("Bob").actor)
    assert prompts == [message.id]
    assert t.summarizer.summarize.await_count == 3
    await catch_up_revisions(t.scene)
    assert t.summarizer.summarize.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.parametrize(
    "failure", [GenerationCancelled, asyncio.CancelledError, RuntimeError]
)
@pytest.mark.parametrize("boundary", ["archive", "tts", "learning"])
async def test_archive_retry_preserves_completed_real_listeners(
    submission,
    monkeypatch,
    persistence_scene_factory,
    isolate_signals,
    reload,
    failure,
    boundary,
):
    t = submission
    t.release.set()
    await catch_up_revisions(t.scene)
    calls = []
    archive_attempts = []
    tts_attempts = []
    learning_attempts = []

    async def summarize(*args, **kwargs):
        archive_attempts.append(args[0])
        if boundary == "archive" and len(archive_attempts) == 1:
            raise failure("dispatch interrupted")
        return "The old key is silver.", []

    def connect(scene):
        conversation = get_agent("conversation")
        conversation.write_enabled("character_knowledge", boundary == "learning")
        conversation.write_config(
            "character_knowledge", "ledger", boundary == "learning"
        )

        async def learn(*args, **kwargs):
            learning_attempts.append(kwargs["message"].id)
            if len(learning_attempts) == 1:
                raise failure("dispatch interrupted")
            return {}

        monkeypatch.setattr(conversation, "record_learned_facts", learn)
        summarizer = get_agent("summarizer")
        summarizer.write_enabled("archive", True)
        summarizer.write_config("archive", "threshold", 1)
        monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=summarize))
        monkeypatch.setattr(summarizer, "analyze_dialoge", AsyncMock(return_value=None))
        monkeypatch.setattr(conversation, "finalize_message_avatar", AsyncMock())
        tts = get_agent("tts")
        monkeypatch.setattr(type(tts), "enabled", property(lambda self: True))
        monkeypatch.setattr(type(tts), "ready", property(lambda self: True))
        monkeypatch.setattr(
            type(tts), "generate_for_player", property(lambda self: True)
        )

        async def generate(text, **kwargs):
            tts_attempts.append(kwargs["message"].id)
            if boundary == "tts" and len(tts_attempts) == 1:
                raise failure("dispatch interrupted")
            calls.append(kwargs["message"].id)

        monkeypatch.setattr(tts, "generate", generate)
        isolate_signals("push_history", "push_history.after", "game_loop_new_message")
        scene.signals["game_loop_new_message"].connect(conversation.on_new_message)
        scene.signals["game_loop_new_message"].connect(tts.on_game_loop_new_message)
        scene.signals["push_history.after"].connect(summarizer.on_push_history)
        return conversation

    conversation = connect(t.scene)
    save_entry_windows(conversation, {"Bob": CharacterEntryWindow(remaining_turns=2)})
    message = CharacterMessage(message="Bob: I will keep the key.", source="player")
    with pytest.raises(failure, match="dispatch interrupted"):
        await t.scene.push_history(message, emit_message=True)
    assert calls == ([message.id] if boundary == "archive" else [])
    assert entry_windows(conversation)["Bob"].remaining_turns == 1
    assert message.history_dispatch_pending
    saved = json.loads(t.saved.read_text())
    scene = t.scene
    if reload:
        scene = persistence_scene_factory()
        await load_scene_from_data(scene, saved, name=str(t.saved))
        conversation = connect(scene)
        message = scene.get_message(message.id)
        assert entry_windows(conversation)["Bob"].remaining_turns == 1
    with ActiveScene(scene):
        await catch_up_revisions(scene)
        await catch_up_revisions(scene)
    assert len(archive_attempts) == (2 if boundary == "archive" else 1)
    assert len(tts_attempts) == (2 if boundary == "tts" else 1)
    assert len(learning_attempts) == (2 if boundary == "learning" else 0)
    assert len(scene.archived_history) == 1
    assert calls == [message.id]
    assert entry_windows(conversation)["Bob"].remaining_turns == 1
    assert not message.history_dispatch_pending
    assert len([entry for entry in scene.history if entry.id == message.id]) == 1
    assert len([entry for entry in t.visible if entry[0] == message.id]) == 1
