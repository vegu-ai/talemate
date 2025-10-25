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
    A node that signals that an operation has been done
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
    A node that signals that an operation has failed
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
    A node that queues a response to be sent to the websocket
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
    A node that gets a websocket router
    """

    class Fields:
        router = PropertyField(
            name="router",
            description="The router to get the websocket plugin for",
            type="str",
            default="",
            choices=[],
            generate_choices=lambda: [
                router.router for router in active_websocket_handler().routes.values()
            ],
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
