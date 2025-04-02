import structlog
import talemate.emit.async_signals as signals
from .core import Listen, Node, Graph, GraphState, NodeVerbosity, PropertyField
from .registry import register
from talemate.emit import emit, Emission
from talemate.emit.signals import handlers
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
                log.debug("Connecting listener", listener=listener, event_name=event_name)
            
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
                log.debug("Disconnecting listener", listener=listener, event_name=event_name)
            
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
        self.set_output_values({
            "event": state.data.get("event"),
        })
        
        
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
        
        self.set_output_values({
            "emitted": True,
        })