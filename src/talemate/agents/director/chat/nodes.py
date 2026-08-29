import structlog
from typing import ClassVar
import pydantic
import asyncio
import time
from talemate.game.engine.nodes.core import (
    GraphState,
    PropertyField,
    NodeStyle,
    Node,
    UNRESOLVED,
    TYPE_CHOICES,
    InputValueError,
)
from talemate.game.engine.nodes.registry import register, base_node_type
from talemate.game.engine.nodes.run import Function, FunctionWrapper
from talemate.game.engine.nodes.focal import FocalArgument
from talemate.game.engine.nodes.agent import AgentNode
from talemate.emit import emit
from talemate.instance import get_agent
from talemate.context import active_scene

from .context import director_chat_context
from .schema import DirectorChatMessage
from talemate.agents.director.action_core.exceptions import ActionRejected
from talemate.agents.director.action_core.gating import (
    is_action_id_enabled,
    ActionMode,
    CallbackDescriptor,
)
from talemate.agents.director.scene_direction.mixin import scene_direction_context

log = structlog.get_logger("talemate.game.engine.nodes.agents.director.chat")

TYPE_CHOICES.extend(
    [
        "director/chat_message",
    ]
)


@base_node_type("agents/director/DirectorChatAction")
class DirectorChatAction(Function):
    """
    A action is a node that can be executed by the director during chat with the user
    """

    _isolated: ClassVar[bool] = True
    _export_definition: ClassVar[bool] = False

    class Fields:
        name = PropertyField(
            name="name", description="The name of the action", type="str", default=""
        )
        description = PropertyField(
            name="description",
            description="The description of the action",
            type="text",
            default="",
        )
        instructions = PropertyField(
            name="instructions",
            description="The instructions for the action",
            type="text",
            default="",
        )
        example_json = PropertyField(
            name="example_json",
            description="An example JSON payload for the action",
            type="text",
            default=None,
        )
        allow_concurrent = PropertyField(
            name="allow_concurrent",
            description="Whether the action can be called concurrently",
            type="bool",
            default=False,
        )

    def __init__(self, title="Command", **kwargs):
        super().__init__(title=title, **kwargs)
        if not self.get_property("name"):
            self.set_property("name", "")
        if not self.get_property("description"):
            self.set_property("description", "")

    async def execute_action(self, state: GraphState, **kwargs):
        wrapped = FunctionWrapper(self, self, state)
        await wrapped(**kwargs)

    async def test_run(self, state: GraphState):
        return await self.execute_action(state, **{})


@register("agents/director/chat/DirectorChatSubAction")
class DirectorChatSubAction(Node):
    """
    Declares a sub-action inside a DirectorChatAction graph. Its properties
    describe one concrete operation the director can perform and are extracted
    statically (without running the graph) to advertise the sub-action in chat
    and scene direction prompts and in the enable/disable UI. At runtime the
    node acts as a gate: it evaluates the optional condition function and the
    gating rules (availability vs. current mode, force_enabled, per-scene
    disabled list) and only passes state through when the sub-action is
    enabled - otherwise the state output stays unresolved and the downstream
    branch is skipped.

    Inputs:

    - state: State to pass through when the sub-action is enabled
    - condition: Optional function; if it returns falsy the sub-action is
      neither advertised nor executed

    Outputs:

    - state: The state input, passed through when the sub-action is enabled;
      stays unresolved when the sub-action is gated off

    Properties:

    - group: Group label used to organize sub-actions in prompts and the UI
    - action_title: Human readable title of the sub-action
    - action_id: Unique id of the sub-action (required); used for gating and
      the per-scene disabled list
    - instruction_examples: Example instructions shown to the director to
      illustrate how to invoke the sub-action
    - description_chat: Description shown to the director in chat mode
    - description_scene_direction: Description shown to the director in scene
      direction mode (each description falls back to the other when unset)
    - availability: Which modes the sub-action is available in (both, chat or
      scene_direction)
    - force_enabled: If true, users cannot disable this sub-action
    """

    class Fields:
        group = PropertyField(
            name="group",
            description="The group of the action",
            type="str",
            default="",
        )
        action_title = PropertyField(
            name="action_title",
            description="The title of the action",
            type="str",
            default="",
        )
        action_id = PropertyField(
            name="action_id",
            description="The id of the action",
            type="str",
            default="",
        )
        instruction_examples = PropertyField(
            name="instruction_examples",
            description="The examples of the action instructions",
            type="list",
            default=[],
        )
        description_chat = PropertyField(
            name="description_chat",
            description="The description of the action in chat",
            type="text",
            default="",
        )
        description_scene_direction = PropertyField(
            name="description_scene_direction",
            description="The description of the action in scene direction",
            type="text",
            default="",
        )
        availability = PropertyField(
            name="availability",
            description="Which modes this action is available in",
            type="str",
            default="both",
            choices=["both", "chat", "scene_direction"],
        )
        force_enabled = PropertyField(
            name="force_enabled",
            description="If true, prevents users from disabling this action",
            type="bool",
            default=False,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2b273a",
            title_color="#3d315b",
            icon="F0295",
            auto_title="[{group}] {action_title}",
        )

    def __init__(self, title="Director Chat Sub Action", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state", socket_type="any", optional=True)
        self.add_input("condition", socket_type="function", optional=True)
        self.set_property("group", "")
        self.set_property("action_id", "")
        self.set_property("action_title", "")
        self.set_property("description_chat", "")
        self.set_property("description_scene_direction", "")
        self.set_property("instruction_examples", [])
        self.set_property("availability", "both")
        self.set_property("force_enabled", False)
        self.add_output("state", socket_type="any")

    def _detect_mode(self) -> ActionMode:
        """
        Detect the current execution mode based on context variables.

        Returns:
            "chat" if in a chat context, "scene_direction" if in scene direction context
        """
        # Check if we're in a scene direction turn
        ctx = scene_direction_context.get()
        if ctx.get("in_direction_turn"):
            return "scene_direction"

        # Check if we're in a chat context
        chat_ctx = director_chat_context.get()
        if chat_ctx is not None:
            return "chat"

        # Default to chat
        return "chat"

    async def run(self, state: GraphState):
        action_id = self.normalized_input_value("action_id")

        if not action_id:
            raise InputValueError(self, "action_id", "Action id is required")

        condition = self.normalized_input_value("condition")
        if condition:
            result = await condition()
            if not result:
                log.debug(
                    "director.sub_action.condition_failed",
                    action_id=action_id,
                    condition=condition,
                )
                self.set_output_values({"state": UNRESOLVED})
                return

        director = get_agent("director")
        mode = self._detect_mode()

        # Create a descriptor from node properties for consistent gating logic
        availability = self.normalized_input_value("availability") or "both"
        if availability not in ["both", "chat", "scene_direction"]:
            availability = "both"
        force_enabled = self.get_property("force_enabled") or False

        descriptor = CallbackDescriptor(
            action_id=action_id,
            action_title=self.normalized_input_value("action_title") or "",
            group=self.normalized_input_value("group") or "",
            description_chat=self.normalized_input_value("description_chat") or "",
            description_scene_direction=self.normalized_input_value(
                "description_scene_direction"
            )
            or "",
            instruction_examples=self.normalized_input_value("instruction_examples")
            or [],
            availability=availability,
            force_enabled=force_enabled,
        )

        # Check gating - handles availability, force_enabled, and denylist
        if not is_action_id_enabled(mode, action_id, director, descriptor=descriptor):
            log.debug(
                "director.sub_action.gated",
                action_id=action_id,
                mode=mode,
                availability=availability,
                force_enabled=force_enabled,
            )
            self.set_output_values({"state": UNRESOLVED})
            return

        # Pass through the state input if available, otherwise pass through None
        input_state = self.normalized_input_value("state")
        self.set_output_values({"state": input_state})


@register("agents/director/chat/ActionArgument")
class DirectorChatActionArgument(FocalArgument):
    """
    Declares an argument for a director chat action. Place it inside a
    DirectorChatAction graph to define one named, typed argument the
    director can pass when invoking the action; the instructions describe
    the argument to the director in the action prompt.

    Properties:

    - name: The name of the argument
    - typ: The type of the argument (str, int, float, bool, list, any)
    - instructions: Description of the argument shown to the director

    Outputs:

    - value: The argument's value (available while the action executes)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2c2a37",
            title_color="#144870",
            icon="F0AE7",  # variable
            auto_title="{name}",
        )

    def __init__(self, title="Director Action Argument", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/director/chat/ActionConfirm")
class DirectorChatActionConfirm(Node):
    """
    Asks the user to confirm a director action before it proceeds. Only
    active when the current director chat context requires confirmation
    for write actions - otherwise the state passes straight through as
    accepted. When active, the node emits a confirmation request to the
    frontend and blocks until the user responds, the scene ends, or the
    configured timeout is reached (timeouts and scene shutdown count as
    rejections).

    On acceptance the state is passed to the `accepted` output; on
    rejection it is passed to the `rejected` output instead - unless
    raise_on_reject is set (the default), in which case an ActionRejected
    error is raised and aborts the action.

    Inputs:

    - state: The state to gate on user confirmation
    - name: The name of the action to confirm (optional)
    - description: The description of the action to confirm (optional)

    Properties:

    - raise_on_reject: Whether to raise an error if the action is rejected

    Outputs:

    - accepted: The state input, set when the action was confirmed
    - rejected: The state input, set when the action was rejected
    - rejected_message: A message describing the rejection (only set on
      rejection)
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the action",
            type="str",
            default="",
        )
        description = PropertyField(
            name="description",
            description="The description of the action",
            type="text",
            default="",
        )
        raise_on_reject = PropertyField(
            name="raise_on_reject",
            description="Whether to raise an error if the action is rejected",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            # caution/confirm theme close to validation/breakpoint family
            node_color="#2b273a",
            title_color="#3d315b",
            icon="F02D6",  # help-circle-outline
            auto_title="Confirm Action",
        )

    def __init__(self, title="Director Action Confirm", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("name", socket_type="str", optional=True)
        self.add_input("description", socket_type="str", optional=True)
        self.set_property("name", "")
        self.set_property("description", "")
        self.set_property("raise_on_reject", True)
        self.add_output("accepted")
        self.add_output("rejected")
        self.add_output("rejected_message", socket_type="str")

    async def run(self, state: GraphState):
        state_value = self.get_input_value("state")
        director = get_agent("director")
        max_wait_time: int = director.chat_action_confirm_timeout
        key: str = f"_director_chat_action_confirm_{self.id}"
        name: str = self.normalized_input_value("name")
        description: str = self.normalized_input_value("description")
        raise_on_reject: bool = self.get_property("raise_on_reject")
        scene = active_scene.get()

        rejected_state = UNRESOLVED

        try:
            context = director_chat_context.get()
            if context and context.confirm_write_actions:
                state.shared[key] = "waiting"
                start_time = time.time()
                emit(
                    "request_action_confirmation",
                    data={
                        "chat_id": context.chat_id,
                        "id": self.id,
                        "name": name,
                        "description": description,
                        "timer": max_wait_time,
                    },
                    websocket_passthrough=True,
                )
                while state.shared[key] == "waiting":
                    if not scene.active:
                        log.warning(
                            "Director Chat Action Confirm: Scene is no longer active",
                            node=self.id,
                        )
                        rejected_state = state_value
                        break

                    log.debug(
                        "Director Chat Action Confirm: Waiting for confirmation",
                        node=self.id,
                    )
                    await asyncio.sleep(1)
                    if max_wait_time and time.time() - start_time > max_wait_time:
                        log.error(
                            "Director Chat Action Confirm: Max wait time reached",
                            node=self.id,
                        )
                        rejected_state = state_value
                        break

                if state.shared[key] == "reject":
                    rejected_state = state_value

                if raise_on_reject and rejected_state is not UNRESOLVED:
                    raise ActionRejected(name, description)
        except LookupError:
            pass
        finally:
            if key in state.shared:
                del state.shared[key]

        log.debug("Director Chat Action Confirm: Final output", rejected=rejected_state)

        if rejected_state is not UNRESOLVED:
            message = f"User REJECTED action: {name} -> {description}"
            self.set_output_values(
                {"rejected": rejected_state, "rejected_message": message}
            )
        else:
            self.set_output_values({"accepted": state_value})


@register("agents/director/InsertChatMessage")
class InsertChatMessage(AgentNode):
    """
    Inserts a message into the director chat.
    Can optionally display an asset from scene_assets by providing an asset_id.
    """

    _agent_name: ClassVar[str] = "director"

    class Fields:
        message = PropertyField(
            name="message",
            type="text",
            description="The message to insert",
            default="",
        )
        source = PropertyField(
            name="source",
            type="str",
            description="The source of the message",
            default="user",
            choices=["user", "director"],
        )
        asset_id = PropertyField(
            name="asset_id",
            type="str",
            description="Optional asset ID from scene_assets library to display",
            default="",
        )

    def __init__(self, title="Insert Chat Message", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("message", socket_type="str")
        self.add_input("source", socket_type="str", optional=True)
        self.add_input("asset_id", socket_type="str", optional=True)

        self.set_property("message", "")
        self.set_property("source", "user")
        self.set_property("asset_id", "")

        self.add_output("state")
        self.add_output("chat_message", socket_type="director/chat_message")
        self.add_output("message", socket_type="str")
        self.add_output("source", socket_type="str")
        self.add_output("asset_id", socket_type="str")

    async def run(self, state: GraphState):
        message_content = self.require_input("message")
        source = self.normalized_input_value("source") or "user"
        asset_id = self.normalized_input_value("asset_id")

        # If asset_id is provided, validate it exists
        if asset_id:
            scene = active_scene.get()
            if not scene.assets.validate_asset_id(asset_id):
                raise ValueError(f"Asset not found: {asset_id}")

        # Resolve the target chat: prefer the chat that initiated the
        # current action (director chat context), fall back to the active
        # chat and only create a new one as a last resort.
        chat = None
        context = director_chat_context.get()
        if context and context.chat_id:
            chat = self.agent.chat_get(context.chat_id)
        if not chat:
            chat = self.agent.chat_get_or_create_active()

        message = DirectorChatMessage(
            message=message_content,
            source=source,
            type="asset_view" if asset_id else "text",
            asset_id=asset_id if asset_id else None,
        )

        # Append message
        await self.agent.chat_append_message(chat.id, message)

        emit(
            "director",
            message=message_content,
            data={
                "action": "chat_require_sync",
                "chat_id": chat.id,
            },
            websocket_passthrough=True,
        )

        output_values = {
            "state": state,
            "chat_message": message,
            "source": source,
            "message": message_content,
        }
        if asset_id:
            output_values["asset_id"] = asset_id

        self.set_output_values(output_values)


@register("agents/director/chat/GetDirectorChatContext")
class GetDirectorChatContext(Node):
    """
    Exposes the active DirectorChatContext as a dict for graph consumption.

    Use this when a graph needs to read flags off the current director chat
    (e.g. close_arc, chat_id, plan_id) without reaching into Python context.
    The `context` output is a plain dict that can be wired into template_vars
    or inspected directly; fields are added as the DirectorChatContext grows
    without requiring node socket changes.

    When no chat context is active, `has_context` is False and `context` is
    an empty dict.
    """

    def __init__(self, title="Get Director Chat Context", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        self.add_output("has_context", socket_type="bool")
        self.add_output("context", socket_type="dict")

    async def run(self, state: GraphState):
        input_state = self.require_input("state")
        ctx = director_chat_context.get()
        # Exclude `token` — it's the contextvars reset handle, not state worth
        # exposing. Private fields (_context_id_collector) are already dropped
        # by pydantic's model_dump.
        context_dict = ctx.model_dump(exclude={"token"}) if ctx is not None else {}

        self.set_output_values(
            {
                "state": input_state,
                "has_context": ctx is not None,
                "context": context_dict,
            }
        )
