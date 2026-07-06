"""
Tests for the help agent: documentation tools, chat CRUD + persistence,
call-block stripping and the focal-backed generation loop.
"""

import json

import pytest

import talemate.agents.help.storage as help_storage
import talemate.instance as instance
from talemate.agents.help import HelpAgent, docs
from talemate.agents.help.chat import INITIAL_MESSAGE
from talemate.agents.help.schema import HelpChatStore
from talemate.game.focal.util import strip_call_blocks

from conftest import MockClient, MockClientContext, bootstrap_engine, client_responses


class _ConcurrentMockClient(MockClient):
    """MockClient that opts in to concurrent inference."""

    @property
    def supports_concurrent_inference(self):
        return True


@pytest.fixture
def help_agent(tmp_path, monkeypatch):
    """A fresh HelpAgent persisting to a temporary chat store."""
    monkeypatch.setattr(help_storage, "HELP_CHATS_DIR", tmp_path)
    monkeypatch.setattr(help_storage, "HELP_CHATS_FILE", tmp_path / "help.json")
    agent = HelpAgent(client=MockClient("test_client"))
    agent.scene = None
    return agent


# ---------------------------------------------------------------------------
# Documentation tools
# ---------------------------------------------------------------------------


def test_docs_index_loads_and_paths_exist():
    index = docs.load_docs_index()
    assert len(index) > 100
    for entry in index:
        assert entry.keys() >= {"path", "title", "summary"}
        assert (docs.DOCS_DIR / entry["path"]).is_file(), entry["path"]


def test_search_docs_returns_matches():
    results = docs.search_docs("director")
    assert isinstance(results, list)
    assert results
    first = results[0]
    assert first.keys() == {"path", "line", "text"}
    assert (docs.DOCS_DIR / first["path"]).is_file()


def test_search_docs_no_matches_returns_hint():
    result = docs.search_docs("zzz-no-such-term-zzz")
    assert isinstance(result, str)
    assert "No matches" in result


def test_search_docs_invalid_regex_falls_back_to_literal():
    result = docs.search_docs("director (")
    # must not raise - falls back to literal matching
    assert isinstance(result, (list, str))


def test_doc_url():
    assert (
        docs.doc_url("user-guide/agents/editor/settings.md")
        == "https://vegu-ai.github.io/talemate/user-guide/agents/editor/settings/"
    )
    assert (
        docs.doc_url("user-guide/agents/help/index.md")
        == "https://vegu-ai.github.io/talemate/user-guide/agents/help/"
    )
    assert docs.doc_url("index.md") == "https://vegu-ai.github.io/talemate/"


def test_read_doc():
    result = docs.read_doc("index.md")
    assert isinstance(result, dict)
    assert result["path"] == "index.md"
    assert result["url"] == docs.DOCS_SITE_URL
    assert result["content"]


def test_read_doc_rejects_traversal_and_unknown():
    assert isinstance(docs.read_doc("../pyproject.toml"), str)
    assert isinstance(docs.read_doc("/etc/passwd"), str)
    assert isinstance(docs.read_doc("no/such/file.md"), str)


def test_read_doc_section():
    # index.md is guaranteed to have headings
    full = (docs.DOCS_DIR / "index.md").read_text()
    heading = next(
        line.lstrip("#").strip() for line in full.splitlines() if line.startswith("#")
    )
    result = docs.read_doc_section("index.md", heading)
    assert isinstance(result, dict)
    assert result["content"]


def test_read_doc_section_unknown_lists_available():
    result = docs.read_doc_section("index.md", "zzz-no-such-section-zzz")
    assert isinstance(result, dict)
    assert "error" in result
    assert isinstance(result["available_sections"], list)


# ---------------------------------------------------------------------------
# Call block stripping
# ---------------------------------------------------------------------------


def test_strip_call_blocks_removes_calls_keeps_code():
    call_block = json.dumps({"function": "search_docs", "arguments": {"query": "x"}})
    response = (
        "Let me look that up.\n"
        f"```json\n{call_block}\n```\n"
        "Meanwhile, here is an example:\n"
        "```yaml\nfoo: bar\n```\n"
        "Done."
    )
    stripped = strip_call_blocks(response, "json")
    assert "search_docs" not in stripped
    assert "foo: bar" in stripped
    assert "Let me look that up." in stripped


def test_strip_call_blocks_plain_text_untouched():
    assert strip_call_blocks("Just an answer.", "json") == "Just an answer."


# ---------------------------------------------------------------------------
# Chat CRUD + persistence
# ---------------------------------------------------------------------------


def test_chat_create_list_select(help_agent):
    chat = help_agent.chat_create()
    assert chat.messages[0].message == INITIAL_MESSAGE
    assert help_agent.chat_get_last_active_id() == chat.id

    second = help_agent.chat_create()
    entries = help_agent.chat_list()
    assert [e.id for e in entries] == [second.id, chat.id]

    help_agent.chat_set_last_active_id(chat.id)
    assert help_agent.chat_get_or_create_active().id == chat.id


def test_chat_delete_switches_active(help_agent):
    first = help_agent.chat_create()
    second = help_agent.chat_create()
    assert help_agent.chat_get_last_active_id() == second.id

    assert help_agent.chat_delete(second.id)
    assert help_agent.chat_get_last_active_id() == first.id
    assert not help_agent.chat_delete("nonexistent")


def test_chat_clear(help_agent):
    from talemate.agents.help.schema import HelpChatMessage

    chat = help_agent.chat_create()
    chat.messages.append(HelpChatMessage(message="question", source="user"))
    assert help_agent.chat_clear(chat.id)
    assert len(help_agent.chat_get(chat.id).messages) == 1


def test_chat_scene_aware_toggle(help_agent):
    chat = help_agent.chat_create()
    assert chat.scene_aware is False  # no scene loaded
    assert help_agent.chat_update_scene_aware(chat.id, True)
    assert help_agent.chat_get(chat.id).scene_aware is True


def test_chat_persistence_roundtrip(help_agent):
    chat = help_agent.chat_create()
    help_agent.chat_update_title(chat.id, "My title")

    # a fresh store read (as after a backend restart) sees the same data
    store = help_storage.load_store()
    assert isinstance(store, HelpChatStore)
    assert store.chats[chat.id].title == "My title"
    assert store.last_active_chat_id == chat.id


def test_chat_store_load_corrupt_file_returns_empty(help_agent):
    help_storage.HELP_CHATS_FILE.write_text("{not valid json")
    store = help_storage.load_store()
    assert store.chats == {}


# ---------------------------------------------------------------------------
# Generation loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_send_with_doc_lookup(help_agent):
    """
    First response performs a doc lookup, second response answers.
    The chat must contain: initial, user, doc_result, help answer.
    """
    bootstrap_engine()  # focal logs calls on the director agent
    chat = help_agent.chat_create()

    call_block = json.dumps({"function": "read_doc", "arguments": {"path": "index.md"}})
    updates = []

    async def on_update(chat_id, new_messages):
        updates.extend(new_messages)

    async with MockClientContext():
        responses = client_responses.get()
        responses.append(f"```json\n{call_block}\n```")
        responses.append("Talemate is a storytelling application.")

        await help_agent.chat_send(chat.id, "What is Talemate?", on_update=on_update)

    messages = help_agent.chat_get(chat.id).messages
    types = [(m.type, getattr(m, "source", None)) for m in messages]
    assert types == [
        ("text", "help"),  # initial greeting
        ("text", "user"),
        ("doc_result", None),
        ("text", "help"),
    ]

    doc_result = messages[2]
    assert doc_result.name == "read_doc"
    assert doc_result.result["path"] == "index.md"
    assert messages[3].message == "Talemate is a storytelling application."

    # on_update saw the doc result and the final answer
    assert [m.type for m in updates] == ["doc_result", "text"]


@pytest.mark.asyncio
async def test_chat_send_concurrent_doc_lookups(help_agent):
    """
    Multiple doc-tool calls in one response execute as a focal concurrent
    streak when the client supports concurrent inference.
    """
    bootstrap_engine()
    help_agent.client = _ConcurrentMockClient("test_client")
    chat = help_agent.chat_create()

    call_one = json.dumps({"function": "read_doc", "arguments": {"path": "index.md"}})
    call_two = json.dumps(
        {"function": "search_docs", "arguments": {"query": "revision"}}
    )

    async with MockClientContext():
        responses = client_responses.get()
        responses.append(f"```json\n{call_one}\n```\n```json\n{call_two}\n```")
        responses.append("Answer based on both lookups.")

        await help_agent.chat_send(chat.id, "Tell me about revisions?")

    messages = help_agent.chat_get(chat.id).messages
    doc_results = [m for m in messages if m.type == "doc_result"]
    assert [m.name for m in doc_results] == ["read_doc", "search_docs"]
    assert all(m.result for m in doc_results)
    assert messages[-1].message == "Answer based on both lookups."


@pytest.mark.asyncio
async def test_chat_send_direct_answer(help_agent):
    """A response without call blocks ends the loop immediately."""
    bootstrap_engine()
    chat = help_agent.chat_create()

    done = []

    async def on_done(chat_id):
        done.append(chat_id)

    async with MockClientContext():
        client_responses.get().append("Just an answer, no lookup needed.")
        await help_agent.chat_send(chat.id, "Hi?", on_done=on_done)

    messages = help_agent.chat_get(chat.id).messages
    assert messages[-1].message == "Just an answer, no lookup needed."
    assert done == [chat.id]


@pytest.mark.asyncio
async def test_chat_send_failure_skips_on_done(help_agent, monkeypatch):
    """
    on_done fires only on success - on failure the websocket error handler
    owns the chat_done signal (a success-shaped one would trigger a history
    re-sync that wipes the error message).
    """
    bootstrap_engine()
    chat = help_agent.chat_create()
    done = []

    async def on_done(chat_id):
        done.append(chat_id)

    async def boom(self, *args, **kwargs):
        raise RuntimeError("generation failed")

    monkeypatch.setattr("talemate.game.focal.Focal.request", boom)

    with pytest.raises(RuntimeError):
        await help_agent.chat_send(chat.id, "Hi?", on_done=on_done)

    assert done == []


@pytest.mark.asyncio
async def test_chat_send_rejected_while_generating(help_agent):
    """
    A send while a generation is in flight for the same chat is rejected
    with an error-carrying chat_done instead of being silently dropped.
    """
    import asyncio

    from talemate.agents.help.websocket_handler import HelpWebsocketHandler

    class FakeWSHandler:
        scene = None

        def __init__(self):
            self.sent = []

        def queue_put(self, data):
            self.sent.append(data)

    bootstrap_engine()
    instance.AGENTS["help"] = help_agent
    try:
        chat = help_agent.chat_create()
        ws = FakeWSHandler()
        handler = HelpWebsocketHandler(ws)

        started = asyncio.Event()
        release = asyncio.Event()

        async def busy():
            started.set()
            await release.wait()

        task = await help_agent.run_tracked_task(
            f"help_chat_{chat.id}", busy, background=True
        )
        await started.wait()

        await handler.handle_chat_send({"chat_id": chat.id, "message": "hello"})

        release.set()
        await task

        rejections = [
            m for m in ws.sent if m["action"] == "chat_done" and m.get("error")
        ]
        assert len(rejections) == 1
        assert rejections[0]["chat_id"] == chat.id
        # the dropped message was never persisted
        assert all(m.message != "hello" for m in help_agent.chat_get(chat.id).messages)
    finally:
        instance.AGENTS.pop("help", None)


@pytest.mark.asyncio
async def test_chat_regenerate_last(help_agent):
    bootstrap_engine()
    chat = help_agent.chat_create()

    async with MockClientContext():
        client_responses.get().append("First answer.")
        await help_agent.chat_send(chat.id, "Question?")

        client_responses.get().append("Second answer.")
        await help_agent.chat_regenerate_last(chat.id)

    messages = help_agent.chat_get(chat.id).messages
    texts = [m.message for m in messages if m.type == "text"]
    assert texts == [INITIAL_MESSAGE, "Question?", "Second answer."]


def test_agent_registered():
    from talemate.agents.registry import AGENT_CLASSES

    assert AGENT_CLASSES["help"] is HelpAgent
    assert HelpAgent.essential is False
    assert HelpAgent.websocket_handler.router == "help"
    # keep instance registry clean for other tests
    instance.AGENTS.pop("help", None)


@pytest.mark.asyncio
async def test_chat_send_fires_signals(help_agent, isolate_signals):
    """agent.help.chat.before / .after fire around the generation loop."""
    bootstrap_engine()
    chat = help_agent.chat_create()

    before, after = isolate_signals("agent.help.chat.before", "agent.help.chat.after")
    received = []

    async def on_before(emission):
        received.append(("before", emission.chat_id, len(emission.chat.messages)))

    async def on_after(emission):
        received.append(("after", emission.chat_id, len(emission.chat.messages)))

    before.connect(on_before)
    after.connect(on_after)

    async with MockClientContext():
        client_responses.get().append("Just an answer.")
        await help_agent.chat_send(chat.id, "Hi?")

    # initial + user message at .before; help answer appended by .after
    assert received == [("before", chat.id, 2), ("after", chat.id, 3)]
