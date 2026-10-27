import structlog
from typing import ClassVar
from .core import (
    GraphState,
    PropertyField,
    UNRESOLVED,
)
from .run import FunctionWrapper
from .base_types import base_node_type
from .run import Function

__all__ = ["Command"]

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
            name="name", description="The name of the command", type="str", default=""
        )
        icon = PropertyField(
            name="icon",
            description="Icon shown for this command in the scene tools menu",
            type="icon",
            default="mdi-console-line",
        )
        menu = PropertyField(
            name="menu",
            description="Menu id - commands with the same menu id group into one sub menu of the custom commands scene tools menu. Empty keeps the command typed-only.",
            type="str",
            default="",
        )

    def __init__(self, title="Command", **kwargs):
        super().__init__(title=title, **kwargs)
        if not self.get_property("name"):
            self.set_property("name", "")
        if self.get_property("icon") in (UNRESOLVED, None, ""):
            self.set_property("icon", "mdi-console-line")
        if self.get_property("menu") in (UNRESOLVED, None):
            self.set_property("menu", "")

    async def execute_command(self, state: GraphState, **kwargs):
        wrapped = FunctionWrapper(self, self, state)
        await wrapped(**kwargs)
