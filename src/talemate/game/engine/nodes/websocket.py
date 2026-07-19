import structlog
from typing import TYPE_CHECKING

from talemate.game.engine.nodes.core import (
    Node,
    register,
    GraphState,
    PropertyField,
    InputValueError,
    TYPE_CHOICES,
)

from talemate.server.websocket_plugin import Plugin

if TYPE_CHECKING:
    from talemate.server.websocket_server import WebsocketHandler

log = structlog.get_logger("talemate.game.engine.nodes.websocket")

TYPE_CHOICES.extend(
    [
        "websocket_handler",
        "websocket_router",
    ]
)


def active_websocket_handler() -> "WebsocketHandler":
    from talemate.server.api import get_active_frontend_handler

    return get_active_frontend_handler()


def get_websocket_router(router: str) -> Plugin:
    websocket_handler = active_websocket_handler()
    return websocket_handler.routes.get(router)


class WebsocketBase(Node):
    """
    Base class for websocket nodes
    """

    def __init__(self, title="Websocket", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("websocket_router", socket_type="websocket_router")

        self.add_output("state")
        self.add_output("websocket_router", socket_type="websocket_router")

    def validate_websocket_router(self) -> Plugin:
        websocket_router = self.normalized_input_value("websocket_router")
        if not isinstance(websocket_router, Plugin):
            raise InputValueError(
                self, "websocket_router", "Websocket plugin is not valid"
            )
        return websocket_router


@register("websocket/signals/OperationDone")
class OperationDone(WebsocketBase):
    """
    Signal to the frontend that a websocket operation has completed successfully.

    Sends an `operation_done` message through the websocket router, optionally
    emits a status message and - unless `signal_only` is set - triggers an auto
    save of the scene (or marks the scene as unsaved when auto save is off or
    disallowed).

    Inputs:

    - state: The graph state
    - websocket_router: The websocket router (plugin) to signal through
    - signal_only: If true, only send the signal and skip the save handling (optional)
    - allow_auto_save: Whether to allow the scene to auto save after the operation (optional)
    - emit_status_message: Status message to display in the frontend (optional)

    Outputs:

    - state: The state input, passed through
    - websocket_router: The websocket router, passed through
    """

    class Fields:
        signal_only = PropertyField(
            name="signal_only",
            description="Whether to signal only or emit a status",
            type="bool",
            default=False,
        )
        allow_auto_save = PropertyField(
            name="allow_auto_save",
            description="Whether to allow auto save",
            type="bool",
            default=True,
        )
        emit_status_message = PropertyField(
            name="emit_status_message",
            description="The status message to emit",
            type="str",
            default="",
        )

    def __init__(self, title="Websocket Operation Done", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("signal_only", socket_type="bool", optional=True)
        self.add_input("allow_auto_save", socket_type="bool", optional=True)
        self.add_input("emit_status_message", socket_type="str", optional=True)

        self.set_property("signal_only", False)
        self.set_property("allow_auto_save", True)
        self.set_property("emit_status_message", "")

    async def run(self, state: GraphState):
        signal_only = self.normalized_input_value("signal_only")
        allow_auto_save = self.normalized_input_value("allow_auto_save")
        emit_status_message = self.normalized_input_value("emit_status_message")
        websocket_router = self.validate_websocket_router()
        await websocket_router.signal_operation_done(
            signal_only=signal_only,
            allow_auto_save=allow_auto_save,
            emit_status_message=emit_status_message,
        )

        self.set_output_values({"state": state, "websocket_router": websocket_router})


@register("websocket/signals/OperationFailed")
class OperationFailed(WebsocketBase):
    """
    Signal to the frontend that a websocket operation has failed.

    Sends an `operation_done` message carrying the error through the websocket
    router and optionally emits an error status message in the frontend.

    Inputs:

    - state: The graph state
    - websocket_router: The websocket router (plugin) to signal through
    - message: The error message (optional)
    - emit_status: Whether to also emit an error status message (optional)

    Outputs:

    - state: The state input, passed through
    - websocket_router: The websocket router, passed through
    """

    class Fields:
        message = PropertyField(
            name="message",
            description="The message to emit",
            type="str",
            default="",
        )

        emit_status = PropertyField(
            name="emit_status",
            description="Whether to emit a status",
            type="bool",
            default=True,
        )

    def __init__(self, title="Websocket Operation Failed", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("message", socket_type="str", optional=True)
        self.add_input("emit_status", socket_type="bool", optional=True)

        self.set_property("message", "")
        self.set_property("emit_status", True)

    async def run(self, state: GraphState):
        message = self.normalized_input_value("message")
        emit_status = self.normalized_input_value("emit_status")
        websocket_router = self.validate_websocket_router()
        await websocket_router.signal_operation_failed(
            message=message, emit_status=emit_status
        )
        self.set_output_values({"state": state, "websocket_router": websocket_router})


@register("websocket/WebsocketResponse")
class QueueResponse(WebsocketBase):
    """
    Queue a message to be sent to the frontend through the websocket.

    The message is sent with the router's name as its type, the given action
    name, and the data dict merged into the message payload.

    Inputs:

    - state: The graph state
    - websocket_router: The websocket router (plugin) to send the message through
    - action: The action name of the message
    - data: Dict of additional payload fields merged into the message

    Outputs:

    - state: The state input, passed through
    - websocket_router: The websocket router, passed through
    - action: The action input, passed through
    - data: The data input, passed through
    """

    class Fields:
        action = PropertyField(
            name="action",
            description="The action to send to the websocket",
            type="str",
            default="",
        )
        data = PropertyField(
            name="data",
            description="The data to send to the websocket",
            type="dict",
            default={},
        )

    def __init__(self, title="Websocket Response", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("action", socket_type="str")
        self.add_input("data", socket_type="dict")

        self.set_property("action", "")
        self.set_property("data", {})

        self.add_output("action", socket_type="str")
        self.add_output("data", socket_type="dict")

    async def run(self, state: GraphState):
        action = self.normalized_input_value("action")
        data = self.normalized_input_value("data")
        websocket_router = self.validate_websocket_router()
        websocket_router.websocket_handler.queue_put(
            {
                "type": websocket_router.router,
                "action": action,
                **data,
            }
        )
        self.set_output_values(
            {
                "state": state,
                "websocket_router": websocket_router,
                "action": action,
                "data": data,
            }
        )


@register("websocket/GetWebsocketRouter")
class GetWebsocketRouter(Node):
    """
    Get a websocket router (plugin) by its route name from the active
    websocket handler.

    Raises an error if no plugin is registered for the given route.

    Properties:

    - router: The route name to get the websocket plugin for

    Outputs:

    - router: The route name, passed through
    - websocket_router: The websocket router (plugin) instance
    - websocket_handler: The active websocket handler
    """

    class Fields:
        router = PropertyField(
            name="router",
            description="The router to get the websocket plugin for",
            type="str",
            default="",
            choices=[],
            generate_choices=lambda: (
                [router.router for router in active_websocket_handler().routes.values()]
                if active_websocket_handler() is not None
                else []
            ),
        )

    def __init__(self, title="Get Websocket Router", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("router", "")
        self.add_output("router", socket_type="str")
        self.add_output("websocket_router", socket_type="websocket_router")
        self.add_output("websocket_handler", socket_type="websocket_handler")

    async def run(self, state: GraphState):
        router = self.require_input("router")
        websocket_router = get_websocket_router(router)

        if not websocket_router:
            raise InputValueError(
                self, "router", f"Websocket plugin not found for router: {router}"
            )

        websocket_handler = active_websocket_handler()
        self.set_output_values(
            {
                "state": state,
                "websocket_router": websocket_router,
                "websocket_handler": websocket_handler,
                "router": router,
            }
        )
