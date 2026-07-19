"""
Tests for the help agent: documentation tools, chat CRUD + persistence,
call-block stripping and the focal-backed generation loop.
"""

import json

import pytest

import talemate.agents.help.storage as help_storage
import talemate.config.state as config_state
import talemate.emit.async_signals as async_signals
import talemate.instance as instance
from talemate.agents.help import settings as help_settings
from talemate.config import get_config
from talemate.config.schema import Client, Config
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
# find_docs / docs_section_overview
# ---------------------------------------------------------------------------

FIND_DOCS_INDEX = [
    {
        "path": "user-guide/node-editor/reference/nodes/context-id.md",
        "title": "Context ID Nodes",
        "summary": "Node reference. Nodes: Set Pin, Remove Pin, Is Pin Active.",
    },
    {
        "path": "user-guide/agents/world-state/settings.md",
        "title": "Settings",
        "summary": "World state agent settings: state reinforcement options.",
    },
    {
        "path": "user-guide/clients/types/koboldcpp.md",
        "title": "KoboldCpp Client",
        "summary": "KoboldCpp client setup and options.",
    },
    {
        "path": "user-guide/node-editor/reference/nodes/core.md",
        "title": "Core Nodes",
        "summary": "Graph plumbing: Route, Watch, Null and Stage.",
    },
    {
        "path": "user-guide/apis/openrouter.md",
        "title": "OpenRouter",
        "summary": "OpenRouter API key setup.",
    },
    {
        "path": "user-guide/tracking-a-state.md",
        "title": "Tracking a State",
        "summary": "Tracking world and character states.",
    },
    {
        "path": "user-guide/node-editor/reference/nodes/scene-characters.md",
        "title": "Scene Character Nodes",
        "summary": "Nodes: Get Character, Make Character.",
    },
]


@pytest.fixture
def stub_docs_index(monkeypatch):
    monkeypatch.setattr(docs, "load_docs_index", lambda: FIND_DOCS_INDEX)


def test_find_docs_result_shape_and_url(stub_docs_index):
    results = docs.find_docs("koboldcpp")
    assert isinstance(results, list)
    first = results[0]
    assert first.keys() == {"path", "title", "summary", "url"}
    assert first["path"] == "user-guide/clients/types/koboldcpp.md"
    assert first["url"] == docs.doc_url(first["path"])


def test_find_docs_word_boundaries_not_substrings(stub_docs_index):
    # "set" must not match "settings": the Set Pin node page has to beat
    # the settings page
    results = docs.find_docs("Set Pin")
    assert results[0]["path"] == "user-guide/node-editor/reference/nodes/context-id.md"

    # "route" must not match "openrouter"
    results = docs.find_docs("Route")
    paths = [entry["path"] for entry in results]
    assert "user-guide/node-editor/reference/nodes/core.md" in paths
    assert "user-guide/apis/openrouter.md" not in paths


def test_find_docs_camelcase_and_compound_tokens(stub_docs_index):
    # registry-path style queries split on camelCase
    results = docs.find_docs("scene/GetCharacter")
    assert (
        results[0]["path"]
        == "user-guide/node-editor/reference/nodes/scene-characters.md"
    )
    # compound names also match unsplit ("koboldcpp" vs "KoboldCpp")
    results = docs.find_docs("koboldcpp setup")
    assert results[0]["path"] == "user-guide/clients/types/koboldcpp.md"


def test_find_docs_morphology_folds(stub_docs_index):
    # singular query matches plural titles
    results = docs.find_docs("core node")
    assert results[0]["path"] == "user-guide/node-editor/reference/nodes/core.md"
    # "track" matches "Tracking"
    results = docs.find_docs("track a state")
    assert results[0]["path"] == "user-guide/tracking-a-state.md"


def test_find_docs_limit(stub_docs_index):
    results = docs.find_docs("nodes", limit=2)
    assert isinstance(results, list)
    assert len(results) == 2


def test_find_docs_empty_and_no_match(stub_docs_index):
    assert isinstance(docs.find_docs(""), str)
    result = docs.find_docs("zzz-no-such-topic-zzz")
    assert isinstance(result, str)
    assert "No documentation pages match" in result


def test_find_docs_real_index_smoke():
    # against the shipped index: a node question must surface its
    # reference page
    results = docs.find_docs("Dict Collector node")
    assert isinstance(results, list)
    assert any(
        "node-editor" in entry["path"] and "collect" in entry["path"].lower()
        for entry in results
    )


def test_docs_section_overview(stub_docs_index):
    overview = docs.docs_section_overview()
    by_prefix = {entry["prefix"]: entry for entry in overview}
    assert by_prefix["user-guide/node-editor"]["count"] == 3
    assert by_prefix["user-guide"]["count"] == 1
    assert by_prefix["user-guide/clients"]["count"] == 1
    # known prefixes carry curated descriptions
    assert (
        by_prefix["user-guide/clients"]["description"]
        == docs.SECTION_DESCRIPTIONS["user-guide/clients"]
    )
    # sorted by prefix
    assert [entry["prefix"] for entry in overview] == sorted(
        entry["prefix"] for entry in overview
    )


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


# ---------------------------------------------------------------------------
# Settings tools
# ---------------------------------------------------------------------------


class _SceneStub:
    """Minimal scene stand-in with the attributes scene-override writes need."""

    def __init__(self, save_dir):
        self.name = "Test Scene"
        self.filename = "scene.json"
        self.project_name = "test-scene"
        self.save_dir = save_dir
        self.agent_overrides = None
        self.agent_settings_file = None
        self._agent_settings_opted_out = False


@pytest.fixture
def settings_env(monkeypatch):
    """Bootstrapped agents + isolated config; config never touches disk."""
    bootstrap_engine()

    original = config_state.CONFIG
    config_state.CONFIG = Config.model_validate(
        original.model_dump() if original else {}
    )

    async def _no_commit():
        pass

    monkeypatch.setattr(help_settings, "commit_config", _no_commit)

    # config.changed receivers (e.g. the memory agent's key watcher) expect
    # a fully wired runtime - detach them for the test
    isolated = {}
    for signal_name in ("config.changed", "config.changed.follow"):
        sig = async_signals.get(signal_name)
        isolated[signal_name] = (sig, list(sig.receivers))
        sig.receivers.clear()

    yield config_state.CONFIG

    for sig, receivers in isolated.values():
        sig.receivers.clear()
        sig.receivers.extend(receivers)

    config_state.CONFIG = original


def test_read_agent_settings(settings_env):
    payload = help_settings.read_agent_settings("conversation")
    assert payload["agent"] == "conversation"
    assert payload["enabled"] is True

    action = payload["actions"]["generation_override"]
    assert action["label"] == "Generation"

    length = action["settings"]["length"]
    assert length["type"] == "number"
    assert length["value"] == 192
    assert length["min"] == 32
    assert length["max"] == 4096

    fmt = action["settings"]["format"]
    assert {"label": "Narrative", "value": "narrative"} in fmt["choices"]

    # other agents read fine too
    payload_editor = help_settings.read_agent_settings("editor")
    assert payload_editor["actions"]["fix_exposition"]["can_be_disabled"] is True


def test_read_agent_settings_unknown_agent(settings_env):
    result = help_settings.read_agent_settings("nope")
    assert isinstance(result, str)
    assert "conversation" in result


def test_read_agent_settings_redacts_secret_fields(settings_env):
    agent = instance.get_agent("conversation")
    field = agent.actions["generation_override"].config["instructions"]
    field.type = "password"
    field.value = "super-secret"

    payload = help_settings.read_agent_settings("conversation")
    rendered = json.dumps(payload)
    assert "super-secret" not in rendered
    instructions = payload["actions"]["generation_override"]["settings"]["instructions"]
    assert instructions["value"] == help_settings.REDACTED
    assert "read_only" in instructions


@pytest.mark.asyncio
async def test_update_agent_setting_global(settings_env):
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", "256", "global"
    )
    assert result["applied"] is True
    assert result["previous_value"] == 192
    assert result["new_value"] == 256

    agent = instance.get_agent("conversation")
    assert agent.actions["generation_override"].config["length"].value == 256

    # persisted into the app config
    saved = get_config().agents["conversation"]
    assert saved.actions["generation_override"].config["length"].value == 256


@pytest.mark.asyncio
async def test_update_agent_setting_validation(settings_env):
    # unknown agent / action / setting
    assert "Valid agents" in await help_settings.update_agent_setting(
        "nope", "x", "y", 1
    )
    assert "Valid actions" in await help_settings.update_agent_setting(
        "conversation", "nope", "y", 1
    )
    assert "Valid settings" in await help_settings.update_agent_setting(
        "conversation", "generation_override", "nope", 1
    )

    # number range
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 8
    )
    assert "below the minimum" in result

    # invalid choice
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "format", "banana"
    )
    assert "Invalid choice" in result

    # choice by label (case-insensitive) resolves to the value
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "format", "narrative"
    )
    assert result["new_value"] == "narrative"

    # invalid scope
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 64, "nope"
    )
    assert "Invalid scope" in result


@pytest.mark.asyncio
async def test_update_agent_setting_refuses_secret_fields(settings_env):
    agent = instance.get_agent("conversation")
    agent.actions["generation_override"].config["instructions"].type = "password"

    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "instructions", "x"
    )
    assert "settings dialog" in result


@pytest.mark.asyncio
async def test_update_agent_setting_enabled_toggle(settings_env):
    # editor.fix_exposition can be disabled
    result = await help_settings.update_agent_setting(
        "editor", "fix_exposition", "enabled", "false"
    )
    assert result["applied"] is True
    assert result["new_value"] is False
    assert instance.get_agent("editor").actions["fix_exposition"].enabled is False

    # help.chat cannot
    result = await help_settings.update_agent_setting("help", "chat", "enabled", False)
    assert "always enabled" in result


@pytest.mark.asyncio
async def test_update_agent_setting_scene_override(settings_env, tmp_path):
    agent = instance.get_agent("conversation")
    agent.scene = _SceneStub(tmp_path)

    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 384, "scene"
    )
    assert result["applied"] is True
    assert result["scope"] == "scene"
    assert result["new_value"] == 384

    # overlay file created with the default name and override active
    assert (tmp_path / "agent-settings" / "agent-settings.json").exists()
    assert agent.resolve_config("generation_override", "length") == 384
    # the global value is untouched
    assert agent.actions["generation_override"].config["length"].value == 192

    # a global write on an overridden field warns about the mask
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 224, "global"
    )
    assert "scene override" in result["warning"]

    # reading reports the override
    payload = help_settings.read_agent_settings("conversation")
    length = payload["actions"]["generation_override"]["settings"]["length"]
    assert length["scene_override"] == 384

    # clearing restores fall-through to the global value
    result = await help_settings.clear_agent_setting_scene_override(
        "conversation", "generation_override", "length"
    )
    assert result["cleared"] is True
    assert result["removed_override_value"] == 384
    assert agent.resolve_config("generation_override", "length") == 224

    result = await help_settings.clear_agent_setting_scene_override(
        "conversation", "generation_override", "length"
    )
    assert "No scene override" in result


@pytest.mark.asyncio
async def test_update_agent_setting_scene_override_guards(settings_env, tmp_path):
    agent = instance.get_agent("conversation")
    agent.scene = None

    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 384, "scene"
    )
    assert "No scene is currently loaded" in result

    # unsaved scene
    scene = _SceneStub(tmp_path)
    scene.filename = None
    agent.scene = scene
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 384, "scene"
    )
    assert "not been saved" in result

    # opted out
    scene = _SceneStub(tmp_path)
    scene._agent_settings_opted_out = True
    agent.scene = scene
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 384, "scene"
    )
    assert "opted out" in result

    # field not scene-overridable
    scene = _SceneStub(tmp_path)
    agent.scene = scene
    result = await help_settings.update_agent_setting(
        "conversation", "prompt_caching", "optimize_prompt_caching", "on", "scene"
    )
    assert "cannot be overridden per scene" in result

    # enabled flag not scene-overridable on this action
    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "enabled", False, "scene"
    )
    assert "cannot be overridden per scene" in result


def test_read_app_config(settings_env):
    payload = help_settings.read_app_config("game")
    assert payload["writable"] is True
    assert payload["values"]["general"]["auto_save"] is True

    presets = help_settings.read_app_config("presets")
    assert presets["writable"] is False
    assert "inference_defaults" not in presets["values"]
    assert "embeddings_defaults" not in presets["values"]

    result = help_settings.read_app_config("clients")
    assert isinstance(result, str)
    assert "read_clients" in result


@pytest.mark.asyncio
async def test_update_app_config(settings_env):
    result = await help_settings.update_app_config("game.general.auto_save", "false")
    assert result["applied"] is True
    assert result["previous_value"] is True
    assert result["new_value"] is False
    assert get_config().game.general.auto_save is False

    # list replacement
    result = await help_settings.update_app_config(
        "creator.content_context", ["a story", "another story"]
    )
    assert result["applied"] is True
    assert get_config().creator.content_context == ["a story", "another story"]


@pytest.mark.asyncio
async def test_update_app_config_validation(settings_env):
    # pydantic validation rejects out-of-range values
    result = await help_settings.update_app_config(
        "appearance.scene.backdrop_panel_opacity", 5
    )
    assert isinstance(result, str)
    assert "Invalid value" in result
    assert get_config().appearance.scene.backdrop_panel_opacity == 0.8

    # section not writable
    result = await help_settings.update_app_config(
        "presets.inference.creative.temperature", 0.5
    )
    assert "not writable" in result

    # bad paths
    assert "does not exist" in await help_settings.update_app_config(
        "game.general.nope", 1
    )
    assert "does not exist" in await help_settings.update_app_config(
        "game.nope.deeper", 1
    )
    assert "at least a section and a setting" in await help_settings.update_app_config(
        "game", 1
    )

    # nested sections are not settings
    result = await help_settings.update_app_config("game.general", 1)
    assert "nested section" in result

    # api keys are refused outright
    result = await help_settings.update_app_config("game.api_key", "x")
    assert "cannot be read or changed" in result

    # type coercion errors
    result = await help_settings.update_app_config("game.general.auto_save", "maybe")
    assert "expects a boolean" in result
    result = await help_settings.update_app_config(
        "game.general.max_backscroll", "lots"
    )
    assert "expects a number" in result
    result = await help_settings.update_app_config(
        "creator.content_context", "not a list"
    )
    assert "full list" in result


def test_read_clients_redacts_api_keys(settings_env):
    config = get_config()
    config.clients.clear()
    config.clients["testc"] = Client(
        type="openai", name="testc", model="gpt-x", api_key="super-secret-key"
    )

    payload = help_settings.read_clients()
    assert len(payload) == 1
    entry = payload[0]
    assert entry["name"] == "testc"
    assert entry["api_key"] == "set"
    assert "super-secret-key" not in json.dumps(payload)


def test_read_clients_empty(settings_env):
    get_config().clients.clear()
    assert "No clients" in help_settings.read_clients()


@pytest.mark.asyncio
async def test_chat_send_with_setting_update(help_agent, settings_env):
    """A settings write requested through the chat loop is applied and
    recorded as a tool-result message."""
    chat = help_agent.chat_create()

    call_block = json.dumps(
        {
            "function": "update_agent_setting",
            "arguments": {
                "agent": "conversation",
                "action": "generation_override",
                "setting": "length",
                "value": 256,
                "scope": "global",
            },
        }
    )

    async with MockClientContext():
        responses = client_responses.get()
        responses.append(f"```json\n{call_block}\n```")
        responses.append("Done - conversation generation length is now 256 tokens.")

        await help_agent.chat_send(
            chat.id, "Set the conversation generation length to 256"
        )

    messages = help_agent.chat_get(chat.id).messages
    tool_results = [m for m in messages if m.type == "doc_result"]
    assert len(tool_results) == 1
    assert tool_results[0].name == "update_agent_setting"
    assert tool_results[0].result["applied"] is True

    agent = instance.get_agent("conversation")
    assert agent.actions["generation_override"].config["length"].value == 256


@pytest.mark.asyncio
async def test_update_agent_setting_refused_while_modal_open(settings_env, tmp_path):
    # write targeting the agent whose settings dialog is open is refused
    result = await help_settings.update_agent_setting(
        "conversation",
        "generation_override",
        "length",
        256,
        "global",
        open_agent_modal="conversation",
    )
    assert isinstance(result, str)
    assert "settings dialog" in result

    agent = instance.get_agent("conversation")
    assert agent.actions["generation_override"].config["length"].value == 192

    # a different agent's open dialog does not block the write
    result = await help_settings.update_agent_setting(
        "conversation",
        "generation_override",
        "length",
        256,
        "global",
        open_agent_modal="summarizer",
    )
    assert result["applied"] is True

    # clearing a scene override is refused the same way
    agent.scene = _SceneStub(tmp_path)
    await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 384, "scene"
    )
    result = await help_settings.clear_agent_setting_scene_override(
        "conversation",
        "generation_override",
        "length",
        open_agent_modal="conversation",
    )
    assert isinstance(result, str)
    assert "settings dialog" in result
    assert agent.resolve_config("generation_override", "length") == 384


@pytest.mark.asyncio
async def test_chat_send_setting_update_refused_while_modal_open(
    help_agent, settings_env
):
    """The ux snapshot's open agent modal reaches the settings tools."""
    chat = help_agent.chat_create()

    call_block = json.dumps(
        {
            "function": "update_agent_setting",
            "arguments": {
                "agent": "conversation",
                "action": "generation_override",
                "setting": "length",
                "value": 256,
                "scope": "global",
            },
        }
    )

    async with MockClientContext():
        responses = client_responses.get()
        responses.append(f"```json\n{call_block}\n```")
        responses.append("The conversation settings dialog is open - close it first.")

        await help_agent.chat_send(
            chat.id,
            "Set the conversation generation length to 256",
            ux_snapshot={
                "agent_settings_modal": {"agent": "conversation", "tab": "general"}
            },
        )

    messages = help_agent.chat_get(chat.id).messages
    tool_results = [m for m in messages if m.type == "doc_result"]
    assert len(tool_results) == 1
    assert "settings dialog" in tool_results[0].result

    agent = instance.get_agent("conversation")
    assert agent.actions["generation_override"].config["length"].value == 192


@pytest.mark.asyncio
async def test_update_agent_setting_flags(settings_env):
    # flags fields hold a list of choice values - full-list replacement
    result = await help_settings.update_agent_setting(
        "editor", "revision", "automatic_revision_targets", ["narrator"]
    )
    assert result["applied"] is True
    assert result["previous_value"] == ["character", "narrator"]
    assert result["new_value"] == ["narrator"]

    agent = instance.get_agent("editor")
    field = agent.actions["revision"].config["automatic_revision_targets"]
    assert field.value == ["narrator"]

    # elements resolve by label too, and invalid elements are rejected
    result = await help_settings.update_agent_setting(
        "editor", "revision", "automatic_revision_targets", ["banana"]
    )
    assert "Invalid choice" in result
    assert field.value == ["narrator"]

    # scalars are rejected outright - a scalar write would corrupt the list
    result = await help_settings.update_agent_setting(
        "editor", "revision", "automatic_revision_targets", "narrator"
    )
    assert "list of values" in result
    assert field.value == ["narrator"]

    # empty list clears all flags
    result = await help_settings.update_agent_setting(
        "editor", "revision", "automatic_revision_targets", []
    )
    assert result["applied"] is True
    assert field.value == []


@pytest.mark.asyncio
async def test_update_app_config_refused_while_app_settings_dirty(settings_env):
    result = await help_settings.update_app_config(
        "game.general.auto_save", False, app_settings_dirty=True
    )
    assert isinstance(result, str)
    assert "unsaved edits" in result
    assert get_config().game.general.auto_save is True

    # a merely open (clean) settings view does not block the write
    result = await help_settings.update_app_config(
        "game.general.auto_save", False, app_settings_dirty=False
    )
    assert result["applied"] is True
    assert get_config().game.general.auto_save is False


def test_read_clients_unified_api_key(settings_env):
    """Clients resolving their key from an app-level unified path must not
    report 'not set' when that key is configured."""
    config = get_config()
    config.clients.clear()
    config.clients["openrouter"] = Client(
        type="openrouter", name="openrouter", model="some-model"
    )

    config.openrouter.api_key = None
    payload = help_settings.read_clients()
    assert payload[0]["api_key"] == "not set"

    # a key cleared in Application Settings persists as "" and clients treat it
    # as unset - it must not report "set"
    config.openrouter.api_key = ""
    payload = help_settings.read_clients()
    assert payload[0]["api_key"] == "not set"

    config.openrouter.api_key = "sk-or-unified-secret"
    payload = help_settings.read_clients()
    assert payload[0]["api_key"] == (
        "set (unified API key from application settings: openrouter.api_key)"
    )
    assert "sk-or-unified-secret" not in json.dumps(payload)
