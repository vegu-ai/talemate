"""
Tests for the scene state reset functionality.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from conftest import MockScene, bootstrap_scene

from talemate.server.world_state_manager.scene_state_reset import (
    SceneStateResetMixin,
)
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.schema import Fact, FactAnchor, KnowledgeEdge
from talemate.scene_message import CharacterMessage
from talemate.world_state import Reinforcement


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scene_factory():
    """Factory that builds a real bootstrapped `MockScene` with state populated.

    Uses production `Scene`/`MockScene`, `WorldState`, `SceneIntent`,
    `Reinforcement`. Bootstraps the agent slate so `world_state.remove_reinforcement`
    can resolve `instance.get_agent('world_state')` for real. Peripheral RPC
    methods (commit_to_memory, emit_history, emit_status, world_state.emit)
    are stubbed because they call into agents/signals that aren't the unit
    under test here.
    """

    def _factory(
        history=None,
        archived_history=None,
        layered_history=None,
        agent_state=None,
        reinforcements=None,
    ):
        scene = MockScene()
        bootstrap_scene(scene)

        scene.history = history if history is not None else []
        scene.archived_history = (
            archived_history if archived_history is not None else []
        )
        scene.layered_history = layered_history if layered_history is not None else []
        scene.agent_state = agent_state if agent_state is not None else {}

        # Pre-populate intent_state to a phase the test can verify gets reset.
        from talemate.scene.schema import ScenePhase

        if scene.intent_state.phase is None:
            scene.intent_state.phase = ScenePhase(scene_type="test")
        scene.intent_state.start = 10

        # Real WorldState already on scene; populate reinforce list.
        scene.world_state.reinforce = list(reinforcements) if reinforcements else []

        # Peripheral plumbing: stub the RPC-style emit/commit methods.
        scene.commit_to_memory = AsyncMock()
        scene.emit_history = AsyncMock()
        scene.emit_status = MagicMock()

        return scene

    return _factory


@pytest.fixture(autouse=True)
def _stub_world_state_emit(monkeypatch):
    """Silence WorldState.emit (signal-firing) for every test.

    Patched on the class because pydantic v2 forbids instance-level method
    assignment.
    """
    from talemate.world_state import WorldState

    monkeypatch.setattr(WorldState, "emit", lambda self, status="update": None)


@pytest.fixture
def reinforcement_factory():
    """Build real `Reinforcement` instances.

    Using the real pydantic model so any rename/removal on Reinforcement
    fields breaks these tests.
    """

    def _factory(question, character=None):
        return Reinforcement(question=question, character=character)

    return _factory


@pytest.fixture
def mixin_instance():
    """Create an instance of SceneStateResetMixin with stubbed websocket plumbing.

    The websocket_handler / signal_operation_done are peripheral plumbing
    the mixin happens to call — not domain types. MagicMock is appropriate.
    """

    class TestMixin(SceneStateResetMixin):
        def __init__(self, scene):
            self._scene = scene
            self.websocket_handler = MagicMock()
            self._signal_done_called = False

        @property
        def scene(self):
            return self._scene

        async def signal_operation_done(self):
            self._signal_done_called = True

    def _factory(scene):
        return TestMixin(scene)

    return _factory


# ---------------------------------------------------------------------------
# Tests: History Wipe
# ---------------------------------------------------------------------------


class TestHistoryWipe:
    @pytest.mark.asyncio
    async def test_wipe_all_history_including_static(
        self, scene_factory, mixin_instance
    ):
        """Wipe all history including static entries."""
        scene = scene_factory(
            history=[{"text": "msg1"}, {"text": "msg2"}],
            archived_history=[
                {"text": "arch1", "end": 5},  # dynamic
                {"text": "arch2", "end": None},  # static
            ],
            layered_history=[["layer1"], ["layer2"]],
        )
        scene.start_ts = 3600
        scene.ts = 7200
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "wipe_history": True,
                "wipe_history_include_static": True,
            }
        )

        assert scene.history == []
        assert scene.archived_history == []
        assert scene.layered_history == []
        # no static entry is left to be older than the scene
        assert (scene.start_ts, scene.ts) == (0, 0)

    @pytest.mark.asyncio
    async def test_wipe_all_history_removes_static_entry_facts(
        self, scene_factory, mixin_instance, monkeypatch
    ):
        """A wipe that includes static entries removes the facts they recorded."""
        scene = scene_factory(
            archived_history=[
                {"id": "world-1", "text": "Static entry", "end": None},
            ]
        )
        scene.world_state.facts = {
            "F1": Fact(id="F1", text="Static fact", archive_id="world-1"),
            "F2": Fact(id="F2", text="Manual fact", source="manual"),
        }
        # a hand grant keeps F1 through the loss of one line, not through the
        # wipe of the entry it came from
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F1", source="manual"),
        ]
        memory = get_agent("memory")
        monkeypatch.setattr(memory, "delete", AsyncMock())

        await mixin_instance(scene).handle_execute_scene_state_reset(
            {
                "wipe_history": True,
                "wipe_history_include_static": True,
            }
        )

        assert scene.archived_history == []
        assert set(scene.world_state.facts) == {"F2"}
        assert scene.world_state.knowledge == []
        memory.delete.assert_awaited_once_with({"ids": ["F1"]})

    @pytest.mark.asyncio
    async def test_wipe_all_history_keeps_an_author_edited_static_fact(
        self, scene_factory, mixin_instance, monkeypatch
    ):
        """An author-edited fact outlives the static entry it came from."""
        scene = scene_factory(
            archived_history=[
                {"id": "world-1", "text": "Static entry", "end": None},
            ]
        )
        scene.world_state.facts = {
            "F3": Fact(
                id="F3",
                text="Edited fact",
                archive_id="world-1",
                text_edited=True,
            ),
        }
        memory = get_agent("memory")
        monkeypatch.setattr(memory, "delete", AsyncMock())

        await mixin_instance(scene).handle_execute_scene_state_reset(
            {
                "wipe_history": True,
                "wipe_history_include_static": True,
            }
        )

        assert scene.archived_history == []
        (fact,) = scene.world_state.facts.values()
        assert (fact.source, fact.archive_id) == ("manual", None)
        memory.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wipe_all_history_drops_a_rule_anchored_on_a_static_entry(
        self, scene_factory, mixin_instance, monkeypatch
    ):
        """A rule that waits on a wiped static entry goes with the entry."""
        scene = scene_factory(
            archived_history=[
                {"id": "world-1", "text": "Static entry", "end": None},
            ]
        )
        scene.world_state.knowledge = [
            KnowledgeEdge(
                character="Edwin",
                target="F9",
                source="manual",
                anchor=FactAnchor(text="A missing statement", archive_id="world-1"),
            ),
        ]
        memory = get_agent("memory")
        monkeypatch.setattr(memory, "delete", AsyncMock())

        await mixin_instance(scene).handle_execute_scene_state_reset(
            {
                "wipe_history": True,
                "wipe_history_include_static": True,
            }
        )

        assert scene.world_state.knowledge == []

    @pytest.mark.asyncio
    async def test_wipe_history_without_static_keeps_static_entry_facts(
        self, scene_factory, mixin_instance, monkeypatch
    ):
        """Keeping the static entries keeps the facts they recorded."""
        scene = scene_factory(
            archived_history=[
                {"id": "world-1", "text": "Static entry", "end": None},
            ]
        )
        scene.world_state.facts = {
            "F1": Fact(id="F1", text="Static fact", archive_id="world-1"),
        }
        memory = get_agent("memory")
        monkeypatch.setattr(memory, "delete", AsyncMock())

        await mixin_instance(scene).handle_execute_scene_state_reset(
            {
                "wipe_history": True,
                "wipe_history_include_static": False,
            }
        )

        assert len(scene.archived_history) == 1
        assert set(scene.world_state.facts) == {"F1"}
        memory.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wipe_history_preserve_static(self, scene_factory, mixin_instance):
        """Wipe history but preserve static archived entries."""
        scene = scene_factory(
            history=[{"text": "msg1"}],
            archived_history=[
                {"text": "arch1", "end": 5},  # dynamic - should be removed
                {"text": "arch2", "end": None},  # static - should be kept
                {"text": "arch3", "end": 10},  # dynamic - should be removed
            ],
            layered_history=[["layer1"]],
        )
        scene.start_ts = 3600
        scene.ts = 7200
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "wipe_history": True,
                "wipe_history_include_static": False,
            }
        )

        assert scene.history == []
        assert len(scene.archived_history) == 1
        assert scene.archived_history[0]["text"] == "arch2"
        assert scene.layered_history == []
        # the static entry keeps its distance from the scene start
        assert (scene.start_ts, scene.ts) == (3600, 3600)

    @pytest.mark.asyncio
    async def test_wipe_history_no_static_entries(self, scene_factory, mixin_instance):
        """Wipe history when there are no static entries."""
        scene = scene_factory(
            history=[{"text": "msg1"}],
            archived_history=[
                {"text": "arch1", "end": 5},
                {"text": "arch2", "end": 10},
            ],
            layered_history=[],
        )
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "wipe_history": True,
                "wipe_history_include_static": False,
            }
        )

        assert scene.history == []
        assert scene.archived_history == []


# ---------------------------------------------------------------------------
# Tests: Agent State Reset
# ---------------------------------------------------------------------------


class TestAgentStateReset:
    @pytest.mark.asyncio
    async def test_reset_entire_agent(self, scene_factory, mixin_instance):
        """Reset all state for a specific agent."""
        scene = scene_factory(
            agent_state={
                "director": {"scene_direction": {"data": 1}, "chat": {"data": 2}},
                "summarizer": {"cache": {"data": 3}},
            }
        )
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "reset_agent_states": {"director": True},
            }
        )

        assert "director" not in scene.agent_state
        assert "summarizer" in scene.agent_state
        assert scene.agent_state["summarizer"]["cache"] == {"data": 3}

    @pytest.mark.asyncio
    async def test_reset_specific_keys(self, scene_factory, mixin_instance):
        """Reset specific keys within an agent."""
        scene = scene_factory(
            agent_state={
                "director": {
                    "scene_direction": {"data": 1},
                    "chat": {"data": 2},
                    "other": {"data": 3},
                }
            }
        )
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "reset_agent_states": {"director": ["scene_direction", "chat"]},
            }
        )

        assert "director" in scene.agent_state
        assert "scene_direction" not in scene.agent_state["director"]
        assert "chat" not in scene.agent_state["director"]
        assert "other" in scene.agent_state["director"]

    @pytest.mark.asyncio
    async def test_reset_all_keys_removes_agent(self, scene_factory, mixin_instance):
        """Resetting all keys of an agent should remove the agent entry."""
        scene = scene_factory(
            agent_state={
                "director": {"scene_direction": {"data": 1}},
            }
        )
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "reset_agent_states": {"director": ["scene_direction"]},
            }
        )

        assert "director" not in scene.agent_state

    @pytest.mark.asyncio
    async def test_reset_nonexistent_agent(self, scene_factory, mixin_instance):
        """Attempting to reset a nonexistent agent should not raise an error."""
        scene = scene_factory(agent_state={"director": {"data": 1}})
        mixin = mixin_instance(scene)

        # Should not raise
        await mixin.handle_execute_scene_state_reset(
            {
                "reset_agent_states": {"nonexistent": True},
            }
        )

        assert "director" in scene.agent_state


# ---------------------------------------------------------------------------
# Tests: Reinforcement Wipe
# ---------------------------------------------------------------------------


class TestReinforcementWipe:
    @pytest.mark.asyncio
    async def test_wipe_single_reinforcement(
        self, scene_factory, reinforcement_factory, mixin_instance
    ):
        """Wipe a single reinforcement by index."""
        reinforcements = [
            reinforcement_factory("Question 1", "Alice"),
            reinforcement_factory("Question 2", None),
        ]
        scene = scene_factory(reinforcements=reinforcements)
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "wipe_reinforcements": [0],
            }
        )

        assert len(scene.world_state.reinforce) == 1
        assert scene.world_state.reinforce[0].question == "Question 2"

    @pytest.mark.asyncio
    async def test_wipe_multiple_reinforcements_descending_order(
        self, scene_factory, reinforcement_factory, mixin_instance
    ):
        """Ensure indices are processed in descending order to preserve validity."""
        reinforcements = [
            reinforcement_factory("Question 1"),
            reinforcement_factory("Question 2"),
            reinforcement_factory("Question 3"),
        ]
        scene = scene_factory(reinforcements=reinforcements)
        mixin = mixin_instance(scene)

        # Wipe indices 0 and 2 - should work correctly regardless of order provided
        await mixin.handle_execute_scene_state_reset(
            {
                "wipe_reinforcements": [0, 2],
            }
        )

        assert len(scene.world_state.reinforce) == 1
        assert scene.world_state.reinforce[0].question == "Question 2"

    @pytest.mark.asyncio
    async def test_wipe_all_reinforcements(
        self, scene_factory, reinforcement_factory, mixin_instance
    ):
        """Wipe all reinforcements."""
        reinforcements = [
            reinforcement_factory("Question 1"),
            reinforcement_factory("Question 2"),
        ]
        scene = scene_factory(reinforcements=reinforcements)
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "wipe_reinforcements": [0, 1],
            }
        )

        assert len(scene.world_state.reinforce) == 0

    @pytest.mark.asyncio
    async def test_wipe_invalid_index(
        self, scene_factory, reinforcement_factory, mixin_instance
    ):
        """Attempting to wipe an invalid index should not raise an error."""
        reinforcements = [reinforcement_factory("Question 1")]
        scene = scene_factory(reinforcements=reinforcements)
        mixin = mixin_instance(scene)

        # Should not raise
        await mixin.handle_execute_scene_state_reset(
            {
                "wipe_reinforcements": [5, 10],  # Invalid indices
            }
        )

        assert len(scene.world_state.reinforce) == 1


# ---------------------------------------------------------------------------
# Tests: Intent State Reset
# ---------------------------------------------------------------------------


class TestIntentStateReset:
    @pytest.mark.asyncio
    async def test_reset_intent_state(self, scene_factory, mixin_instance):
        """Reset intent state via its reset() method."""
        scene = scene_factory()
        # Sanity: factory pre-populates a non-default intent state.
        assert scene.intent_state.phase is not None
        assert scene.intent_state.start == 10

        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "reset_intent_state": True,
            }
        )

        # Real `SceneIntent.reset()` resets phase to a default and start to 0.
        # Verify against its real semantics, not a custom flag.
        assert scene.intent_state.start == 0


# ---------------------------------------------------------------------------
# Tests: Context DB Reset
# ---------------------------------------------------------------------------


class TestContextDBReset:
    @pytest.mark.asyncio
    async def test_reset_context_db(self, scene_factory, mixin_instance):
        """Reset context DB calls commit_to_memory."""
        scene = scene_factory()
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "reset_context_db": True,
            }
        )

        scene.commit_to_memory.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Get State Info
# ---------------------------------------------------------------------------


class TestGetStateInfo:
    @pytest.mark.asyncio
    async def test_returns_correct_counts(
        self, scene_factory, reinforcement_factory, mixin_instance
    ):
        """Verify get_scene_state_reset_info returns correct counts."""
        scene = scene_factory(
            history=[{"text": "1"}, {"text": "2"}, {"text": "3"}],
            archived_history=[
                {"text": "a1", "end": 5},
                {"text": "a2", "end": None},  # static
                {"text": "a3", "end": None},  # static
            ],
            layered_history=[["l1"], ["l2"]],
        )
        mixin = mixin_instance(scene)

        await mixin.handle_get_scene_state_reset_info({})

        call_args = mixin.websocket_handler.queue_put.call_args[0][0]
        data = call_args["data"]

        assert data["history_count"] == 3
        assert data["archived_history_count"] == 3
        assert data["static_history_count"] == 2
        assert data["layered_history_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_agent_state_keys(self, scene_factory, mixin_instance):
        """Verify agent states are returned with their keys."""
        scene = scene_factory(
            agent_state={
                "director": {"scene_direction": {}, "chat": {}},
                "summarizer": {"cache": {}},
            }
        )
        mixin = mixin_instance(scene)

        await mixin.handle_get_scene_state_reset_info({})

        call_args = mixin.websocket_handler.queue_put.call_args[0][0]
        data = call_args["data"]

        assert "director" in data["agent_states"]
        assert set(data["agent_states"]["director"]) == {"scene_direction", "chat"}
        assert "summarizer" in data["agent_states"]
        assert data["agent_states"]["summarizer"] == ["cache"]

    @pytest.mark.asyncio
    async def test_returns_reinforcement_info(
        self, scene_factory, reinforcement_factory, mixin_instance
    ):
        """Verify reinforcements are returned with question and character."""
        reinforcements = [
            reinforcement_factory("What is the mood?", None),
            reinforcement_factory("Where is Alice?", "Alice"),
        ]
        scene = scene_factory(reinforcements=reinforcements)
        mixin = mixin_instance(scene)

        await mixin.handle_get_scene_state_reset_info({})

        call_args = mixin.websocket_handler.queue_put.call_args[0][0]
        data = call_args["data"]

        assert len(data["reinforcements"]) == 2
        assert data["reinforcements"][0]["idx"] == 0
        assert data["reinforcements"][0]["question"] == "What is the mood?"
        assert data["reinforcements"][0]["character"] is None
        assert data["reinforcements"][1]["idx"] == 1
        assert data["reinforcements"][1]["character"] == "Alice"

    @pytest.mark.asyncio
    async def test_empty_agent_states_not_included(self, scene_factory, mixin_instance):
        """Empty agent states should not be included in the response."""
        scene = scene_factory(
            agent_state={
                "director": {"data": 1},
                "empty_agent": {},  # Empty - should not be included
            }
        )
        mixin = mixin_instance(scene)

        await mixin.handle_get_scene_state_reset_info({})

        call_args = mixin.websocket_handler.queue_put.call_args[0][0]
        data = call_args["data"]

        assert "director" in data["agent_states"]
        assert "empty_agent" not in data["agent_states"]


# ---------------------------------------------------------------------------
# Tests: Combined Operations
# ---------------------------------------------------------------------------


class TestCombinedOperations:
    @pytest.mark.asyncio
    async def test_multiple_reset_operations(
        self, scene_factory, reinforcement_factory, mixin_instance
    ):
        """Test executing multiple reset operations at once."""
        reinforcements = [reinforcement_factory("Q1")]
        scene = scene_factory(
            history=[{"text": "msg"}],
            archived_history=[{"text": "arch", "end": 5}],
            layered_history=[["layer"]],
            agent_state={"director": {"data": 1}},
            reinforcements=reinforcements,
        )
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "reset_context_db": True,
                "wipe_history": True,
                "wipe_history_include_static": True,
                "reset_intent_state": True,
                "reset_agent_states": {"director": True},
                "wipe_reinforcements": [0],
            }
        )

        # Verify all operations completed
        assert scene.history == []
        assert scene.archived_history == []
        assert scene.layered_history == []
        assert "director" not in scene.agent_state
        assert len(scene.world_state.reinforce) == 0
        assert scene.intent_state.start == 0
        scene.commit_to_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_db_reset_is_last_operation(
        self, scene_factory, mixin_instance
    ):
        """
        Context DB reset should be the last operation so it reflects all other changes.
        """
        scene = scene_factory(
            history=[{"text": "msg"}],
            agent_state={"director": {"data": 1}},
        )
        mixin = mixin_instance(scene)

        # Track the order of operations by snapshotting state when commit fires.
        operations = []

        async def track_commit():
            operations.append(
                {
                    "history_count": len(scene.history),
                    "agent_state_has_director": "director" in scene.agent_state,
                }
            )

        scene.commit_to_memory = track_commit

        await mixin.handle_execute_scene_state_reset(
            {
                "reset_context_db": True,
                "wipe_history": True,
                "reset_agent_states": {"director": True},
            }
        )

        # When commit_to_memory is called, all other operations should be complete
        assert len(operations) == 1
        assert operations[0]["history_count"] == 0  # History already wiped
        assert (
            operations[0]["agent_state_has_director"] is False
        )  # Agent state already reset


@pytest.mark.asyncio
@pytest.mark.parametrize("reset_context_db", [False, True])
async def test_wipe_history_removes_message_facts_before_reindex(
    scene_factory, mixin_instance, monkeypatch, reset_context_db
):
    from talemate.knowledge.perspective_models import content_digest

    scene = scene_factory(history=[CharacterMessage(message="Alice: I moved in.")])
    scene.world_state.facts = {
        "F1": Fact(
            id="F1",
            text="Alice moved in.",
            archive_id="e1",
            message_id=scene.history[0].id,
            message_digest=content_digest(scene.history[0].perception_text),
        ),
        "F2": Fact(id="F2", text="The house is old.", source="manual"),
    }
    retained = KnowledgeEdge(
        character="Bob", target="F2", message_id=scene.history[0].id
    )
    scene.world_state.knowledge = [
        # a hand grant keeps a fact through the loss of one message, not
        # through a wipe of the history it came from
        KnowledgeEdge(character="Bob", target="F1", source="manual"),
        retained,
    ]
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "delete", AsyncMock())

    async def reindex():
        assert set(scene.world_state.facts) == {"F2"}
        assert scene.world_state.knowledge == [retained]
        assert retained.message_id is None

    scene.commit_to_memory.side_effect = reindex
    with ActiveScene(scene):
        await mixin_instance(scene).handle_execute_scene_state_reset(
            {"wipe_history": True, "reset_context_db": reset_context_db}
        )
    assert set(scene.world_state.facts) == {"F2"}
    assert scene.world_state.knowledge == [retained]
    assert retained.message_id is None
    memory.delete.assert_awaited_once_with({"ids": ["F1"]})
    assert scene.commit_to_memory.await_count == int(reset_context_db)
