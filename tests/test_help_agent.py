"""
Tests for the help agent: documentation tools, chat CRUD + persistence,
call-block stripping and the focal-backed generation loop.
"""

import json
from unittest.mock import AsyncMock

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
from talemate.scene_agent_settings import SceneAgentSettings

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
        assert not entry["title"].startswith(":material-"), entry["path"]


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


@pytest.mark.parametrize(
    "query",
    [
        "commit_revision",
        "pending_perception_messages",
        "scene.history_ready",
        "agent.conversation.finalized",
        "evidence_boundary evidence_budget",
        "intro_knowledge",
        "SourceReference intro",
        "opening audience derivation on load",
        "scoped graph memory access",
        "intro_present",
        "context_review",
        "push_history",
        "before_memory",
        "swap_revision",
        "deep retrieval",
    ],
)
def test_find_docs_scene_processing_api_routes(query):
    assert "dev/character-perspectives.md" in [
        entry["path"] for entry in docs.find_docs(query)
    ]


@pytest.mark.parametrize("symbol,limit", [("SourceReference", 1)])
def test_find_docs_perspective_symbols_keep_code_spelling_near_top(symbol, limit):
    results = docs.find_docs(symbol, limit=limit)
    result = next(
        (
            entry
            for entry in results
            if entry["path"] == "dev/character-perspectives.md"
        ),
        None,
    )
    assert result is not None
    assert symbol in result["summary"]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("summarization settings", "user-guide/agents/summarizer/settings.md"),
        (
            "configure summarization thresholds",
            "user-guide/agents/summarizer/settings.md",
        ),
        ("scene analysis caching", "user-guide/agents/summarizer/settings.md"),
        ("stored views", "dev/character-perspectives.md"),
        ("audience summaries", "dev/character-perspectives.md"),
        ("portrait cadence", "dev/character-perspectives.md"),
        ("flow diagrams", "user-guide/world-editor/knowledge-how-it-works.md"),
        ("reply inputs", "user-guide/world-editor/knowledge-how-it-works.md"),
        (
            "character knowledge flow reference",
            "user-guide/world-editor/knowledge-how-it-works.md",
        ),
        (
            "character re-entry bridge",
            "user-guide/world-editor/knowledge-how-it-works.md",
        ),
        (
            "arrival notes automatic timing",
            "user-guide/world-editor/knowledge-how-it-works.md",
        ),
        (
            "retry regeneration return bridge",
            "user-guide/world-editor/knowledge-how-it-works.md",
        ),
        (
            "activation deactivation chips",
            "user-guide/world-editor/knowledge-how-it-works.md",
        ),
    ],
)
def test_find_docs_preserves_parent_knowledge_routes(query, expected):
    assert expected in [entry["path"] for entry in docs.find_docs(query)]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("koboldcpp client setup", "user-guide/clients/types/koboldcpp.md"),
        ("openrouter api key", "user-guide/apis/openrouter.md"),
        ("context db", "user-guide/world-editor/context-db.md"),
        ("tracking a state", "user-guide/tracking-a-state.md"),
        (
            "collector nodes",
            "user-guide/node-editor/core-concepts/collector_nodes.md",
        ),
        ("character card import", "user-guide/character-card-import.md"),
        ("pytest compose test exclusions", "dev/testing.md"),
        # a thorough summary must keep its phrase bonus: this page is the only
        # one about the pi coding agent, and competes with node-reference
        # pages that match nothing but the token "agent"
        ("coding agent", "user-guide/clients/types/pi-bridge.md"),
    ],
)
def test_find_docs_canonical_pages(query, expected):
    # pinned against the shipped index: regenerating docs-index.yaml must not
    # silently displace the page that answers these questions
    results = docs.find_docs(query)
    assert isinstance(results, list)
    assert results[0]["path"] == expected


def test_find_docs_rare_tokens_outweigh_common_ones():
    # against the shipped index, where many pages are titled "Settings" and
    # only a handful mention KoboldCpp at all - the distinctive token has to
    # decide the match, or the query drowns in generic settings pages. Any
    # KoboldCpp page is a right answer here; the point is that one wins.
    results = docs.find_docs("koboldcpp settings")
    assert isinstance(results, list)
    assert "koboldcpp" in results[0]["path"]


# the real #169 case: a summary hand-extended to describe a documentation
# section accurately, which then surfaced for topics the page barely mentions
BLOAT = (
    " Covers per-step toggles for content context, description, attributes, "
    "dialogue instructions, example dialogue and story intent, Full/Minimal "
    "presets, and card-data fallback when a step is off or fails."
)
BLOATED_PATH = "user-guide/character-card-import.md"


@pytest.mark.parametrize(
    "query",
    [
        "dialogue instructions",
        "example dialogue",
        "story intent",
        "content context",
    ],
)
def test_find_docs_long_summary_cannot_displace_better_matches(query, monkeypatch):
    # #169: padding a summary with topics the page only mentions in passing
    # must not buy it a slot above the last result. The corpus-wide IDF and
    # average summary length also change, so unrelated relevant pages may
    # reorder; that is not promotion of the padded page.
    index = docs.load_docs_index()
    assert any(entry["path"] == BLOATED_PATH for entry in index)
    bloated_index = [
        {**entry, "summary": entry["summary"] + BLOAT}
        if entry["path"] == BLOATED_PATH
        else entry
        for entry in index
    ]

    trimmed = [entry["path"] for entry in docs.find_docs(query)]
    monkeypatch.setattr(docs, "load_docs_index", lambda: bloated_index)
    bloated = [entry["path"] for entry in docs.find_docs(query)]

    assert BLOATED_PATH not in trimmed
    assert BLOATED_PATH not in bloated[:-1]


def test_find_docs_summary_phrase_bonus_is_diluted(monkeypatch):
    # the phrase bonus is the one component that could still be bought with
    # length: an exact phrase planted in a padded summary used to add a flat
    # +3 and evict a page whose token score alone outscored the intruder
    index = docs.load_docs_index()
    bloated_index = [
        {**entry, "summary": entry["summary"] + BLOAT}
        if entry["path"] == BLOATED_PATH
        else entry
        for entry in index
    ]
    trimmed = [entry["path"] for entry in docs.find_docs("dialogue instructions")]
    monkeypatch.setattr(docs, "load_docs_index", lambda: bloated_index)

    # "dialogue instructions" is in BLOAT verbatim, so the padded entry takes
    # the summary-phrase branch - and must still stay out of the results,
    # displacing nothing
    paths = [entry["path"] for entry in docs.find_docs("dialogue instructions")]
    assert BLOATED_PATH not in paths
    assert paths == trimmed


def test_find_docs_phrase_dilution_bites_past_typical_length(monkeypatch):
    # the other side of the trade from the canonical "coding agent" pin: that
    # page wins its own topic at its real summary length, and has to lose once
    # its summary runs well past typical.
    #
    # Padded to 2.5x typical deliberately. Pad much further and the page loses
    # on summary-token dilution alone, which would leave this test passing with
    # the phrase dilution deleted entirely; at 2.5x it still wins on an
    # undiluted bonus, so only the dilution can decide it.
    index = docs.load_docs_index()
    target = "user-guide/clients/types/pi-bridge.md"
    scoring = docs._scoring_index()
    indexed = next(e for e in scoring.entries if e.entry["path"] == target)
    # "zz0 zz1 ..." - distinct filler tokens that match no real query
    filler_tokens = int(scoring.average_summary_tokens * 2.5) - len(
        indexed.summary_tokens
    )
    assert filler_tokens > 0
    filler = " " + " ".join(f"zz{i}" for i in range(filler_tokens))
    padded = [
        {**entry, "summary": entry["summary"] + filler}
        if entry["path"] == target
        else entry
        for entry in index
    ]

    assert docs.find_docs("coding agent")[0]["path"] == target
    monkeypatch.setattr(docs, "load_docs_index", lambda: padded)
    assert docs.find_docs("coding agent")[0]["path"] != target


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
async def test_update_agent_setting_combobox_keeps_a_value_outside_the_choices(
    settings_env,
):
    agent = instance.get_agent("conversation")
    agent.actions["generation_override"].config["format"].type = "combobox"

    payload = help_settings.read_agent_settings("conversation")
    fmt = payload["actions"]["generation_override"]["settings"]["format"]
    assert fmt["other_values"] == "accepted, the choices are suggestions"
    assert "read_only" not in fmt

    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "format", "my-own-format"
    )
    assert result["new_value"] == "my-own-format"
    assert (
        agent.actions["generation_override"].config["format"].value == "my-own-format"
    )


@pytest.mark.asyncio
async def test_update_agent_setting_refuses_secret_fields(settings_env):
    agent = instance.get_agent("conversation")
    agent.actions["generation_override"].config["instructions"].type = "password"

    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "instructions", "x"
    )
    assert "agent settings page" in result


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


async def _visualizer_with_backend(backend_name: str):
    """The Visualizer with its text-to-image backend built, as a load builds it."""
    agent = instance.get_agent("visual")
    await agent.apply_config(
        actions={"_config": {"config": {"backend": {"value": backend_name}}}},
        enabled=True,
    )
    return agent


@pytest.mark.asyncio
async def test_update_agent_setting_reaches_the_visualizer_backend(settings_env):
    agent = await _visualizer_with_backend("openrouter")
    assert agent.backend.model != "meta/muse-image"

    result = await help_settings.update_agent_setting(
        "visual", "openrouter_image_create", "model", "meta/muse-image"
    )

    assert result["applied"] is True
    assert agent.backend.model == "meta/muse-image"


@pytest.mark.asyncio
async def test_update_agent_setting_rebuilds_the_comfyui_backend_on_a_new_url(
    settings_env,
):
    agent = await _visualizer_with_backend("comfyui")
    old_backend = agent.backend

    await help_settings.update_agent_setting(
        "visual", "comfyui_image_create", "api_url", "http://comfy.local:8188"
    )

    # the backend is rebuilt only when it sees the old and the new URL differ
    assert agent.backend is not old_backend
    assert agent.backend.api_url == "http://comfy.local:8188"


@pytest.mark.asyncio
async def test_update_agent_setting_reloads_the_embeddings_on_a_device_change(
    settings_env, monkeypatch
):
    agent = instance.get_agent("memory")
    embeddings_change = AsyncMock()
    monkeypatch.setattr(agent, "handle_embeddings_change", embeddings_change)

    result = await help_settings.update_agent_setting(
        "memory", "_config", "device", "cuda"
    )

    assert result["new_value"] == "cuda"
    embeddings_change.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_agent_setting_keeps_a_change_whose_apply_fails(
    settings_env, monkeypatch
):
    agent = instance.get_agent("conversation")

    async def failing_apply(*args, **kwargs):
        raise RuntimeError("the backend is gone")

    monkeypatch.setattr(agent, "apply_config", failing_apply)

    result = await help_settings.update_agent_setting(
        "conversation", "generation_override", "length", 256
    )

    assert result == (
        "Saved generation_override.length = 256, but applying it to the running "
        "agent failed: the backend is gone. Restart Talemate to apply it."
    )
    saved = get_config().agents["conversation"]
    assert saved.actions["generation_override"].config["length"].value == 256
    assert config_state.PENDING_APPLY == {"agents"}


@pytest.mark.asyncio
async def test_update_agent_setting_enabled_toggle_reaches_apply_config(
    settings_env, monkeypatch
):
    agent = instance.get_agent("editor")
    real_apply = agent.apply_config
    seen = []

    async def recording_apply(*args, **kwargs):
        # the flag the agent holds, and the flag the config hands it
        seen.append(
            (
                agent.actions["fix_exposition"].enabled,
                kwargs["actions"]["fix_exposition"]["enabled"],
            )
        )
        await real_apply(*args, **kwargs)

    monkeypatch.setattr(agent, "apply_config", recording_apply)

    await help_settings.update_agent_setting(
        "editor", "fix_exposition", "enabled", False
    )

    assert seen == [(True, False)]
    assert agent.actions["fix_exposition"].enabled is False


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


def test_read_agent_settings_omits_inert_scene_overrides(settings_env, tmp_path):
    """`resolve_config` ignores an overlay value for a non-overridable field, so
    reporting it would name an effective value that is not in effect."""
    agent = instance.get_agent("conversation")
    scene = _SceneStub(tmp_path)
    overrides = SceneAgentSettings(filepath=tmp_path / "agent-settings.json")
    overrides.set_value("conversation", "generation_override", "length", 384)
    overrides.set_value(
        "conversation", "prompt_caching", "optimize_prompt_caching", "on"
    )
    scene.agent_overrides = overrides
    agent.scene = scene

    try:
        payload = help_settings.read_agent_settings("conversation")
    finally:
        agent.scene = None

    length = payload["actions"]["generation_override"]["settings"]["length"]
    assert length["scene_override"] == 384

    caching = payload["actions"]["prompt_caching"]["settings"][
        "optimize_prompt_caching"
    ]
    assert caching["scene_overridable"] is False
    assert "scene_override" not in caching


@pytest.mark.asyncio
async def test_clear_scene_override_redacts_a_secret_value(settings_env, tmp_path):
    """The clear tool must not hand the removed credential back to the LLM."""
    agent = instance.get_agent("conversation")
    field = agent.actions["generation_override"].config["instructions"]
    original_type = field.type
    field.type = "password"

    scene = _SceneStub(tmp_path)
    overrides = SceneAgentSettings(filepath=tmp_path / "agent-settings.json")
    overrides.set_value(
        "conversation", "generation_override", "instructions", "super-secret"
    )
    scene.agent_overrides = overrides
    agent.scene = scene

    try:
        result = await help_settings.clear_agent_setting_scene_override(
            "conversation", "generation_override", "instructions"
        )
    finally:
        field.type = original_type
        agent.scene = None

    assert result["cleared"] is True
    assert result["removed_override_value"] == help_settings.REDACTED
    assert "super-secret" not in json.dumps(result)
    assert (
        overrides.get_value("conversation", "generation_override", "instructions")
        is help_settings.UNSET
    )


@pytest.mark.asyncio
async def test_clear_scene_override_returns_real_value_for_normal_fields(
    settings_env, tmp_path
):
    agent = instance.get_agent("conversation")
    scene = _SceneStub(tmp_path)
    overrides = SceneAgentSettings(filepath=tmp_path / "agent-settings.json")
    overrides.set_value("conversation", "generation_override", "length", 384)
    scene.agent_overrides = overrides
    agent.scene = scene

    try:
        result = await help_settings.clear_agent_setting_scene_override(
            "conversation", "generation_override", "length"
        )
    finally:
        agent.scene = None

    assert result["removed_override_value"] == 384


@pytest.mark.asyncio
async def test_global_write_does_not_warn_about_an_inert_override(
    settings_env, tmp_path
):
    """`resolve_config` ignores the stored value, so the global write IS in
    effect — a masking warning would be wrong."""
    agent = instance.get_agent("conversation")
    scene = _SceneStub(tmp_path)
    overrides = SceneAgentSettings(filepath=tmp_path / "agent-settings.json")
    overrides.set_value(
        "conversation", "prompt_caching", "optimize_prompt_caching", "on"
    )
    overrides.set_value("conversation", "generation_override", "length", 384)
    scene.agent_overrides = overrides
    agent.scene = scene

    try:
        inert = await help_settings.update_agent_setting(
            "conversation", "prompt_caching", "optimize_prompt_caching", "off", "global"
        )
        masked = await help_settings.update_agent_setting(
            "conversation", "generation_override", "length", 256, "global"
        )
    finally:
        agent.scene = None

    assert "warning" not in inert
    # an override that really does mask the global value still warns
    assert "scene override" in masked["warning"]


def test_action_payload_omits_inert_enabled_override(settings_env, tmp_path):
    agent = instance.get_agent("conversation")
    scene = _SceneStub(tmp_path)
    overrides = SceneAgentSettings(filepath=tmp_path / "agent-settings.json")
    # `generation_override` has no Enable control; `use_long_term_memory` does
    overrides.set_enabled("conversation", "generation_override", False)
    overrides.set_enabled("conversation", "use_long_term_memory", False)
    scene.agent_overrides = overrides
    agent.scene = scene

    try:
        payload = help_settings.read_agent_settings("conversation")
    finally:
        agent.scene = None

    assert "enabled_scene_override" not in payload["actions"]["generation_override"]
    assert payload["actions"]["use_long_term_memory"]["enabled_scene_override"] is False


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
    assert presets["mode"] == "index"
    assert {"inference_defaults", "embeddings_defaults"} <= {
        entry["key"] for entry in presets["entries"]
    }
    defaults = help_settings.read_app_config(
        "presets", ["inference_defaults", "analytical"]
    )
    assert defaults["values"]["temperature"] == 0.7

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
    allow_settings_changes(help_agent)
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
async def test_update_agent_setting_refused_while_app_settings_dirty(
    settings_env, tmp_path
):
    # the settings view saves its whole working copy from whatever page is
    # showing, so ANY unsaved edit there would push the pre-change values back
    result = await help_settings.update_agent_setting(
        "conversation",
        "generation_override",
        "length",
        256,
        "global",
        app_settings_dirty=True,
    )
    assert isinstance(result, str)
    assert "unsaved edits" in result

    agent = instance.get_agent("conversation")
    assert agent.actions["generation_override"].config["length"].value == 192

    # an open but clean settings view is not a conflict
    result = await help_settings.update_agent_setting(
        "conversation",
        "generation_override",
        "length",
        256,
        "global",
        app_settings_dirty=False,
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
        app_settings_dirty=True,
    )
    assert isinstance(result, str)
    assert "unsaved edits" in result
    assert agent.resolve_config("generation_override", "length") == 384


@pytest.mark.asyncio
def allow_settings_changes(agent):
    """The permission is off by default; these two drive the write tools."""
    agent.actions["permissions"].config["allow_settings_changes"].value = True


async def test_chat_send_setting_update_refused_while_app_settings_dirty(
    help_agent, settings_env
):
    """The ux snapshot's dirty settings view reaches the settings tools."""
    allow_settings_changes(help_agent)
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
        responses.append("The settings view has unsaved edits - save them first.")

        await help_agent.chat_send(
            chat.id,
            "Set the conversation generation length to 256",
            ux_snapshot={
                # the user is on an unrelated page - the dirty flag covers the
                # whole working copy (including page-owned extra changes)
                "app_settings_modal": {
                    "tab": "settings",
                    "page": "gameplay",
                    "dirty": True,
                }
            },
        )

    messages = help_agent.chat_get(chat.id).messages
    tool_results = [m for m in messages if m.type == "doc_result"]
    assert len(tool_results) == 1
    assert "unsaved edits" in tool_results[0].result

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


@pytest.mark.parametrize(
    "query,page",
    [
        ("learn never learn rules", "knowledge.md"),
        ("first save continuation retry discard", "knowledge.md"),
        ("intro audiences", "knowledge-how-it-works.md"),
        ("browse revisions before keeping a version", "knowledge-how-it-works.md"),
        ("reply inputs and memory ranking", "knowledge-how-it-works.md"),
        (
            "mode decision tree model secrets cast size cost",
            "knowledge-how-it-works.md",
        ),
        ("revision browsing", "knowledge-how-it-works.md"),
        ("collapsed return entries automatic timing arrival notes", "knowledge.md"),
        ("character activation arrival note", "knowledge.md"),
    ],
)
def test_find_docs_preserves_knowledge_routes_after_return_updates(query, page):
    assert "user-guide/world-editor/" + page in [
        entry["path"] for entry in docs.find_docs(query, limit=3)
    ]
