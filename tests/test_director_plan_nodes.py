"""Unit tests for talemate.agents.director.plan.nodes.

Each plan node is exercised inside a real GraphContext bound to a real Scene
(MockScene + bootstrap_scene). LLM-bound paths are not exercised — these node
classes do not call Prompt.request directly; ExpandStoryArc delegates to
PlanMixin.plan_expand_beats which is tested separately.

The CompleteTask/RemoveTask/EditTask/InsertTask/DeletePlan/CreatePlan/etc.
nodes all manipulate plan state via the same util functions covered in
test_plan_tasks.py — these tests focus on the node-level glue: input wiring,
output values, error paths via ActionFailed, and chat-context interactions.
"""

from __future__ import annotations

from typing import Any

import pytest

from conftest import MockScene, bootstrap_scene

from talemate.agents.director.action_core.exceptions import ActionFailed
from talemate.agents.director.chat.context import (
    DirectorChatContext,
    director_chat_context,
)
from talemate.agents.director.chat.settings import (
    ChatModeSettings,
    GenerateArcSettings,
)
from talemate.agents.director.plan.nodes import (
    CompleteTask,
    CreatePlan,
    DeletePlan,
    EditTask,
    EstimateWords,
    ExpandStoryArc,
    GetActiveChatPlanId,
    GetActivePlan,
    InsertTask,
    RemoveTask,
    _validate_task,
)
from talemate.agents.director.plan.schema import (
    Beat,
    Plan,
    PlanStatus,
    Task,
)
from talemate.agents.director.plan.util import (
    get_plan,
    save_plan,
)
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import (
    GraphContext,
    NodeVerbosity,
)
from talemate.game.engine.nodes.registry import import_talemate_node_definitions


# ---------------------------------------------------------------------------
# Session-scoped: register node definitions once.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _import_node_definitions():
    import_talemate_node_definitions()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_RESERVED_PROPERTY_NAMES = {"title", "id"}


@pytest.fixture
def scene():
    """Real Scene with bootstrapped agents (mock memory + mock client)."""
    s = MockScene()
    bootstrap_scene(s)
    return s


async def _run_node(
    node,
    scene,
    *,
    inputs: dict | None = None,
    chat_ctx: DirectorChatContext | None = None,
    state_setup=None,
) -> dict[str, Any]:
    """Run a node inside a GraphContext bound to the given scene.

    `inputs` are pre-loaded as properties (the fallback path used when an
    input socket has no connected producer).
    `chat_ctx` is optionally set on the director_chat_context contextvar.
    Returns a dict of {output_name: value} captured before the context exits.
    """
    if inputs:
        for k, v in inputs.items():
            if k in _RESERVED_PROPERTY_NAMES:
                node.properties[k] = v
            else:
                node.set_property(k, v)

    token = None
    if chat_ctx is not None:
        token = director_chat_context.set(chat_ctx)
    try:
        with ActiveScene(scene):
            with GraphContext() as state:
                state.verbosity = NodeVerbosity.NORMAL
                if state_setup:
                    state_setup(state)
                await node.run(state)
                return {sock.name: sock.value for sock in node.outputs}
    finally:
        if token is not None:
            director_chat_context.reset(token)


def _ensure_director_state(scene):
    if "director" not in scene.agent_state:
        scene.agent_state["director"] = {}


# ---------------------------------------------------------------------------
# _validate_task
# ---------------------------------------------------------------------------


class TestValidateTask:
    def test_returns_beat_when_beat_fields_present(self):
        out = _validate_task(
            {"description": "x", "type": "dialogue", "tension": 0.6}, order=2
        )
        assert isinstance(out, Beat)
        assert out.order == 2
        assert out.tension == 0.6

    def test_returns_task_when_no_beat_fields(self):
        out = _validate_task({"description": "x"}, order=4)
        assert isinstance(out, Task)
        assert not isinstance(out, Beat)
        assert out.order == 4

    def test_uses_explicit_order_over_argument(self):
        out = _validate_task({"description": "x", "order": 9}, order=2)
        assert out.order == 9

    def test_pacing_field_promotes_to_beat(self):
        out = _validate_task({"description": "x", "pacing": "fast"}, order=1)
        assert isinstance(out, Beat)
        assert out.pacing == "fast"

    def test_characters_field_promotes_to_beat(self):
        out = _validate_task({"description": "x", "characters": ["A"]}, order=1)
        assert isinstance(out, Beat)
        assert out.characters == ["A"]


# ---------------------------------------------------------------------------
# CreatePlan
# ---------------------------------------------------------------------------


class TestCreatePlan:
    @pytest.mark.asyncio
    async def test_creates_plan_with_validated_tasks(self, scene):
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "instructions": "outline a beach scene",
                "tasks": [
                    {"description": "wake up", "type": "narration", "tension": 0.2},
                    {"description": "set goal"},  # plain task
                ],
            },
        )

        assert out["plan_id"]
        plan = get_plan(scene, out["plan_id"])
        assert plan is not None
        assert plan.instructions == "outline a beach scene"
        assert plan.status == PlanStatus.ready
        assert len(plan.tasks) == 2
        assert isinstance(plan.tasks[0], Beat)
        assert plan.tasks[0].order == 1
        assert isinstance(plan.tasks[1], Task)
        assert plan.tasks[1].order == 2

    @pytest.mark.asyncio
    async def test_handles_non_list_tasks_with_warning(self, scene):
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "instructions": "x",
                "tasks": "not-a-list",  # invalid
            },
        )
        plan = get_plan(scene, out["plan_id"])
        assert plan is not None
        assert plan.tasks == []

    @pytest.mark.asyncio
    async def test_skips_non_dict_items_in_tasks(self, scene):
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "instructions": "x",
                "tasks": [{"description": "valid"}, "string-not-dict", 42, None],
            },
        )
        plan = get_plan(scene, out["plan_id"])
        assert len(plan.tasks) == 1
        assert plan.tasks[0].description == "valid"

    @pytest.mark.asyncio
    async def test_skips_invalid_task_dicts(self, scene):
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "instructions": "x",
                "tasks": [
                    {"description": "ok"},
                    # tension > 1.0 — pydantic doesn't reject by default since
                    # it's a float; use an explicit invalid type instead
                    {"description": "bad", "type": "not-a-valid-type"},
                ],
            },
        )
        plan = get_plan(scene, out["plan_id"])
        # The invalid type should cause _validate_task to raise; node skips it.
        assert all(t.description != "bad" for t in plan.tasks)

    @pytest.mark.asyncio
    async def test_stamps_close_arc_from_chat_context(self, scene):
        chat_ctx = DirectorChatContext(
            chat_id="chat-1",
            modes=ChatModeSettings(generate_arc=GenerateArcSettings(close_arc=True)),
        )
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={"state": {}, "instructions": "x", "tasks": []},
            chat_ctx=chat_ctx,
        )
        plan = get_plan(scene, out["plan_id"])
        assert plan.meta["close_arc"] is True

    @pytest.mark.asyncio
    async def test_meta_close_arc_is_preserved_when_set_explicitly(self, scene):
        chat_ctx = DirectorChatContext(
            chat_id="chat-1",
            modes=ChatModeSettings(generate_arc=GenerateArcSettings(close_arc=True)),
        )
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "instructions": "x",
                "tasks": [],
                "meta": {"close_arc": False, "perspective": "First person"},
            },
            chat_ctx=chat_ctx,
        )
        plan = get_plan(scene, out["plan_id"])
        # Existing meta close_arc must NOT be overwritten by chat-ctx.
        assert plan.meta["close_arc"] is False
        assert plan.meta["perspective"] == "First person"

    @pytest.mark.asyncio
    async def test_sets_scene_perspective_from_meta(self, scene):
        node = CreatePlan()
        await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "instructions": "x",
                "tasks": [],
                "meta": {"perspective": "Third person omniscient"},
            },
        )
        assert scene.perspectives.default == "Third person omniscient"

    @pytest.mark.asyncio
    async def test_links_plan_to_chat_context(self, scene):
        chat_ctx = DirectorChatContext(chat_id="chat-1")
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={"state": {}, "instructions": "x", "tasks": []},
            chat_ctx=chat_ctx,
        )
        assert chat_ctx.plan_id == out["plan_id"]

    @pytest.mark.asyncio
    async def test_state_passes_through(self, scene):
        node = CreatePlan()
        sentinel = {"key": "value"}
        out = await _run_node(
            node,
            scene,
            inputs={"state": sentinel, "instructions": "x", "tasks": []},
        )
        assert out["state"] is sentinel

    @pytest.mark.asyncio
    async def test_status_value_default_ready(self, scene):
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={"state": {}, "instructions": "x", "tasks": []},
        )
        plan = get_plan(scene, out["plan_id"])
        assert plan.status == PlanStatus.ready

    @pytest.mark.asyncio
    async def test_explicit_status_value_used(self, scene):
        node = CreatePlan()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "instructions": "x",
                "tasks": [],
                "status": "planning",
            },
        )
        plan = get_plan(scene, out["plan_id"])
        assert plan.status == PlanStatus.planning


# ---------------------------------------------------------------------------
# EstimateWords
# ---------------------------------------------------------------------------


class TestEstimateWords:
    @pytest.mark.asyncio
    async def test_estimates_increase_with_beat_count(self, scene):
        node1 = EstimateWords()
        out1 = await _run_node(node1, scene, inputs={"state": {}, "beat_count": 4})
        node2 = EstimateWords()
        out2 = await _run_node(node2, scene, inputs={"state": {}, "beat_count": 12})
        assert out1["estimated_words"] > 0
        assert out2["estimated_words"] > out1["estimated_words"]
        assert out1["beat_count"] == 4
        assert out2["beat_count"] == 12

    @pytest.mark.asyncio
    async def test_default_beat_count(self, scene):
        node = EstimateWords()
        out = await _run_node(node, scene, inputs={"state": {}})
        assert out["beat_count"] == 8
        assert out["estimated_words"] > 0
        assert out["estimated_reading_minutes"] >= 0

    @pytest.mark.asyncio
    async def test_reading_minutes_consistent_with_word_count(self, scene):
        from talemate.agents.director.plan.schema import READING_SPEED_WPM

        node = EstimateWords()
        out = await _run_node(node, scene, inputs={"state": {}, "beat_count": 8})
        # The node rounds reading_minutes to 1 decimal. Check that word count
        # divided by the WPM constant matches the reported reading time.
        expected = round(out["estimated_words"] / READING_SPEED_WPM, 1)
        assert out["estimated_reading_minutes"] == expected


# ---------------------------------------------------------------------------
# GetActiveChatPlanId
# ---------------------------------------------------------------------------


class TestGetActiveChatPlanId:
    @pytest.mark.asyncio
    async def test_returns_plan_id_when_chat_has_plan(self, scene):
        ctx = DirectorChatContext(chat_id="c1", plan_id="plan-abc")
        node = GetActiveChatPlanId()
        out = await _run_node(node, scene, inputs={"state": {}}, chat_ctx=ctx)
        assert out["plan_id"] == "plan-abc"
        assert out["has_plan"] is True

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_no_chat_context(self, scene):
        node = GetActiveChatPlanId()
        out = await _run_node(node, scene, inputs={"state": {}})
        assert out["plan_id"] == ""
        assert out["has_plan"] is False

    @pytest.mark.asyncio
    async def test_returns_empty_when_chat_has_no_plan(self, scene):
        ctx = DirectorChatContext(chat_id="c1")
        node = GetActiveChatPlanId()
        out = await _run_node(node, scene, inputs={"state": {}}, chat_ctx=ctx)
        assert out["plan_id"] == ""
        assert out["has_plan"] is False


# ---------------------------------------------------------------------------
# GetActivePlan
# ---------------------------------------------------------------------------


class TestGetActivePlan:
    @pytest.mark.asyncio
    async def test_returns_plan_with_beats_and_meta(self, scene):
        plan = Plan(
            instructions="x",
            status=PlanStatus.ready,
            tasks=[
                Beat(description="b1", order=1, tension=0.2),
                Task(description="t1", order=2),  # not a Beat
                Beat(description="b2", order=3, tension=0.6),
            ],
            meta={"perspective": "First person", "close_arc": True},
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = GetActivePlan()
        out = await _run_node(node, scene, inputs={"state": {}}, chat_ctx=ctx)
        assert out["has_plan"] is True
        assert out["plan_id"] == plan.id
        assert out["plan"].id == plan.id
        # Only Beats are included in the beats output (Task `t1` excluded).
        assert [b.description for b in out["beats"]] == ["b1", "b2"]
        assert out["perspective"] == "First person"
        assert out["close_arc"] is True

    @pytest.mark.asyncio
    async def test_falls_back_to_scene_perspective(self, scene):
        plan = Plan(instructions="x", tasks=[], meta={})
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)
        scene.perspectives.default = "Custom scene perspective"

        node = GetActivePlan()
        out = await _run_node(node, scene, inputs={"state": {}}, chat_ctx=ctx)
        assert out["perspective"] == "Custom scene perspective"

    @pytest.mark.asyncio
    async def test_returns_default_perspective_when_nothing_set(self, scene):
        plan = Plan(instructions="x", tasks=[], meta={})
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        scene.perspectives.default = ""

        node = GetActivePlan()
        out = await _run_node(node, scene, inputs={"state": {}}, chat_ctx=ctx)
        assert out["perspective"] == "Third person, past tense."

    @pytest.mark.asyncio
    async def test_no_plan_when_chat_has_no_plan_id(self, scene):
        ctx = DirectorChatContext(chat_id="c1")
        node = GetActivePlan()
        out = await _run_node(node, scene, inputs={"state": {}}, chat_ctx=ctx)
        assert out["has_plan"] is False
        assert out["plan"] is None
        assert out["beats"] == []

    @pytest.mark.asyncio
    async def test_no_chat_context_returns_no_plan(self, scene):
        node = GetActivePlan()
        out = await _run_node(node, scene, inputs={"state": {}})
        assert out["has_plan"] is False


# ---------------------------------------------------------------------------
# CompleteTask
# ---------------------------------------------------------------------------


class TestCompleteTaskNode:
    @pytest.mark.asyncio
    async def test_marks_task_completed_with_explicit_plan_id(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        task_id = plan.tasks[0].id

        node = CompleteTask()
        out = await _run_node(
            node,
            scene,
            inputs={"state": {}, "task_id": task_id, "plan_id": plan.id},
        )
        assert "completed" in out["result"]
        loaded = get_plan(scene, plan.id)
        assert loaded.get_task(task_id).status == "completed"

    @pytest.mark.asyncio
    async def test_resolves_plan_id_from_chat_ctx(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)
        task_id = plan.tasks[0].id

        node = CompleteTask()
        out = await _run_node(
            node,
            scene,
            inputs={"state": {}, "task_id": task_id},
            chat_ctx=ctx,
        )
        assert "completed" in out["result"]


# ---------------------------------------------------------------------------
# RemoveTask
# ---------------------------------------------------------------------------


class TestRemoveTaskNode:
    @pytest.mark.asyncio
    async def test_removes_task_from_active_plan(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[
                Task(description="a", order=1),
                Task(description="b", order=2),
            ],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)
        task_id = plan.tasks[0].id

        node = RemoveTask()
        out = await _run_node(
            node,
            scene,
            inputs={"state": {}, "task_id": task_id},
            chat_ctx=ctx,
        )
        assert "Removed" in out["result"]
        loaded = get_plan(scene, plan.id)
        assert len(loaded.tasks) == 1
        assert loaded.tasks[0].description == "b"
        assert loaded.tasks[0].order == 1  # renumbered

    @pytest.mark.asyncio
    async def test_raises_when_no_active_plan(self, scene):
        node = RemoveTask()
        with pytest.raises(ActionFailed, match="No active plan"):
            await _run_node(node, scene, inputs={"state": {}, "task_id": "x"})

    @pytest.mark.asyncio
    async def test_raises_when_plan_completed(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.completed,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = RemoveTask()
        with pytest.raises(ActionFailed, match="completed"):
            await _run_node(
                node,
                scene,
                inputs={"state": {}, "task_id": plan.tasks[0].id},
                chat_ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_raises_when_task_id_unknown(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = RemoveTask()
        with pytest.raises(ActionFailed, match="No task with ID"):
            await _run_node(
                node,
                scene,
                inputs={"state": {}, "task_id": "missing"},
                chat_ctx=ctx,
            )


# ---------------------------------------------------------------------------
# EditTask
# ---------------------------------------------------------------------------


class TestEditTaskNode:
    @pytest.mark.asyncio
    async def test_edits_existing_task_and_returns_changed(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="orig", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)
        task_id = plan.tasks[0].id

        node = EditTask()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "task_id": task_id,
                "updates": {"description": "edited"},
            },
            chat_ctx=ctx,
        )
        assert "description" in out["result"]
        loaded = get_plan(scene, plan.id)
        assert loaded.get_task(task_id).description == "edited"

    @pytest.mark.asyncio
    async def test_raises_when_no_active_plan(self, scene):
        node = EditTask()
        with pytest.raises(ActionFailed, match="No active plan"):
            await _run_node(
                node,
                scene,
                inputs={"state": {}, "task_id": "x", "updates": {}},
            )

    @pytest.mark.asyncio
    async def test_raises_when_plan_completed(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.completed,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = EditTask()
        with pytest.raises(ActionFailed, match="completed"):
            await _run_node(
                node,
                scene,
                inputs={
                    "state": {},
                    "task_id": plan.tasks[0].id,
                    "updates": {"description": "x"},
                },
                chat_ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_raises_when_updates_not_dict(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = EditTask()
        with pytest.raises(ActionFailed, match="Updates must be a dict"):
            await _run_node(
                node,
                scene,
                inputs={
                    "state": {},
                    "task_id": plan.tasks[0].id,
                    "updates": "not-a-dict",
                },
                chat_ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_raises_when_task_unknown(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = EditTask()
        with pytest.raises(ActionFailed, match="No task with ID"):
            await _run_node(
                node,
                scene,
                inputs={
                    "state": {},
                    "task_id": "missing",
                    "updates": {"description": "x"},
                },
                chat_ctx=ctx,
            )


# ---------------------------------------------------------------------------
# InsertTask
# ---------------------------------------------------------------------------


class TestInsertTaskNode:
    @pytest.mark.asyncio
    async def test_inserts_task_at_default_end(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = InsertTask()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "task": {"description": "appended"},
            },
            chat_ctx=ctx,
        )
        assert "Inserted" in out["result"]
        loaded = get_plan(scene, plan.id)
        assert len(loaded.tasks) == 2
        assert loaded.tasks[1].description == "appended"

    @pytest.mark.asyncio
    async def test_inserts_at_start(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = InsertTask()
        await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "task": {"description": "first"},
                "position": "start",
            },
            chat_ctx=ctx,
        )
        loaded = get_plan(scene, plan.id)
        assert loaded.tasks[0].description == "first"

    @pytest.mark.asyncio
    async def test_inserts_beat_when_beat_fields_present(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = InsertTask()
        await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "task": {"description": "b", "type": "dialogue", "tension": 0.7},
            },
            chat_ctx=ctx,
        )
        loaded = get_plan(scene, plan.id)
        assert isinstance(loaded.tasks[-1], Beat)
        assert loaded.tasks[-1].tension == 0.7

    @pytest.mark.asyncio
    async def test_raises_when_no_active_plan(self, scene):
        node = InsertTask()
        with pytest.raises(ActionFailed, match="No active plan"):
            await _run_node(
                node,
                scene,
                inputs={"state": {}, "task": {"description": "x"}},
            )

    @pytest.mark.asyncio
    async def test_raises_when_plan_completed(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[],
            status=PlanStatus.completed,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = InsertTask()
        with pytest.raises(ActionFailed, match="completed"):
            await _run_node(
                node,
                scene,
                inputs={"state": {}, "task": {"description": "x"}},
                chat_ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_raises_when_task_not_dict(self, scene):
        plan = Plan(instructions="x", tasks=[], status=PlanStatus.ready)
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = InsertTask()
        with pytest.raises(ActionFailed, match="Task must be a dict"):
            await _run_node(
                node,
                scene,
                inputs={"state": {}, "task": "string-not-dict"},
                chat_ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_raises_on_invalid_task_payload(self, scene):
        plan = Plan(instructions="x", tasks=[], status=PlanStatus.ready)
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = InsertTask()
        with pytest.raises(ActionFailed, match="Invalid task"):
            await _run_node(
                node,
                scene,
                inputs={
                    "state": {},
                    "task": {"description": "x", "type": "not-a-valid-type"},
                },
                chat_ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_raises_when_position_unknown_id(self, scene):
        plan = Plan(
            instructions="x",
            tasks=[Task(description="a", order=1)],
            status=PlanStatus.ready,
        )
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = InsertTask()
        with pytest.raises(ActionFailed, match="No task with ID"):
            await _run_node(
                node,
                scene,
                inputs={
                    "state": {},
                    "task": {"description": "x"},
                    "position": "missing-id",
                },
                chat_ctx=ctx,
            )


# ---------------------------------------------------------------------------
# DeletePlan
# ---------------------------------------------------------------------------


class TestDeletePlanNode:
    @pytest.mark.asyncio
    async def test_deletes_active_plan(self, scene):
        plan = Plan(instructions="x", tasks=[], status=PlanStatus.ready)
        save_plan(scene, plan)
        ctx = DirectorChatContext(chat_id="c1", plan_id=plan.id)

        node = DeletePlan()
        out = await _run_node(node, scene, inputs={"state": {}}, chat_ctx=ctx)
        assert "Deleted" in out["result"]
        assert get_plan(scene, plan.id) is None
        # chat_ctx plan_id is cleared
        assert ctx.plan_id is None

    @pytest.mark.asyncio
    async def test_raises_when_no_active_plan(self, scene):
        node = DeletePlan()
        with pytest.raises(ActionFailed, match="No active plan"):
            await _run_node(node, scene, inputs={"state": {}})


# ---------------------------------------------------------------------------
# ExpandStoryArc — only the `no beats` early-out path (LLM path skipped)
# ---------------------------------------------------------------------------


class TestExpandStoryArcEarlyOut:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_beats(self, scene):
        node = ExpandStoryArc()
        out = await _run_node(
            node,
            scene,
            inputs={
                "state": {},
                "plan_id": "anything",
                "beats": [],
                "perspective": "Third person",
            },
        )
        assert out["result"] == "No beats to expand"
        assert out["word_count"] == 0
