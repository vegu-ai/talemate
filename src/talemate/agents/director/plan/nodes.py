"""
Plan graph nodes.

- CreatePlan: creates a plan with tasks and saves to agent state
- EstimateWords: estimates word count for a given number of beats
- CompleteTask: marks a task as completed in a plan
- RemoveTask: removes a task from a plan
- EditTask: patch-updates a task's fields
- InsertTask: inserts a new task at a given position
- DeletePlan: removes an entire plan
- ExpandStoryArc: expands beats into prose via the arc-expand pipeline

Beat execution is handled by the existing `direct_scene` FOCAL action.
Plan state is injected into the chat context when a plan exists.
"""

import structlog
from typing import ClassVar

from talemate.game.engine.nodes.core import (
    Node,
    GraphState,
    PropertyField,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentNode
from talemate.instance import get_agent
from talemate.context import active_scene
from talemate.agents.director.chat.context import director_chat_context
from talemate.agents.director.action_core.exceptions import ActionFailed

from .schema import (
    Beat,
    Plan,
    PlanStatus,
    Task,
    READING_SPEED_WPM,
    NARRATION_BEAT_RATIO,
)
from .util import (
    save_plan,
    delete_plan,
    complete_task,
    emit_plan_updated,
    get_plan,
    get_active_plan,
    check_plan_locked,
    emit_plan_for_chat,
)

log = structlog.get_logger("talemate.agents.director.plan.nodes")

BEAT_FIELDS = {"type", "pacing", "tension", "characters"}


def _validate_task(item: dict, order: int) -> Task:
    """Validate a task dict as Beat or Task based on fields present."""
    data = {**item, "order": item.get("order", order)}
    if BEAT_FIELDS & data.keys():
        return Beat.model_validate(data)
    return Task.model_validate(data)


@register("agents/director/plan/CreatePlan")
class CreatePlan(Node):
    """
    Creates a plan with tasks and saves it to agent state.

    Accepts a list of task dicts — automatically validates each as Beat
    (if beat-specific fields are present) or generic Task.
    """

    class Fields:
        instructions = PropertyField(
            name="instructions",
            type="text",
            description="Instructions for the plan",
            default="",
        )
        status = PropertyField(
            name="status",
            type="str",
            description="Initial plan status",
            default="ready",
            choices=[s.value for s in PlanStatus],
        )

    def __init__(self, title="Create Plan", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("instructions", socket_type="str")
        self.add_input("tasks", socket_type="list")
        self.add_input("meta", socket_type="dict", optional=True)
        self.add_input("status", socket_type="str", optional=True)

        self.set_property("instructions", "")
        self.set_property("status", "ready")

        self.add_output("state")
        self.add_output("plan_id", socket_type="str")
        self.add_output("result", socket_type="str")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        instructions = self.require_input("instructions")
        raw_tasks = self.require_input("tasks")
        meta = self.normalized_input_value("meta") or {}
        status_value = self.normalized_input_value("status") or "ready"

        scene = active_scene.get()
        chat_ctx = director_chat_context.get()

        # Validate tasks
        tasks = []
        if not isinstance(raw_tasks, list):
            log.warning("plan.create.tasks_not_list", type=type(raw_tasks).__name__)
            raw_tasks = []
        for i, item in enumerate(raw_tasks):
            if not isinstance(item, dict):
                log.warning("plan.create.skip_task", index=i, reason="not a dict")
                continue
            try:
                tasks.append(_validate_task(item, order=i + 1))
            except Exception as e:
                log.warning("plan.create.skip_task", index=i, error=str(e))

        # Stamp close_arc from the active chat context so expansion can read it
        # from plan.meta later (survives regenerations from a saved plan).
        # Guard on "not in meta" in case an upstream graph node set it explicitly.
        if chat_ctx is not None and "close_arc" not in meta:
            meta["close_arc"] = bool(chat_ctx.modes.generate_arc.close_arc)

        plan = Plan(
            instructions=instructions,
            status=PlanStatus(status_value),
            tasks=tasks,
            meta=meta,
        )

        save_plan(scene, plan)

        # Set scene perspective from plan meta if available
        perspective = meta.get("perspective")
        if perspective:
            scene.perspectives.default = perspective
            log.info("plan.set_perspective", perspective=perspective)

        # Link plan to the active director chat via context
        chat_id = None
        if chat_ctx:
            chat_ctx.plan_id = plan.id
            chat_id = chat_ctx.chat_id
            log.info("plan.linked_to_chat", plan_id=plan.id, chat_id=chat_id)

        log.info("plan.created", plan_id=plan.id, task_count=len(tasks))

        emit_plan_updated(plan, chat_id=chat_id)

        self.set_output_values(
            {
                "state": input_state,
                "plan_id": plan.id,
                "result": plan.status_summary(),
            }
        )


@register("agents/director/plan/EstimateWords")
class EstimateWords(Node):
    """
    Estimates total word output for a given number of beats based on
    narrator and conversation agent token settings.
    """

    class Fields:
        beat_count = PropertyField(
            name="beat_count",
            type="int",
            description="Number of beats to estimate for",
            default=8,
        )

    def __init__(self, title="Estimate Words", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("beat_count", socket_type="int", optional=True)

        self.set_property("beat_count", 8)

        self.add_output("state")
        self.add_output("beat_count", socket_type="int")
        self.add_output("estimated_words", socket_type="int")
        self.add_output("estimated_reading_minutes", socket_type="float")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        beat_count = self.normalized_input_value("beat_count") or 8
        scene = active_scene.get()

        narrator = get_agent("narrator")
        conversation = get_agent("conversation")
        narration_tokens = narrator.action_response_length("progress_story")
        dialogue_tokens = conversation.generation_settings_response_length

        dialogue_characters = len(list(scene.character_names))

        estimated_words = Beat.estimate_words(
            beat_count,
            narration_tokens,
            dialogue_tokens,
            dialogue_characters,
            narration_ratio=NARRATION_BEAT_RATIO,
        )
        estimated_reading = estimated_words / READING_SPEED_WPM

        self.set_output_values(
            {
                "state": input_state,
                "beat_count": beat_count,
                "estimated_words": estimated_words,
                "estimated_reading_minutes": round(estimated_reading, 1),
            }
        )


@register("agents/director/plan/GetActiveChatPlanId")
class GetActiveChatPlanId(Node):
    """
    Returns the plan_id linked to the currently active director chat,
    or None if no chat is active or no plan is linked.
    """

    def __init__(self, title="Get Active Chat Plan ID", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        self.add_output("plan_id", socket_type="str")
        self.add_output("has_plan", socket_type="bool")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")

        chat_ctx = director_chat_context.get()
        plan_id = chat_ctx.plan_id if chat_ctx else None

        self.set_output_values(
            {
                "state": input_state,
                "plan_id": plan_id or "",
                "has_plan": plan_id is not None,
            }
        )


@register("agents/director/plan/GetActivePlan")
class GetActivePlan(Node):
    """
    Returns the plan linked to the currently active director chat.
    Outputs the full plan object, plan ID, perspective, and beat list.
    """

    def __init__(self, title="Get Active Plan", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        self.add_output("plan_id", socket_type="str")
        self.add_output("plan", socket_type="any")
        self.add_output("beats", socket_type="list")
        self.add_output("perspective", socket_type="str")
        self.add_output("close_arc", socket_type="bool")
        self.add_output("has_plan", socket_type="bool")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")

        chat_ctx = director_chat_context.get()
        plan_id = chat_ctx.plan_id if chat_ctx else None
        plan = get_plan(active_scene.get(), plan_id) if plan_id else None

        perspective = ""
        beats = []
        close_arc = False

        if plan:
            perspective = plan.meta.get("perspective") or ""
            beats = [t for t in plan.tasks if isinstance(t, Beat)]
            close_arc = bool(plan.meta.get("close_arc", False))

        # Fall back to scene perspective or a sensible default
        if not perspective:
            scene = active_scene.get()
            perspective = scene.perspectives.default or "Third person, past tense."

        self.set_output_values(
            {
                "state": input_state,
                "plan_id": plan_id or "",
                "plan": plan,
                "perspective": perspective,
                "beats": beats,
                "close_arc": close_arc,
                "has_plan": plan is not None,
            }
        )


@register("agents/director/plan/CompleteTask")
class CompleteTask(AgentNode):
    """
    Marks a task as completed in a plan.
    """

    _agent_name: ClassVar[str] = "director"

    def __init__(self, title="Complete Task", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("task_id", socket_type="str")
        self.add_input("plan_id", socket_type="str", optional=True)
        self.add_output("state")
        self.add_output("result", socket_type="str")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        task_id = self.require_input("task_id")
        plan_id = self.normalized_input_value("plan_id") or None
        scene = active_scene.get()

        result = complete_task(scene, task_id, plan_id=plan_id)

        # Emit updated plan to frontend
        chat_ctx = director_chat_context.get()
        chat_id = chat_ctx.chat_id if chat_ctx else None
        resolved_plan_id = plan_id or (chat_ctx.plan_id if chat_ctx else None)
        if resolved_plan_id:
            plan = get_plan(scene, resolved_plan_id)
            if plan:
                emit_plan_updated(plan, chat_id=chat_id)

        self.set_output_values({"state": input_state, "result": result})


@register("agents/director/plan/ExpandStoryArc")
class ExpandStoryArc(AgentNode):
    """
    Expands a plan's beats into full prose and pushes them to scene history.

    Delegates to the director's PlanMixin.expand_beats() which handles
    chunking, template calls, revision, emission, and task completion.
    """

    _agent_name: ClassVar[str] = "narrator"

    class Fields:
        chunk_size = PropertyField(
            name="chunk_size",
            type="int",
            description="Number of beats per expansion chunk",
            default=5,
            min=3,
            max=12,
        )

    def __init__(self, title="Expand Story Arc", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("plan_id", socket_type="str")
        self.add_input("beats", socket_type="list")
        self.add_input("perspective", socket_type="str")
        self.add_input("director_notes", socket_type="str", optional=True)
        self.add_input("chunk_size", socket_type="int", optional=True)
        self.add_input("expand_critique", socket_type="bool", optional=True)
        self.add_input("close_arc", socket_type="bool", optional=True)

        self.set_property("chunk_size", 5)

        self.add_output("state")
        self.add_output("result", socket_type="str")
        self.add_output("word_count", socket_type="int")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        plan_id = self.require_input("plan_id")
        beats = self.require_input("beats")
        perspective = (
            self.normalized_input_value("perspective") or "Third person, past tense."
        )
        director_notes = self.normalized_input_value("director_notes") or ""
        chunk_size = self.normalized_input_value("chunk_size") or int(
            self.get_property("chunk_size")
        )
        expand_critique = self.normalized_input_value("expand_critique")
        # Unwired socket -> None -> False (continuation mode default)
        close_arc = bool(self.normalized_input_value("close_arc"))

        scene = active_scene.get()
        director = get_agent("director")

        if not beats:
            self.set_output_values(
                {
                    "state": input_state,
                    "result": "No beats to expand",
                    "word_count": 0,
                }
            )
            return

        chat_ctx = director_chat_context.get()
        chat_id = chat_ctx.chat_id if chat_ctx else None

        total_blocks, total_words = await director.plan_expand_beats(
            scene=scene,
            narrator=get_agent("narrator"),
            beats=beats,
            plan_id=plan_id,
            perspective=perspective,
            director_notes=director_notes,
            chunk_size=chunk_size,
            chat_id=chat_id,
            critique=expand_critique,
            close_arc=close_arc,
        )

        result = f"Generated {total_blocks} blocks, {total_words} words from {len(beats)} beats"
        log.info("expand_story_arc.done", result=result)

        self.set_output_values(
            {
                "state": input_state,
                "result": result,
                "word_count": total_words,
            }
        )


@register("agents/director/plan/RemoveTask")
class RemoveTask(Node):
    """
    Removes a task from the active plan by task ID.

    Renumbers remaining tasks to keep contiguous ordering.
    Blocked if the plan is completed.
    """

    def __init__(self, title="Remove Task", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("task_id", socket_type="str")
        self.add_output("state")
        self.add_output("result", socket_type="str")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        task_id = self.require_input("task_id")
        scene = active_scene.get()

        plan = get_active_plan(scene)
        if not plan:
            raise ActionFailed("No active plan")

        locked = check_plan_locked(plan)
        if locked:
            raise ActionFailed(locked)

        removed = plan.remove_task(task_id)
        if not removed:
            raise ActionFailed(f"No task with ID '{task_id}' in plan '{plan.id}'")

        save_plan(scene, plan)
        emit_plan_for_chat(plan)

        log.info("plan.remove_task", plan_id=plan.id, task_id=task_id)
        self.set_output_values(
            {
                "state": input_state,
                "result": f"Removed task {removed.order} [{task_id}] from plan [{plan.id}]. {len(plan.tasks)} tasks remaining.",
            }
        )


@register("agents/director/plan/EditTask")
class EditTask(Node):
    """
    Patch-updates a task's fields in the active plan.

    Accepts a dict of field updates — only provided fields are changed.
    The 'id' and 'order' fields are protected and cannot be changed.
    Blocked if the plan is completed.
    """

    def __init__(self, title="Edit Task", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("task_id", socket_type="str")
        self.add_input("updates", socket_type="dict")
        self.add_output("state")
        self.add_output("result", socket_type="str")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        task_id = self.require_input("task_id")
        updates = self.require_input("updates")
        scene = active_scene.get()

        plan = get_active_plan(scene)
        if not plan:
            raise ActionFailed("No active plan")

        locked = check_plan_locked(plan)
        if locked:
            raise ActionFailed(locked)

        if not isinstance(updates, dict):
            raise ActionFailed("Updates must be a dict")

        task, changed_fields = plan.edit_task(task_id, updates)
        if not task:
            raise ActionFailed(f"No task with ID '{task_id}' in plan '{plan.id}'")

        save_plan(scene, plan)
        emit_plan_for_chat(plan)

        log.info(
            "plan.edit_task", plan_id=plan.id, task_id=task_id, fields=changed_fields
        )
        self.set_output_values(
            {
                "state": input_state,
                "result": f"Updated task [{task_id}] in plan [{plan.id}]: changed {', '.join(changed_fields)}",
            }
        )


@register("agents/director/plan/InsertTask")
class InsertTask(Node):
    """
    Inserts a new task into the active plan at a given position.

    Position can be "start", "end", or an existing task ID (inserts after that task).
    The task dict is auto-validated as Beat or Task based on fields present.
    Blocked if the plan is completed.
    """

    class Fields:
        position = PropertyField(
            name="position",
            type="str",
            description="Where to insert: 'start', 'end', or a task ID to insert after",
            default="end",
        )

    def __init__(self, title="Insert Task", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("task", socket_type="dict")
        self.add_input("position", socket_type="str", optional=True)
        self.add_output("state")
        self.add_output("result", socket_type="str")

        self.set_property("position", "end")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        raw_task = self.require_input("task")
        position = self.normalized_input_value("position") or "end"
        scene = active_scene.get()

        plan = get_active_plan(scene)
        if not plan:
            raise ActionFailed("No active plan")

        locked = check_plan_locked(plan)
        if locked:
            raise ActionFailed(locked)

        if not isinstance(raw_task, dict):
            raise ActionFailed("Task must be a dict")

        try:
            task = _validate_task(raw_task, order=0)
        except Exception as e:
            raise ActionFailed(f"Invalid task: {e}") from e

        try:
            plan.insert_task(task, position)
        except ValueError as e:
            raise ActionFailed(str(e)) from e

        save_plan(scene, plan)
        emit_plan_for_chat(plan)

        log.info(
            "plan.insert_task", plan_id=plan.id, task_id=task.id, position=position
        )
        self.set_output_values(
            {
                "state": input_state,
                "result": f"Inserted task [{task.id}] at position '{position}' in plan [{plan.id}]. Now {len(plan.tasks)} tasks.",
            }
        )


@register("agents/director/plan/DeletePlan")
class DeletePlan(Node):
    """
    Deletes the active plan.

    Also unlinks the plan from the active director chat.
    """

    def __init__(self, title="Delete Plan", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        self.add_output("result", socket_type="str")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        scene = active_scene.get()

        plan = get_active_plan(scene)
        if not plan:
            raise ActionFailed("No active plan")

        deleted = delete_plan(scene, plan.id)
        if not deleted:
            raise ActionFailed(f"Failed to delete plan '{plan.id}'")

        # Unlink from active chat and notify frontend
        chat_ctx = director_chat_context.get()
        chat_id = chat_ctx.chat_id if chat_ctx else None
        if chat_ctx and chat_ctx.plan_id == plan.id:
            chat_ctx.plan_id = None

        # Clear persisted plan_id on the chat object
        director = get_agent("director")
        if chat_id:
            chat = director.chat_get(chat_id)
            if chat and chat.plan_id == plan.id:
                chat.plan_id = None
                director._chat_save(chat)

        emit_plan_updated(None, chat_id=chat_id)

        log.info("plan.delete", plan_id=plan.id)
        self.set_output_values(
            {
                "state": input_state,
                "result": f"Deleted plan [{plan.id}]",
            }
        )
