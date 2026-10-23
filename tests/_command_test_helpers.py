"""
Shared helpers for the scene command tests.

Command modules are built programmatically: a `Command` subclass registered
in a per-test container that is bound to the scene as `_NODE_DEFINITIONS`,
which is where `get_nodes_by_base_type` / `get_node` look first.
"""

from __future__ import annotations

import asyncio

from talemate.game.engine.nodes.command import Command
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.run import FunctionArgument


def make_command(
    scene,
    registry_name: str,
    *,
    name: str,
    title: str,
    icon: str | None = None,
    menu: str | None = None,
    args: list[tuple] = None,
    on_execute=None,
):
    """Register a command module in `scene._NODE_DEFINITIONS`.

    `args` is a list of (arg_name, arg_type) tuples - pass `UNRESOLVED` or an
    empty string as the arg name to build an unnamed argument node.
    """

    @register(registry_name, container=scene._NODE_DEFINITIONS)
    class TestCommand(Command):
        def __init__(self, **kwargs):
            kwargs.setdefault("title", title)
            super().__init__(**kwargs)
            self.set_property("name", name)
            if icon is not None:
                self.set_property("icon", icon)
            if menu is not None:
                self.set_property("menu", menu)

            for arg_name, arg_type in args or []:
                arg_node = FunctionArgument()
                arg_node.set_property("name", arg_name)
                arg_node.set_property("typ", arg_type)
                self.add_node(arg_node)

        async def execute_command(self, state, **kwargs):
            if on_execute:
                on_execute(kwargs)

    TestCommand._base_type = "command/Command"

    return TestCommand


async def wait_for(condition, tries: int = 20):
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)
