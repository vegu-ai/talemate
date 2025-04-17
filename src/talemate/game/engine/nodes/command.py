import structlog
from typing import ClassVar
import talemate.emit.async_signals as signals
from .core import Listen, Node, Graph, GraphState, NodeVerbosity, PropertyField, UNRESOLVED, InputValueError
from .run import FunctionWrapper
from .base_types import base_node_type
from .registry import register
from .run import Function
from talemate.emit import emit, Emission
from talemate.emit.signals import handlers
from talemate.context import active_scene
from talemate.game.engine.api.schema import StatusEnum

__all__ = ["Command", "InitializeCommand"]

log = structlog.get_logger("talemate.game.engine.nodes.command")


@base_node_type("command/Command")
class Command(Function):
    """
    A command is a node that can be executed by the player
    """
    
    _isolated: ClassVar[bool] = True
    _export_definition: ClassVar[bool] = False
    
    
    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the command",
            type="str",
            default=""
        )
    
    
    def __init__(self, title="Command", **kwargs):
        super().__init__(title=title, **kwargs)
        if not self.get_property("name"):
            self.set_property("name", "")
    
    async def execute_command(self, state:GraphState, **kwargs):
        wrapped = FunctionWrapper(self, self, state)
        await wrapped(**kwargs)
