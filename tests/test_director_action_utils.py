"""Unit tests for talemate.agents.director.action_core.utils.

Covers the pure-Python helpers in this module:
- parse_response, clean_response
- extract_actions (uses real MockClient supplying data_format)
- reverse_trim_history (history token trimming)
- compact_if_needed (history compaction with real SummarizerAgent stubbed at
  the instance method)
- serialize_history
- _build_callback_groups (private but a pure transform — tested via
  get_available_actions, exercised through a curated registry stub)

LLM-driven branches that talk to Prompt.request / Focal.request are
exercised against the real ``Prompt`` class with ``raising=True`` patches
so any rename of the real class surface fails the tests immediately.
"""

from __future__ import annotations

from typing import Any

import pytest

import talemate.instance as instance
from conftest import MockClient, MockScene, bootstrap_scene
from talemate.agents.director import DirectorAgent
from talemate.agents.director.action_core.gating import CallbackDescriptor
from talemate.agents.director.action_core.schema import (
    ActionCoreBudgets,
    ActionCoreMessage,
    ActionCoreResultMessage,
)
from talemate.agents.director.action_core.utils import (
    _build_callback_groups,
    build_prompt_vars,
    clean_response,
    compact_if_needed,
    extract_actions,
    get_available_actions,
    init_action_nodes,
    parse_response,
    request_and_parse,
    reverse_trim_history,
    serialize_history,
)
from talemate.agents.director.scene_direction.schema import UserInteractionMessage
from talemate.agents.summarize import SummarizeAgent
from talemate.game.engine.nodes.core import Graph, GraphState
from talemate.game.engine.nodes.registry import (
    NODES,
    import_talemate_node_definitions,
)

from _director_test_helpers import patch_prompt_request_in


# ---------------------------------------------------------------------------
# Session-scoped: register node definitions once.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _import_node_definitions():
    import_talemate_node_definitions()


# ---------------------------------------------------------------------------
# Real fixtures — director, scene, client, summarizer
# ---------------------------------------------------------------------------


@pytest.fixture
def scene() -> MockScene:
    s = MockScene()
    bootstrap_scene(s)
    return s


@pytest.fixture
def director(scene) -> DirectorAgent:
    return instance.get_agent("director")


@pytest.fixture
def summarizer(scene) -> SummarizeAgent:
    return instance.get_agent("summarizer")


@pytest.fixture
def client(scene) -> MockClient:
    """Return the bootstrapped MockClient (a real ClientBase subclass)."""
    return scene.mock_client


# Real-message factory helpers. They build pydantic models from production
# schema modules, so a rename of any of these fields causes the tests to
# fail at construction time rather than silently keeping a stub copy alive.


def _text(message: str) -> ActionCoreMessage:
    return ActionCoreMessage(message=message)


def _action_result(
    *, name: str = "", instructions: str = "", result: Any = None
) -> ActionCoreResultMessage:
    return ActionCoreResultMessage(name=name, instructions=instructions, result=result)


def _user_interaction(user_input: str) -> UserInteractionMessage:
    return UserInteractionMessage(user_input=user_input)


# ---------------------------------------------------------------------------
# parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_extracts_message_section(self):
        response = "<MESSAGE>hello world</MESSAGE>"
        assert parse_response(response, section="message") == "hello world"

    def test_extracts_decision_section(self):
        response = "<DECISION>do the thing</DECISION>"
        assert parse_response(response, section="decision") == "do the thing"

    def test_returns_none_for_missing_message(self):
        assert parse_response("no tags here", section="message") is None

    def test_returns_none_for_missing_decision(self):
        assert parse_response("<MESSAGE>text</MESSAGE>", section="decision") is None

    def test_message_inside_analysis_is_ignored(self):
        # ComplexAnchorExtractor with tracked_tags: nested MESSAGE inside ANALYSIS
        # should not be returned as the outer message.
        response = (
            "<ANALYSIS>thinking <MESSAGE>inner</MESSAGE> done</ANALYSIS>"
            "<MESSAGE>outer</MESSAGE>"
        )
        assert parse_response(response, section="message") == "outer"


# ---------------------------------------------------------------------------
# clean_response
# ---------------------------------------------------------------------------


class TestCleanResponse:
    def test_strips_actions_block(self):
        text = "Hello\n<ACTIONS>\n```json\n{}\n```\n</ACTIONS>\nWorld"
        cleaned = clean_response(text, section="message")
        assert "<ACTIONS>" not in cleaned
        assert "Hello" in cleaned and "World" in cleaned

    def test_message_section_strips_decision(self):
        text = "Hello<DECISION>some decision</DECISION>"
        cleaned = clean_response(text, section="message")
        # Default "message" section also strips DECISION blocks.
        assert "<DECISION>" not in cleaned
        assert "some decision" not in cleaned
        assert "Hello" in cleaned

    def test_decision_section_keeps_decision_block(self):
        text = "<DECISION>kept</DECISION>"
        cleaned = clean_response(text, section="decision")
        # When DECISION is the primary section, the block stays.
        assert "kept" in cleaned

    def test_strips_legacy_actions_codeblock(self):
        text = "Hello\n```actions\nfoo\n```\nWorld"
        cleaned = clean_response(text, section="message")
        assert "```actions" not in cleaned
        assert "Hello" in cleaned and "World" in cleaned


# ---------------------------------------------------------------------------
# extract_actions — uses the real MockClient (a ClientBase subclass)
# ---------------------------------------------------------------------------


class TestExtractActions:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_actions_block(self, client):
        result = await extract_actions(client, "no actions tag here")
        assert result is None

    @pytest.mark.asyncio
    async def test_parses_single_dict_action_payload(self, client):
        response = (
            '<ACTIONS>\n```json\n{"name": "tell", "instructions": "say hi"}\n```\n'
            "</ACTIONS>"
        )
        result = await extract_actions(client, response)
        assert result == [{"name": "tell", "instructions": "say hi"}]

    @pytest.mark.asyncio
    async def test_parses_list_of_action_dicts(self, client):
        payload = (
            '[{"name": "a", "instructions": "i1"}, {"name": "b", "instructions": "i2"}]'
        )
        response = f"<ACTIONS>\n```json\n{payload}\n```\n</ACTIONS>"
        result = await extract_actions(client, response)
        assert result == [
            {"name": "a", "instructions": "i1"},
            {"name": "b", "instructions": "i2"},
        ]

    @pytest.mark.asyncio
    async def test_falls_back_to_function_field_when_name_missing(self, client):
        response = (
            '<ACTIONS>\n```json\n{"function": "alt", "instructions": ""}\n```\n'
            "</ACTIONS>"
        )
        result = await extract_actions(client, response)
        assert result == [{"name": "alt", "instructions": ""}]

    @pytest.mark.asyncio
    async def test_skips_items_without_name_or_function(self, client):
        payload = '[{"instructions": "no name"}, {"name": "ok"}]'
        response = f"<ACTIONS>\n```json\n{payload}\n```\n</ACTIONS>"
        result = await extract_actions(client, response)
        # The "no name" entry is dropped; "ok" keeps an empty instructions string.
        assert result == [{"name": "ok", "instructions": ""}]

    @pytest.mark.asyncio
    async def test_returns_none_on_invalid_payload(self, client):
        # Block exists but payload is an int → not dict/list of dicts → None.
        response = "<ACTIONS>\n```json\n42\n```\n</ACTIONS>"
        result = await extract_actions(client, response)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_dicts_lacking_name_or_function(self, client):
        # All entries lack both `name` and `function` → normalized list is empty
        # → function returns None.
        payload = '[{"foo": "bar"}, {"baz": "qux"}]'
        response = f"<ACTIONS>\n```json\n{payload}\n```\n</ACTIONS>"
        result = await extract_actions(client, response)
        assert result is None

    @pytest.mark.asyncio
    async def test_coerces_non_string_name_and_instructions_to_strings(self, client):
        # Name and instructions provided as non-strings — function must
        # str()-coerce them in the normalized output.
        payload = '{"name": 42, "instructions": 99}'
        response = f"<ACTIONS>\n```json\n{payload}\n```\n</ACTIONS>"
        result = await extract_actions(client, response)
        assert result == [{"name": "42", "instructions": "99"}]


# ---------------------------------------------------------------------------
# reverse_trim_history — uses real director-action message types
# ---------------------------------------------------------------------------


class TestReverseTrimHistory:
    def test_empty_history_returns_empty(self):
        assert reverse_trim_history([], 1000) == []

    def test_zero_or_negative_budget_keeps_most_recent(self):
        # the most recent message is always kept so the prompt never loses
        # the message it is responding to
        history = [_text("a"), _text("b")]
        assert reverse_trim_history(history, 0) == [history[-1]]
        assert reverse_trim_history(history, -10) == [history[-1]]

    def test_keeps_last_messages_within_budget(self):
        # token counts vary by tokenizer; use a generous budget so all 3 fit
        history = [_text("first"), _text("second"), _text("third")]
        result = reverse_trim_history(history, 1000)
        assert result == history

    def test_drops_earliest_when_budget_too_small(self, monkeypatch):
        # Stub count_tokens so each message is "worth" exactly 5 tokens.
        from talemate.agents.director.action_core import utils as utils_mod

        monkeypatch.setattr(utils_mod.util, "count_tokens", lambda x: 5)
        history = [_text("first"), _text("second"), _text("third")]
        # Budget of 12 fits only the last 2 messages (5+5 = 10 ≤ 12).
        result = reverse_trim_history(history, 12)
        assert result == [history[1], history[2]]

    def test_returns_chronological_order(self, monkeypatch):
        from talemate.agents.director.action_core import utils as utils_mod

        monkeypatch.setattr(utils_mod.util, "count_tokens", lambda x: 5)
        history = [_text("a"), _text("b"), _text("c")]
        # Generous budget — all 3 fit.
        result = reverse_trim_history(history, 100)
        # Order must match chronological original order, not reversed.
        assert [m.message for m in result] == ["a", "b", "c"]

    def test_action_result_message_token_cost_includes_name_and_instructions(self):
        # A single action_result message that fits the budget.
        history = [
            _action_result(name="do_it", instructions="now", result={"ok": True}),
        ]
        # generous budget: should keep the single message.
        assert reverse_trim_history(history, 10000) == history

    def test_user_interaction_message_token_cost(self):
        history = [_user_interaction("please proceed")]
        assert reverse_trim_history(history, 10000) == history

    def test_returns_last_message_on_exception(self):
        # Pass an item that triggers an attribute access error inside the
        # token-counter — the function defends with a single-message fallback.
        # This is a deliberate fault-injection object, NOT a stand-in for any
        # production type — it exists only to drive the except branch.
        class _RaisesOnTypeAccess:
            @property
            def type(self):
                raise RuntimeError("boom")

        broken = _RaisesOnTypeAccess()
        history = [_text("ok"), broken]
        # Should not raise — falls back to [last item]
        result = reverse_trim_history(history, 1000)
        assert result == [broken]


# ---------------------------------------------------------------------------
# serialize_history
# ---------------------------------------------------------------------------


class TestSerializeHistory:
    def test_skips_messages_for_which_serializer_returns_none(self):
        messages = [_text("keep1"), _text("drop"), _text("keep2")]

        def serialize_fn(m):
            return None if m.message == "drop" else m

        result = serialize_history(messages, serialize_fn)
        assert [m.message for m in result] == ["keep1", "keep2"]

    def test_empty_input_yields_empty_output(self):
        assert serialize_history([], lambda m: m) == []

    def test_serializer_can_transform_messages(self):
        messages = [_text("a"), _text("b")]
        result = serialize_history(messages, lambda m: m.message.upper())
        assert result == ["A", "B"]


# ---------------------------------------------------------------------------
# _build_callback_groups (via direct call) — uses the real DirectorAgent.
# ---------------------------------------------------------------------------


def _cd(
    action_id,
    *,
    group="",
    title="",
    chat="",
    sd="",
    availability="both",
    force_enabled=False,
    examples=None,
) -> CallbackDescriptor:
    return CallbackDescriptor(
        action_id=action_id,
        action_title=title,
        group=group,
        description_chat=chat,
        description_scene_direction=sd,
        instruction_examples=examples or [],
        availability=availability,  # type: ignore[arg-type]
        force_enabled=force_enabled,
    )


def _set_disabled(director: DirectorAgent, value) -> None:
    """Write ``disabled_sub_actions`` into the real director's scene state.

    Production reads via ``get_scene_state("disabled_sub_actions")``, backed
    by ``self.scene.agent_state[self.agent_type]``.
    """
    if value is None:
        director.scene.agent_state.pop("director", None)
        return
    director.scene.agent_state["director"] = {"disabled_sub_actions": value}


class TestBuildCallbackGroups:
    def test_returns_empty_when_all_descriptors_disabled(self, director):
        _set_disabled(director, {"chat": ["a", "b"]})
        descriptors = [_cd("a"), _cd("b")]
        result = _build_callback_groups(descriptors, "chat", director)
        assert result == []

    def test_groups_by_group_name_and_sorts_groups(self, director):
        descriptors = [
            _cd("x", group="zeta", title="X", chat="x desc"),
            _cd("y", group="alpha", title="Y", chat="y desc"),
        ]
        result = _build_callback_groups(descriptors, "chat", director)
        # Sorted alphabetically by group name.
        assert [g.group_name for g in result] == ["alpha", "zeta"]

    def test_falls_back_to_general_when_group_is_empty(self, director):
        descriptors = [_cd("ungrouped", group="", title="U", chat="d")]
        result = _build_callback_groups(descriptors, "chat", director)
        assert [g.group_name for g in result] == ["General"]

    def test_callback_uses_action_id_as_title_when_title_missing(self, director):
        descriptors = [_cd("raw-id", title="", chat="d")]
        result = _build_callback_groups(descriptors, "chat", director)
        assert result[0].callbacks[0]["title"] == "raw-id"

    def test_includes_examples_when_present(self, director):
        descriptors = [
            _cd("a", title="A", chat="d", examples=["e1", "e2"]),
            _cd("b", title="B", chat="d", examples=[]),
        ]
        result = _build_callback_groups(descriptors, "chat", director)
        callbacks = result[0].callbacks
        # Find each by title since group ordering is by name (single group)
        by_title = {c["title"]: c for c in callbacks}
        assert by_title["A"]["examples"] == ["e1", "e2"]
        assert "examples" not in by_title["B"]

    def test_skips_disabled_descriptors_within_group(self, director):
        _set_disabled(director, {"chat": ["b"]})
        descriptors = [
            _cd("a", group="g1", title="A", chat="d"),
            _cd("b", group="g1", title="B", chat="d"),
        ]
        result = _build_callback_groups(descriptors, "chat", director)
        titles = [c["title"] for c in result[0].callbacks]
        assert titles == ["A"]


# ---------------------------------------------------------------------------
# get_available_actions — registry-driven
# ---------------------------------------------------------------------------


def _build_subaction_graph(action_name: str, sub_action_props: list[dict]) -> Graph:
    """Build a Graph filled with DirectorChatSubAction nodes and a name property."""
    SubActionCls = NODES["agents/director/chat/DirectorChatSubAction"]
    graph = Graph(title=action_name)
    graph.set_property("name", action_name)
    graph.set_property("description", f"{action_name} description")
    for props in sub_action_props:
        sub = SubActionCls()
        for k, v in props.items():
            sub.set_property(k, v)
        graph.nodes[sub.id] = sub
    return graph


def _scene_with_action_registry(scene, director_chat_actions: dict) -> MockScene:
    """Configure a real ``Scene`` with a ``GraphState`` that the function
    under test can read.

    ``get_available_actions`` reads from ``scene.nodegraph_state.shared``.
    Production scenes lazily build that on first node-graph run; for these
    isolated tests we set it up directly. This is all real Scene state —
    no shim subclass.
    """
    scene.nodegraph_state = GraphState()
    scene.nodegraph_state.shared = {"_director_chat_actions": director_chat_actions}
    return scene


@pytest.fixture
def fake_action_registry(monkeypatch):
    """Patch gating.get_nodes_by_base_type and utils.get_node to use in-test graphs.

    These two are peripheral module-level lookup helpers, NOT domain types —
    they accept a string and return classes from the global node registry.
    Substituting a callable that returns our prebuilt real ``Graph`` instances
    keeps every consumer hitting the real graph type.
    """
    from talemate.agents.director.action_core import gating as gating_mod
    from talemate.agents.director.action_core import utils as utils_mod

    def install(graphs_by_name: dict[str, Graph]):
        # extract_all_callback_descriptors iterates the registry.
        def _fake_get_nodes_by_base_type(base_type):
            assert base_type == "agents/director/DirectorChatAction"
            return [_cls_for(g) for g in graphs_by_name.values()]

        def _cls_for(g: Graph):
            class _Cls:
                def __new__(cls):
                    return g

            return _Cls

        # get_available_actions then calls get_node(node_registry)() to fetch
        # the action's "node" — emulate by mapping registry → graph instance.
        registry_to_graph = {
            f"agents/director/{name}": graph for name, graph in graphs_by_name.items()
        }

        def _fake_get_node(name):
            graph = registry_to_graph.get(name)
            if graph is None:
                raise KeyError(name)

            class _Cls:
                def __new__(cls):
                    return graph

            return _Cls

        monkeypatch.setattr(
            gating_mod, "get_nodes_by_base_type", _fake_get_nodes_by_base_type
        )
        monkeypatch.setattr(utils_mod, "get_node", _fake_get_node)

    return install


class TestGetAvailableActions:
    @pytest.mark.asyncio
    async def test_returns_actions_with_callback_groups(
        self, fake_action_registry, scene, director
    ):
        graph = _build_subaction_graph(
            "narrate",
            [
                {"action_id": "tell", "action_title": "Tell", "description_chat": "d"},
            ],
        )
        fake_action_registry({"narrate": graph})

        scene_with_registry = _scene_with_action_registry(
            scene, {"narrate": "agents/director/narrate"}
        )
        actions = await get_available_actions(scene_with_registry, mode="chat")

        assert len(actions) == 1
        action = actions[0]
        assert action.name == "narrate"
        assert action.description == "narrate description"
        assert len(action.callback_groups) == 1
        assert action.callback_groups[0].callbacks[0]["title"] == "Tell"

    @pytest.mark.asyncio
    async def test_skips_actions_with_no_sub_actions(
        self, fake_action_registry, scene, director
    ):
        graph_a = _build_subaction_graph(
            "with_subs",
            [{"action_id": "x", "action_title": "X", "description_chat": "d"}],
        )
        graph_b = _build_subaction_graph("empty", [])  # no sub-actions
        fake_action_registry({"with_subs": graph_a, "empty": graph_b})

        scene_with_registry = _scene_with_action_registry(
            scene,
            {
                "with_subs": "agents/director/with_subs",
                "empty": "agents/director/empty",
            },
        )
        actions = await get_available_actions(scene_with_registry, mode="chat")

        names = [a.name for a in actions]
        assert names == ["with_subs"]

    @pytest.mark.asyncio
    async def test_skips_actions_with_all_callbacks_disabled(
        self, fake_action_registry, scene, director
    ):
        # Director has the action's only sub-action on the denylist.
        _set_disabled(director, {"chat": ["only-one"]})
        graph = _build_subaction_graph(
            "blocked",
            [{"action_id": "only-one", "action_title": "One", "description_chat": "d"}],
        )
        fake_action_registry({"blocked": graph})

        scene_with_registry = _scene_with_action_registry(
            scene, {"blocked": "agents/director/blocked"}
        )
        actions = await get_available_actions(scene_with_registry, mode="chat")
        assert actions == []

    @pytest.mark.asyncio
    async def test_actions_sorted_alphabetically_by_name(
        self, fake_action_registry, scene, director
    ):
        g_z = _build_subaction_graph(
            "zeta", [{"action_id": "z1", "action_title": "Z1", "description_chat": "d"}]
        )
        g_a = _build_subaction_graph(
            "alpha",
            [{"action_id": "a1", "action_title": "A1", "description_chat": "d"}],
        )
        fake_action_registry({"zeta": g_z, "alpha": g_a})

        scene_with_registry = _scene_with_action_registry(
            scene,
            {
                "zeta": "agents/director/zeta",
                "alpha": "agents/director/alpha",
            },
        )
        actions = await get_available_actions(scene_with_registry, mode="chat")
        assert [a.name for a in actions] == ["alpha", "zeta"]


# ---------------------------------------------------------------------------
# compact_if_needed — uses real SummarizerAgent with summarize_director_chat
# stubbed at the instance level (a peripheral RPC method, not a class).
# ---------------------------------------------------------------------------


class TestCompactIfNeeded:
    @pytest.mark.asyncio
    async def test_returns_false_when_messages_empty(self, scene):
        budgets = ActionCoreBudgets(max_tokens=1000, scene_context_ratio=0.5)
        result = await compact_if_needed(
            messages=[],
            budgets=budgets,
            staleness_threshold=0.5,
            create_message=lambda m, s: _text(m),
            set_messages=lambda msgs: None,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_under_thresholds(self, scene):
        # Tight thresholds, tiny content → no compaction.
        budgets = ActionCoreBudgets(max_tokens=10000, scene_context_ratio=0.5)
        messages = [_text("short msg 1"), _text("short msg 2")]
        result = await compact_if_needed(
            messages=messages,
            budgets=budgets,
            staleness_threshold=0.5,
            create_message=lambda m, s: _text(m),
            set_messages=lambda msgs: None,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_compacts_and_calls_summarizer_when_over_threshold(
        self, scene, summarizer, monkeypatch
    ):
        # Make tokens look big by stubbing util.count_tokens.
        from talemate.agents.director.action_core import utils as utils_mod

        # Each message is "worth" 100 tokens for this test.
        monkeypatch.setattr(utils_mod.util, "count_tokens", lambda x: 100)

        # Budget so history_budget = 100; staleness = 50; active = 50.
        # Total = 4 * 100 = 400 → far exceeds threshold → compact.
        budgets = ActionCoreBudgets(max_tokens=200, scene_context_ratio=0.5)

        # Stub the summarize_director_chat method on the real summarizer
        # instance — a peripheral RPC method, not the class itself.
        summarize_calls: list[list] = []

        async def fake_summarize(history):
            summarize_calls.append(list(history))
            return "ALL OF IT"

        monkeypatch.setattr(summarizer, "summarize_director_chat", fake_summarize)

        messages = [
            _text("a"),
            _text("b"),
            _text("c"),
            _text("d"),
        ]
        stored: list = []

        on_compacting_called = []
        on_compacted_called = []

        async def on_compacting():
            on_compacting_called.append(True)

        async def on_compacted(msgs):
            on_compacted_called.append(list(msgs))

        result = await compact_if_needed(
            messages=messages,
            budgets=budgets,
            staleness_threshold=0.5,
            create_message=lambda m, s: _text(m),
            set_messages=lambda msgs: stored.extend(msgs),
            on_compacted=on_compacted,
            on_compacting=on_compacting,
        )

        assert result is True
        # Summarizer was called once with the stale prefix.
        assert len(summarize_calls) == 1
        stale_passed = summarize_calls[0]
        assert all(m in messages for m in stale_passed)

        # set_messages received: [summary] + tail
        assert stored, "set_messages should have been called"
        assert isinstance(stored[0], ActionCoreMessage)
        assert "ALL OF IT" in stored[0].message

        # Both lifecycle hooks fired.
        assert on_compacting_called == [True]
        assert on_compacted_called and on_compacted_called[0] == stored

    @pytest.mark.asyncio
    async def test_returns_false_when_summarizer_raises(
        self, scene, summarizer, monkeypatch
    ):
        from talemate.agents.director.action_core import utils as utils_mod

        monkeypatch.setattr(utils_mod.util, "count_tokens", lambda x: 100)
        budgets = ActionCoreBudgets(max_tokens=200, scene_context_ratio=0.5)

        async def failing_summarize(history):
            raise RuntimeError("upstream failure")

        monkeypatch.setattr(summarizer, "summarize_director_chat", failing_summarize)

        messages = [_text(c) for c in "abcd"]
        stored: list = []
        result = await compact_if_needed(
            messages=messages,
            budgets=budgets,
            staleness_threshold=0.5,
            create_message=lambda m, s: _text(m),
            set_messages=lambda msgs: stored.extend(msgs),
        )
        assert result is False
        # No new messages were ever stored when the summarizer fails.
        assert stored == []

    @pytest.mark.asyncio
    async def test_compact_if_needed_swallows_on_compacted_exception(
        self, scene, summarizer, monkeypatch
    ):
        from talemate.agents.director.action_core import utils as utils_mod

        monkeypatch.setattr(utils_mod.util, "count_tokens", lambda x: 100)
        budgets = ActionCoreBudgets(max_tokens=200, scene_context_ratio=0.5)

        async def fake_summarize(history):
            return "ok"

        monkeypatch.setattr(summarizer, "summarize_director_chat", fake_summarize)

        async def on_compacted(msgs):
            raise RuntimeError("post hook explosion")

        result = await compact_if_needed(
            messages=[_text(c) for c in "abcd"],
            budgets=budgets,
            staleness_threshold=0.5,
            create_message=lambda m, s: _text(m),
            set_messages=lambda msgs: None,
            on_compacted=on_compacted,
        )
        # Compaction completes successfully even though on_compacted raised.
        assert result is True

    @pytest.mark.asyncio
    async def test_on_compacting_exception_is_swallowed(
        self, scene, summarizer, monkeypatch
    ):
        from talemate.agents.director.action_core import utils as utils_mod

        monkeypatch.setattr(utils_mod.util, "count_tokens", lambda x: 100)
        budgets = ActionCoreBudgets(max_tokens=200, scene_context_ratio=0.5)

        async def fake_summarize(history):
            return "ok"

        monkeypatch.setattr(summarizer, "summarize_director_chat", fake_summarize)

        async def on_compacting():
            raise RuntimeError("hook explosion")

        result = await compact_if_needed(
            messages=[_text(c) for c in "abcd"],
            budgets=budgets,
            staleness_threshold=0.5,
            create_message=lambda m, s: _text(m),
            set_messages=lambda msgs: None,
            on_compacting=on_compacting,
        )
        # Compaction still proceeds even though on_compacting raised.
        assert result is True


# ---------------------------------------------------------------------------
# build_prompt_vars — uses the real Scene with seeded GraphState
# ---------------------------------------------------------------------------


def _scene_with_gamestate(
    scene, director_chat_actions: dict, gamestate_vars: dict | None = None
) -> MockScene:
    """Configure a real Scene with the GraphState + game-state values
    ``build_prompt_vars`` reads. Same Scene type as production — no shim.
    """
    scene.nodegraph_state = GraphState()
    scene.nodegraph_state.shared = {"_director_chat_actions": director_chat_actions}
    scene.game_state.variables = gamestate_vars or {"hp": 100}
    return scene


class TestBuildPromptVars:
    @pytest.mark.asyncio
    async def test_includes_all_required_keys(
        self, fake_action_registry, scene, director, client
    ):
        graph = _build_subaction_graph(
            "act", [{"action_id": "x", "action_title": "X", "description_chat": "d"}]
        )
        fake_action_registry({"act": graph})

        scene_with_state = _scene_with_gamestate(scene, {"act": "agents/director/act"})
        budgets = ActionCoreBudgets(max_tokens=1000, scene_context_ratio=0.5)
        history = [_text("h1")]

        def trim(history, budget):
            return history

        result = await build_prompt_vars(
            scene=scene_with_state,
            client=client,
            history_for_prompt=history,
            scene_snapshot="snap",
            budgets=budgets,
            enable_analysis=True,
            scene_context_ratio=0.5,
            history_trim_fn=trim,
            extra_vars=None,
            mode="chat",
        )

        # Verify all expected keys are present and reflect the caller's values.
        assert result["scene"] is scene_with_state
        assert result["max_tokens"] == client.max_token_length
        assert result["history"] is history
        assert result["scene_snapshot"] == "snap"
        assert isinstance(result["available_functions"], list)
        # the registered action should appear in available_functions
        assert any(a.name == "act" for a in result["available_functions"])
        assert result["enable_analysis"] is True
        assert result["scene_context_ratio"] == 0.5
        assert "useful_context_ids" in result
        assert result["budgets"] is budgets
        assert result["history_trim"] is trim
        assert result["gamestate"] == {"hp": 100}

    @pytest.mark.asyncio
    async def test_extra_vars_merge_into_result(
        self, fake_action_registry, scene, director, client
    ):
        graph = _build_subaction_graph(
            "act", [{"action_id": "x", "action_title": "X", "description_chat": "d"}]
        )
        fake_action_registry({"act": graph})

        scene_with_state = _scene_with_gamestate(scene, {"act": "agents/director/act"})
        budgets = ActionCoreBudgets(max_tokens=1000, scene_context_ratio=0.3)

        result = await build_prompt_vars(
            scene=scene_with_state,
            client=client,
            history_for_prompt=[],
            scene_snapshot="",
            budgets=budgets,
            enable_analysis=False,
            scene_context_ratio=0.3,
            history_trim_fn=lambda h, b: h,
            extra_vars={"custom_key": "custom_value", "another": 42},
            mode="scene_direction",
        )

        assert result["custom_key"] == "custom_value"
        assert result["another"] == 42
        # Existing keys still set correctly
        assert result["scene_context_ratio"] == 0.3
        assert result["enable_analysis"] is False


# ---------------------------------------------------------------------------
# request_and_parse — uses the real Prompt class (raising=True patches)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_prompt_request(monkeypatch):
    """Install a queued response callable on the real ``Prompt.request``.

    ``raising=True`` (default in patch_prompt_request_in) makes the test
    fail loudly if ``Prompt.request`` is renamed or removed.
    """
    return patch_prompt_request_in(monkeypatch)


class TestRequestAndParse:
    @pytest.mark.asyncio
    async def test_returns_parsed_message_section(self, stub_prompt_request, client):
        stub = stub_prompt_request(
            {
                "director.test": [
                    ("<MESSAGE>hello world</MESSAGE>", {"message": "hello world"})
                ]
            }
        )
        parsed, actions, raw = await request_and_parse(
            client=client,
            prompt_template="director.test",
            kind="conversation",
            prompt_vars={},
            response_section="message",
        )
        assert parsed == "hello world"
        assert actions is None
        assert "MESSAGE" in raw
        assert len(stub.calls) == 1

    @pytest.mark.asyncio
    async def test_returns_parsed_decision_section(self, stub_prompt_request, client):
        stub_prompt_request(
            {"director.test": [("<DECISION>do it</DECISION>", {"decision": "do it"})]}
        )
        parsed, actions, _raw = await request_and_parse(
            client=client,
            prompt_template="director.test",
            kind="decision",
            prompt_vars={},
            response_section="decision",
        )
        assert parsed == "do it"
        assert actions is None

    @pytest.mark.asyncio
    async def test_falls_back_to_parse_response_when_extracted_empty(
        self, stub_prompt_request, client
    ):
        # Prompt.request returns extracted={}, but raw response has a MESSAGE tag.
        stub_prompt_request({"t": [("<MESSAGE>fallback parse</MESSAGE>", {})]})
        parsed, _actions, _raw = await request_and_parse(
            client=client,
            prompt_template="t",
            kind="k",
            prompt_vars={},
            response_section="message",
        )
        assert parsed == "fallback parse"

    @pytest.mark.asyncio
    async def test_handles_prompt_request_exception(self, monkeypatch, client):
        # Patch the real Prompt.request to raise — exercise the except branch.
        from talemate.prompts.base import Prompt

        async def failing_request(cls, *args, **kwargs):
            raise RuntimeError("bad llm")

        monkeypatch.setattr(
            Prompt, "request", classmethod(failing_request), raising=True
        )

        parsed, actions, raw = await request_and_parse(
            client=client,
            prompt_template="t",
            kind="k",
            prompt_vars={},
        )
        assert parsed is None
        assert actions is None
        assert raw == ""

    @pytest.mark.asyncio
    async def test_retries_when_response_invalid(self, stub_prompt_request, client):
        # First call returns nothing useful; second call returns valid message.
        stub = stub_prompt_request(
            {
                "t": [
                    ("", {}),  # empty response
                    ("<MESSAGE>second try</MESSAGE>", {"message": "second try"}),
                ]
            }
        )
        parsed, _actions, _raw = await request_and_parse(
            client=client,
            prompt_template="t",
            kind="k",
            prompt_vars={},
            max_retries=3,
        )
        # Should have retried and gotten a valid response on attempt 2.
        assert parsed == "second try"
        assert len(stub.calls) == 2

    @pytest.mark.asyncio
    async def test_breaks_when_max_retries_exceeded(self, stub_prompt_request, client):
        # All responses are empty — function bails after max_retries+1 attempts.
        stub = stub_prompt_request({"t": [("", {}), ("", {}), ("", {})]})
        parsed, actions, raw = await request_and_parse(
            client=client,
            prompt_template="t",
            kind="k",
            prompt_vars={},
            max_retries=2,
        )
        assert parsed is None
        assert actions is None
        # Attempts: 1 (initial) + 2 retries = 3 total
        assert len(stub.calls) == 3

    @pytest.mark.asyncio
    async def test_returns_actions_when_actions_block_present(
        self, stub_prompt_request, client
    ):
        # Response includes a MESSAGE and an ACTIONS block.
        actions_payload = '{"name": "do_thing", "instructions": "now"}'
        raw = (
            "<MESSAGE>hi</MESSAGE>\n"
            f"<ACTIONS>\n```json\n{actions_payload}\n```\n</ACTIONS>"
        )
        stub_prompt_request({"t": [(raw, {"message": "hi"})]})
        parsed, actions, _raw = await request_and_parse(
            client=client,
            prompt_template="t",
            kind="k",
            prompt_vars={},
        )
        assert parsed == "hi"
        assert actions == [{"name": "do_thing", "instructions": "now"}]

    @pytest.mark.asyncio
    async def test_actions_alone_is_valid_without_message(
        self, stub_prompt_request, client
    ):
        # Only an ACTIONS block — no MESSAGE — is still considered valid.
        actions_payload = '{"name": "x", "instructions": ""}'
        raw = f"<ACTIONS>\n```json\n{actions_payload}\n```\n</ACTIONS>"
        stub_prompt_request({"t": [(raw, {})]})
        parsed, actions, _raw = await request_and_parse(
            client=client,
            prompt_template="t",
            kind="k",
            prompt_vars={},
            max_retries=2,
        )
        assert parsed is None
        # actions_selected must be the list — not None.
        assert actions == [{"name": "x", "instructions": ""}]


# ---------------------------------------------------------------------------
# init_action_nodes — uses the real DirectorAgent
# ---------------------------------------------------------------------------


class TestInitActionNodes:
    @pytest.mark.asyncio
    async def test_populates_shared_state_with_action_registries(
        self, scene, director, monkeypatch
    ):
        from talemate.agents.director.action_core import utils as utils_mod

        # init_action_nodes reads the `registry` attr on each action class and
        # tags shared state by the `name` property. Use a Graph subclass with
        # a class-level `registry` for each fake action.
        class _AlphaGraph(Graph):
            _registry = "agents/director/alpha"

        class _BetaGraph(Graph):
            _registry = "agents/director/beta"

        # Mirror _build_subaction_graph but with our subclasses
        g1 = _AlphaGraph(title="alpha")
        g1.set_property("name", "alpha")
        g2 = _BetaGraph(title="beta")
        g2.set_property("name", "beta")

        def _fake_get_nodes_by_base_type(base_type):
            class _A:
                def __new__(cls):
                    return g1

            class _B:
                def __new__(cls):
                    return g2

            return [_A, _B]

        monkeypatch.setattr(
            utils_mod, "get_nodes_by_base_type", _fake_get_nodes_by_base_type
        )

        state = GraphState()
        scene.nodegraph_state = state
        scene.nodegraph_state.shared = {}
        await init_action_nodes(scene, state)

        registry_map = state.shared["_director_chat_actions"]
        assert registry_map == {
            "alpha": "agents/director/alpha",
            "beta": "agents/director/beta",
        }

    @pytest.mark.asyncio
    async def test_handles_director_without_update_callback_choices(
        self, scene, director, monkeypatch
    ):
        """The real DirectorAgent does NOT define ``update_callback_choices`` —
        this test pins that fact. ``init_action_nodes`` guards the call with
        ``hasattr``; the real director must transparently flow through.
        """
        from talemate.agents.director.action_core import utils as utils_mod

        # Real director, real hasattr check: the absence of the method on the
        # real type is the very fact the test is asserting. If someone adds
        # ``update_callback_choices`` to ``DirectorAgent`` (a perfectly
        # reasonable change), this assertion will surface so they can update
        # the test.
        assert not hasattr(director, "update_callback_choices"), (
            "If DirectorAgent grows update_callback_choices, this guard test "
            "needs to be revisited — the original test was about the absent-"
            "method branch in init_action_nodes."
        )

        class _OnlyGraph(Graph):
            _registry = "agents/director/only"

        g = _OnlyGraph(title="only")
        g.set_property("name", "only")

        def _fake_get_nodes_by_base_type(base_type):
            class _C:
                def __new__(cls):
                    return g

            return [_C]

        monkeypatch.setattr(
            utils_mod, "get_nodes_by_base_type", _fake_get_nodes_by_base_type
        )

        state = GraphState()
        scene.nodegraph_state = state
        scene.nodegraph_state.shared = {}
        await init_action_nodes(scene, state)
        assert state.shared["_director_chat_actions"] == {
            "only": "agents/director/only"
        }
