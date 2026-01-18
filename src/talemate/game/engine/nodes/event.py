import uuid
import structlog
import talemate.emit.async_signals as signals
from .core import Listen, Node, Graph, GraphState, NodeVerbosity, PropertyField
from .registry import register
from talemate.agents.registry import get_agent_types
from talemate.agents.base import Agent
from talemate.emit import emit
from talemate.util.colors import COLOR_NAMES
from talemate.context import active_scene
from talemate.game.engine.api.schema import StatusEnum

__all__ = [
    "collect_listeners",
    "connect_listeners",
    "disconnect_listeners",
]

log = structlog.get_logger("talemate.game.engine.nodes.event")


def collect_listeners(graph: Graph) -> dict[str, list["Listen"]]:
    """
    Does a deep search of the graph to find all Listen nodes

    Args:
        graph: Graph to search

    Returns:
        dict[str, list["Listen"]]: A dictionary of event names to Listen nodes
    """

    event_listeners = {}
    for node in graph.nodes.values():
        if isinstance(node, Listen):
            event_name = node.get_property("event_name")

            if not event_name:
                log.warning("Listen node has no event name", node=node)
                continue

            event_listeners.setdefault(event_name, []).append(node)
        elif isinstance(node, Graph):
            event_listeners.update(collect_listeners(node))

    return event_listeners


def connect_listeners(graph: Graph, state: GraphState, disconnect: bool = False):
    """
    Connects all Listen nodes in the graph to the event bus

    Args:
        graph: Graph to search
    """

    event_listeners = collect_listeners(graph)

    for event_name, listeners in event_listeners.items():
        for listener in listeners:
            signal = signals.get(event_name)
            if not signal:
                log.warning("Event not found", event_name=event_name)
                continue

            if state.verbosity == NodeVerbosity.NORMAL:
                log.debug(
                    "Connecting listener", listener=listener, event_name=event_name
                )

            if disconnect:
                signal.disconnect(listener.execute_from_event)

            signal.connect(listener.execute_from_event)


def disconnect_listeners(graph: Graph, state: GraphState):
    """
    Disconnects all Listen nodes in the graph from the event bus

    Args:
        graph: Graph to search
    """

    event_listeners = collect_listeners(graph)
    for event_name, listeners in event_listeners.items():
        for listener in listeners:
            signal = signals.get(event_name)
            if not signal:
                log.warning("Event not found", event_name=event_name)
                continue

            if state.verbosity == NodeVerbosity.NORMAL:
                log.debug(
                    "Disconnecting listener", listener=listener, event_name=event_name
                )

            signal.disconnect(listener.execute_from_event)


@register("event/Event")
class State(Graph):
    """
    Returns the current event object when inside a Listen node module.

    Outputs:

    - event: The current event object
    """

    def __init__(self, title="Event", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("event", socket_type="event")

    async def run(self, state: GraphState):
        self.set_output_values(
            {
                "event": state.data.get("event"),
            }
        )


@register("event/EmitStatus")
class EmitStatus(Node):
    """
    Emits a status message

    Inputs:

    - message: The message text to emit
    - status: The status of the message
    - as_scene_message: Whether to emit the message as a scene message (optional)


    Outputs:

    - emitted: Whether the message was emitted (True) or not (False)
    """

    class Fields:
        message = PropertyField(
            name="message",
            description="The message text to emit",
            type="str",
            default="",
        )

        status = PropertyField(
            name="status",
            description="The status of the message",
            type="str",
            default="info",
            generate_choices=lambda: sorted(list(StatusEnum.__members__.keys())),
        )

        as_scene_message = PropertyField(
            name="as_scene_message",
            description="Whether to emit the message as a scene message",
            type="bool",
            default=False,
        )

    def __init__(self, title="Emit Status", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("message", socket_type="str", optional=True)
        self.add_input("status", socket_type="str", optional=True)
        self.add_input("as_scene_message", socket_type="bool", optional=True)

        self.set_property("message", "")
        self.set_property("status", "info")
        self.set_property("as_scene_message", False)

        self.add_output("emitted", socket_type="bool")

    async def run(self, state: GraphState):
        message_text = self.require_input("message")
        status = self.require_input("status")
        as_scene_message = self.get_input_value("as_scene_message")
        scene = active_scene.get()

        data = {}

        if as_scene_message is True:
            data["as_scene_message"] = True

        emit("status", message=message_text, status=status, scene=scene, data=data)

        self.set_output_values(
            {
                "emitted": True,
            }
        )


@register("event/EmitSystemMessage")
class EmitSystemMessage(EmitStatus):
    """
    Emits a system message

    Inputs:

    - state: The graph state
    - message: The message text to emit


    Outputs:

    - state: The graph state
    """

    class Fields:
        message_title = PropertyField(
            name="message_title",
            description="The title of the message",
            type="str",
            default="",
        )
        message = PropertyField(
            name="message",
            description="The message text to emit",
            type="text",
            default="",
        )
        font_color = PropertyField(
            name="font_color",
            description="The color of the message",
            type="str",
            default="grey",
            generate_choices=lambda: COLOR_NAMES,
        )
        icon = PropertyField(
            name="icon",
            description="The icon of the message",
            type="str",
            default="mdi-information",  # information
        )
        display = PropertyField(
            name="display",
            description="Whether to display the message",
            type="str",
            default="text",
            generate_choices=lambda: ["text", "tonal", "flat"],
        )
        as_markdown = PropertyField(
            name="as_markdown",
            description="Whether to render the message as markdown",
            type="bool",
            default=False,
        )

    def __init__(self, title="Emit System Message", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("message_title", socket_type="str", optional=True)
        self.add_input("message", socket_type="str", optional=True)
        self.set_property("message_title", "")
        self.set_property("message", "")
        self.set_property("font_color", "grey")
        self.set_property("icon", "mdi-information")
        self.set_property("display", "text")
        self.set_property("as_markdown", False)
        self.add_output("state")

    async def run(self, state: GraphState):
        state = self.get_input_value("state")
        message = self.require_input("message")
        message_title = self.get_input_value("message_title")
        font_color = self.get_property("font_color")
        icon = self.get_property("icon")
        display = self.get_property("display")
        as_markdown = self.get_property("as_markdown")
        emit(
            "system",
            message=message,
            meta={
                "color": font_color,
                "icon": icon,
                "title": message_title,
                "display": display,
                "as_markdown": as_markdown,
            },
        )
        self.set_output_values(
            {
                "state": state,
            }
        )


@register("event/EmitStatusConditional")
class EmitStatusConditional(EmitStatus):
    """
    Emits a status message if a condition is met

    Inputs:

    - state: The graph state
    - message: The message text to emit
    - status: The status of the message
    - as_scene_message: Whether to emit the message as a scene message (optional)

    Outputs:

    - state: The graph state
    - emitted: Whether the message was emitted (True) or not (False)
    """

    def __init__(self, title="Emit Status (Conditional)", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        super().setup()

    async def run(self, state: GraphState):
        _state = self.get_input_value("state")
        await super().run(state)
        self.set_output_values(
            {
                "state": _state,
            }
        )


@register("event/EmitSceneStatus")
class EmitSceneStatus(Node):
    """
    Emits the scene status object to the UX

    Inputs:

    - state: The graph state

    Outputs:

    - state: The scene status object
    """

    def __init__(self, title="Emit Scene Status", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")

    async def run(self, state: GraphState):
        _state = self.get_input_value("state")
        scene = active_scene.get()
        scene.emit_status()
        self.set_output_values(
            {
                "state": _state,
            }
        )


@register("event/EmitWorldEditorSync")
class EmitWorldEditorSync(Node):
    """
    Sends a world editor sync message which on the UX side
    will cause the world editor to sync its state with the server

    This is useful when the world editor needs to be updated with the latest state.
    """

    def __init__(self, title="Emit World Editor Sync", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")

    async def run(self, state: GraphState):
        emit(
            "world_state_manager", kwargs={"action": "sync"}, websocket_passthrough=True
        )
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
            }
        )


@register("event/EmitAgentMessage")
class EmitAgentMessage(Node):
    """
    Emits an agent message

    EXAMPLE
            emit("agent_message",
                message=message,
                data={
                    "uuid": str(uuid.uuid4()),
                    "agent": "editor",
                    "header": "Removed repetition",
                    "color": "highlight4",
                },
                meta={
                    "action": "revision_dedupe",
                    "similarity": dedupe['similarity'],
                    "threshold": self.revision_repetition_threshold,
                    "range": self.revision_repetition_range,
                },
                websocket_passthrough=True
            )


    Inputs:

    - state: The graph state
    - message: The message text to emit
    - agent: The agent
    - header: The header of the message
    - color: The color of the message
    - meta: The meta data of the message

    Outputs:

    - emitted: Whether the message was emitted (True) or not (False)

    """

    class Fields:
        message = PropertyField(
            name="message",
            description="The message text to emit",
            type="str",
            default="",
        )

        agent = PropertyField(
            name="agent",
            type="str",
            default="",
            description="The name of the agent to get the client for",
            choices=[],
            generate_choices=lambda: get_agent_types(),
        )

        header = PropertyField(
            name="header",
            description="The header of the message",
            type="str",
            default="",
        )

        message_color = PropertyField(
            name="message_color",
            description="The color of the message",
            type="str",
            default="grey",
            generate_choices=lambda: COLOR_NAMES,
        )

        meta = PropertyField(
            name="meta",
            description="The meta data of the message",
            type="dict",
            default={},
        )

    def __init__(self, title="Emit Agent Message", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")

        self.add_input("message", socket_type="str", optional=True)
        self.add_input("agent", socket_type="agent,str", optional=True)
        self.add_input("header", socket_type="str", optional=True)
        self.add_input("message_color", socket_type="str", optional=True)
        self.add_input("meta", socket_type="dict", optional=True)

        self.set_property("message", "")
        self.set_property("agent", "")
        self.set_property("header", "")
        self.set_property("message_color", "grey")
        self.set_property("meta", {})

        self.add_output("emitted", socket_type="bool")

    async def run(self, state: GraphState):
        message = self.require_input("message")
        agent = self.require_input("agent")
        header = self.require_input("header")
        message_color = self.require_input("message_color")
        meta = self.require_input("meta")

        if isinstance(agent, Agent):
            agent_name = agent.name
        else:
            agent_name = agent

        data = {
            "uuid": str(uuid.uuid4()),
            "agent": agent_name,
            "header": header,
            "color": message_color,
        }

        emit(
            "agent_message",
            message=message,
            data=data,
            meta=meta,
            websocket_passthrough=True,
        )

        self.set_output_values(
            {
                "emitted": True,
            }
        )
