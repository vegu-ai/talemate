"""
Tests for the scene state reset functionality.
"""

import pytest
import types
from unittest.mock import MagicMock, AsyncMock

from talemate.server.world_state_manager.scene_state_reset import (
    SceneStateResetMixin,
    ExecuteSceneStateResetPayload,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_scene():
    """
    Create a mock scene with test data.
    Returns a factory function for creating scenes with different configurations.
    """

    def _factory(
        history=None,
        archived_history=None,
        layered_history=None,
        agent_state=None,
        reinforcements=None,
    ):
        scene = types.SimpleNamespace()
        scene.history = history if history is not None else []
        scene.archived_history = archived_history if archived_history is not None else []
        scene.layered_history = layered_history if layered_history is not None else []
        scene.agent_state = agent_state if agent_state is not None else {}

        # Mock intent_state
        scene.intent_state = types.SimpleNamespace()
        scene.intent_state.phase = {"scene_type": "test"}
        scene.intent_state.start = 10
        scene.intent_state._reset_called = False

        def reset():
            scene.intent_state.phase = None
            scene.intent_state.start = 0
            scene.intent_state._reset_called = True

        scene.intent_state.reset = reset

        # Mock world_state with reinforcements
        scene.world_state = types.SimpleNamespace()
        scene.world_state.reinforce = reinforcements if reinforcements is not None else []
        scene.world_state._removed_indices = []

        async def remove_reinforcement(idx):
            if 0 <= idx < len(scene.world_state.reinforce):
                scene.world_state._removed_indices.append(idx)
                scene.world_state.reinforce.pop(idx)

        scene.world_state.remove_reinforcement = remove_reinforcement
        scene.world_state.emit = MagicMock()

        # Mock async methods
        scene.commit_to_memory = AsyncMock()
        scene.emit_history = AsyncMock()
        scene.emit_status = MagicMock()

        return scene

    return _factory


@pytest.fixture
def mock_reinforcement():
    """Create a mock reinforcement object."""

    def _factory(question, character=None):
        r = types.SimpleNamespace()
        r.question = question
        r.character = character
        return r

    return _factory


@pytest.fixture
def mixin_instance(mock_scene):
    """Create an instance of SceneStateResetMixin with mocked dependencies."""

    class TestMixin(SceneStateResetMixin):
        def __init__(self, scene):
            self._scene = scene
            self.websocket_handler = types.SimpleNamespace()
            self.websocket_handler.queue_put = MagicMock()
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
    async def test_wipe_all_history_including_static(self, mock_scene, mixin_instance):
        """Wipe all history including static entries."""
        scene = mock_scene(
            history=[{"text": "msg1"}, {"text": "msg2"}],
            archived_history=[
                {"text": "arch1", "end": 5},  # dynamic
                {"text": "arch2", "end": None},  # static
            ],
            layered_history=[["layer1"], ["layer2"]],
        )
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

    @pytest.mark.asyncio
    async def test_wipe_history_preserve_static(self, mock_scene, mixin_instance):
        """Wipe history but preserve static archived entries."""
        scene = mock_scene(
            history=[{"text": "msg1"}],
            archived_history=[
                {"text": "arch1", "end": 5},  # dynamic - should be removed
                {"text": "arch2", "end": None},  # static - should be kept
                {"text": "arch3", "end": 10},  # dynamic - should be removed
            ],
            layered_history=[["layer1"]],
        )
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

    @pytest.mark.asyncio
    async def test_wipe_history_no_static_entries(self, mock_scene, mixin_instance):
        """Wipe history when there are no static entries."""
        scene = mock_scene(
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
    async def test_reset_entire_agent(self, mock_scene, mixin_instance):
        """Reset all state for a specific agent."""
        scene = mock_scene(
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
    async def test_reset_specific_keys(self, mock_scene, mixin_instance):
        """Reset specific keys within an agent."""
        scene = mock_scene(
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
    async def test_reset_all_keys_removes_agent(self, mock_scene, mixin_instance):
        """Resetting all keys of an agent should remove the agent entry."""
        scene = mock_scene(
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
    async def test_reset_nonexistent_agent(self, mock_scene, mixin_instance):
        """Attempting to reset a nonexistent agent should not raise an error."""
        scene = mock_scene(agent_state={"director": {"data": 1}})
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
        self, mock_scene, mock_reinforcement, mixin_instance
    ):
        """Wipe a single reinforcement by index."""
        reinforcements = [
            mock_reinforcement("Question 1", "Alice"),
            mock_reinforcement("Question 2", None),
        ]
        scene = mock_scene(reinforcements=reinforcements)
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
        self, mock_scene, mock_reinforcement, mixin_instance
    ):
        """Ensure indices are processed in descending order to preserve validity."""
        reinforcements = [
            mock_reinforcement("Question 1"),
            mock_reinforcement("Question 2"),
            mock_reinforcement("Question 3"),
        ]
        scene = mock_scene(reinforcements=reinforcements)
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
        self, mock_scene, mock_reinforcement, mixin_instance
    ):
        """Wipe all reinforcements."""
        reinforcements = [
            mock_reinforcement("Question 1"),
            mock_reinforcement("Question 2"),
        ]
        scene = mock_scene(reinforcements=reinforcements)
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "wipe_reinforcements": [0, 1],
            }
        )

        assert len(scene.world_state.reinforce) == 0

    @pytest.mark.asyncio
    async def test_wipe_invalid_index(
        self, mock_scene, mock_reinforcement, mixin_instance
    ):
        """Attempting to wipe an invalid index should not raise an error."""
        reinforcements = [mock_reinforcement("Question 1")]
        scene = mock_scene(reinforcements=reinforcements)
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
    async def test_reset_intent_state(self, mock_scene, mixin_instance):
        """Reset intent state via its reset() method."""
        scene = mock_scene()
        mixin = mixin_instance(scene)

        await mixin.handle_execute_scene_state_reset(
            {
                "reset_intent_state": True,
            }
        )

        assert scene.intent_state._reset_called is True
        assert scene.intent_state.phase is None
        assert scene.intent_state.start == 0


# ---------------------------------------------------------------------------
# Tests: Context DB Reset
# ---------------------------------------------------------------------------


class TestContextDBReset:
    @pytest.mark.asyncio
    async def test_reset_context_db(self, mock_scene, mixin_instance):
        """Reset context DB calls commit_to_memory."""
        scene = mock_scene()
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
        self, mock_scene, mock_reinforcement, mixin_instance
    ):
        """Verify get_scene_state_reset_info returns correct counts."""
        scene = mock_scene(
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
    async def test_returns_agent_state_keys(self, mock_scene, mixin_instance):
        """Verify agent states are returned with their keys."""
        scene = mock_scene(
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
        self, mock_scene, mock_reinforcement, mixin_instance
    ):
        """Verify reinforcements are returned with question and character."""
        reinforcements = [
            mock_reinforcement("What is the mood?", None),
            mock_reinforcement("Where is Alice?", "Alice"),
        ]
        scene = mock_scene(reinforcements=reinforcements)
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
    async def test_empty_agent_states_not_included(self, mock_scene, mixin_instance):
        """Empty agent states should not be included in the response."""
        scene = mock_scene(
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
        self, mock_scene, mock_reinforcement, mixin_instance
    ):
        """Test executing multiple reset operations at once."""
        reinforcements = [mock_reinforcement("Q1")]
        scene = mock_scene(
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
        assert scene.intent_state._reset_called is True
        scene.commit_to_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_db_reset_is_last_operation(
        self, mock_scene, mixin_instance
    ):
        """
        Context DB reset should be the last operation so it reflects all other changes.
        """
        scene = mock_scene(
            history=[{"text": "msg"}],
            agent_state={"director": {"data": 1}},
        )
        mixin = mixin_instance(scene)

        # Track the order of operations
        operations = []
        original_commit = scene.commit_to_memory

        async def track_commit():
            # Record state at time of commit
            operations.append({
                "history_count": len(scene.history),
                "agent_state_has_director": "director" in scene.agent_state,
            })
            await original_commit()

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
        assert operations[0]["agent_state_has_director"] is False  # Agent state already reset
