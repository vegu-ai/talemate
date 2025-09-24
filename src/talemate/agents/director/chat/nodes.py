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
)
from talemate.game.engine.nodes.registry import register, base_node_type
from talemate.game.engine.nodes.run import Function, FunctionWrapper
from talemate.game.engine.nodes.focal import FocalArgument
from talemate.emit import emit
from talemate.context import active_scene

from .context import director_chat_context
from .exceptions import DirectorChatActionRejected

log = structlog.get_logger("talemate.game.engine.nodes.agents.director.chat")


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


@register("agents/director/chat/ActionArgument")
class DirectorChatActionArgument(FocalArgument):
    """
    A argument is a node that can be used as an argument to a director chat action
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
    If the is a chat context active that requires confirmation for write
    actions, this node will block the further execution of the node graph
    and send a signal to the frontend to collect the confirmation from the user (or reject the action)
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
        max_wait_time: int = 180
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
                        log.warning("Director Chat Action Confirm: Scene is no longer active", node=self.id)
                        rejected_state = state_value
                        break
                    
                    log.debug(
                        "Director Chat Action Confirm: Waiting for confirmation",
                        node=self.id,
                    )
                    await asyncio.sleep(1)
                    if time.time() - start_time > max_wait_time:
                        log.error(
                            "Director Chat Action Confirm: Max wait time reached",
                            node=self.id,
                        )
                        rejected_state = state_value
                        break

                if state.shared[key] == "reject":
                    rejected_state = state_value

                if raise_on_reject and rejected_state is not UNRESOLVED:
                    raise DirectorChatActionRejected(name, description)
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
