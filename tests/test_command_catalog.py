"""
Unit tests for the scene tools command catalog.

Covers the `command/Command` node metadata (icon/menu), the rich catalog
built by `SceneLoop.register_commands` and the shared `run_node_command`
helper that both the typed `!command` path and the scene tools menu use.

Command modules are built programmatically - see `_command_test_helpers`.
"""

import asyncio

import pytest

import talemate.emit.async_signals as async_signals
import talemate.game.engine.nodes.scene as scene_nodes
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.game.engine.nodes.command import Command
from talemate.game.engine.nodes.core import GraphContext, UNRESOLVED
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.run import FunctionArgument
from talemate.game.engine.nodes.scene import SceneLoop, WaitForInput, run_node_command

from conftest import MockScene, bootstrap_scene
from _command_test_helpers import make_command, wait_for
from _node_test_helpers import make_capture


@pytest.fixture
def scene():
    """Real Scene with bootstrapped agents and an empty node definition set."""
    s = MockScene()
    bootstrap_scene(s)
    s._NODE_DEFINITIONS = {}
    return s


async def build_catalog(scene) -> tuple[list[dict], dict]:
    loop = SceneLoop()
    with ActiveScene(scene):
        with GraphContext() as state:
            await loop.register_commands(scene, state)
            return state.data["_command_catalog"], state.data["_commands"]


def entries_by_name(catalog: list[dict]) -> dict:
    return {entry["name"]: entry for entry in catalog}


# ---------------------------------------------------------------------------
# Command node metadata
# ---------------------------------------------------------------------------


def test_command_node_metadata_defaults():
    node = Command()
    assert node.get_property("icon") == "mdi-console-line"
    assert node.get_property("menu") == ""


def test_command_node_metadata_field_definitions():
    fields = Command().field_definitions
    assert fields["icon"].type == "icon"
    assert fields["icon"].default == "mdi-console-line"
    assert fields["menu"].type == "str"
    assert fields["menu"].default == ""


def test_command_node_metadata_keeps_explicit_values():
    node = Command(properties={"icon": "mdi-sword", "menu": "combat"})
    assert node.get_property("icon") == "mdi-sword"
    assert node.get_property("menu") == "combat"


# ---------------------------------------------------------------------------
# SceneLoop.register_commands catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_commands_builds_catalog_entry(scene):
    make_command(
        scene,
        "test/commands/Attack",
        name="attack",
        title="Attack",
        icon="mdi-sword",
        menu="combat",
        args=[("target", "str"), ("damage", "int")],
    )

    catalog, commands = await build_catalog(scene)
    entry = entries_by_name(catalog)["attack"]

    assert entry == {
        "name": "attack",
        "label": "Attack",
        "icon": "mdi-sword",
        "menu": "combat",
        "args": [{"name": "target", "typ": "str"}, {"name": "damage", "typ": "int"}],
    }
    assert commands["attack"] == "test/commands/Attack"


@pytest.mark.asyncio
async def test_register_commands_skips_unnamed_args(scene):
    make_command(
        scene,
        "test/commands/Greet",
        name="greet",
        title="Greet",
        args=[("target", "str"), (UNRESOLVED, "str"), ("", "int")],
    )

    catalog, _ = await build_catalog(scene)
    entry = entries_by_name(catalog)["greet"]

    assert entry["args"] == [{"name": "target", "typ": "str"}]


@pytest.mark.asyncio
async def test_register_commands_defaults_icon_and_menu(scene):
    make_command(scene, "test/commands/Ponder", name="ponder", title="Ponder")

    catalog, commands = await build_catalog(scene)
    entry = entries_by_name(catalog)["ponder"]

    assert entry["icon"] == "mdi-console-line"
    assert entry["menu"] == ""
    assert entry["args"] == []
    assert commands["ponder"] == "test/commands/Ponder"


@pytest.mark.asyncio
async def test_register_commands_excludes_unnamed_commands(scene):
    make_command(scene, "test/commands/Nameless", name=UNRESOLVED, title="Nameless")
    make_command(scene, "test/commands/Blank", name="", title="Blank")
    make_command(scene, "test/commands/Named", name="named", title="Named")

    catalog, commands = await build_catalog(scene)

    assert [entry["name"] for entry in catalog] == ["named"]
    assert commands[UNRESOLVED] == "test/commands/Nameless"


@pytest.mark.asyncio
async def test_register_commands_coerces_metadata_to_strings(scene):
    make_command(scene, "test/commands/Odd", name="odd", title="Odd", menu=5)

    catalog, _ = await build_catalog(scene)
    entry = entries_by_name(catalog)["odd"]

    assert entry["menu"] == "5"


@pytest.mark.asyncio
async def test_register_commands_strips_whitespace_menu(scene):
    make_command(scene, "test/commands/Blank", name="blank", title="Blank", menu="  ")
    make_command(
        scene, "test/commands/Padded", name="padded", title="Padded", menu=" social "
    )

    catalog, _ = await build_catalog(scene)
    entries = entries_by_name(catalog)

    assert entries["blank"]["menu"] == ""
    assert entries["padded"]["menu"] == "social"


@pytest.mark.asyncio
async def test_register_commands_coerces_unknown_arg_type(scene):
    make_command(
        scene,
        "test/commands/Weird",
        name="weird",
        title="Weird",
        args=[("target", "wobble"), ("damage", UNRESOLVED)],
    )

    catalog, _ = await build_catalog(scene)
    entry = entries_by_name(catalog)["weird"]

    assert entry["args"] == [
        {"name": "target", "typ": "any"},
        {"name": "damage", "typ": "any"},
    ]


@pytest.mark.asyncio
async def test_register_commands_skips_non_string_arg_names(scene):
    make_command(
        scene,
        "test/commands/Numbered",
        name="numbered",
        title="Numbered",
        args=[(5, "str"), ("target", "str")],
    )

    catalog, _ = await build_catalog(scene)
    entry = entries_by_name(catalog)["numbered"]

    assert entry["args"] == [{"name": "target", "typ": "str"}]


@pytest.mark.asyncio
async def test_register_commands_dedupes_by_name(scene):
    make_command(scene, "test/commands/First", name="twice", title="First")
    make_command(scene, "test/commands/Second", name="twice", title="Second")

    catalog, commands = await build_catalog(scene)

    entries = [entry for entry in catalog if entry["name"] == "twice"]
    assert len(entries) == 1
    assert entries[0]["label"] == "Second"
    assert commands["twice"] == "test/commands/Second"


@pytest.mark.asyncio
async def test_register_commands_catalog_is_sorted_by_name(scene):
    make_command(scene, "test/commands/Zap", name="zap", title="Zap")
    make_command(scene, "test/commands/Ally", name="ally", title="Ally")
    make_command(scene, "test/commands/Mend", name="mend", title="Mend")

    catalog, _ = await build_catalog(scene)
    names = [
        entry["name"] for entry in catalog if entry["name"] in ("zap", "ally", "mend")
    ]

    assert names == ["ally", "mend", "zap"]


@pytest.mark.asyncio
async def test_register_commands_sends_catalog_signal(scene):
    make_command(scene, "test/commands/Wave", name="wave", title="Wave", menu="social")

    received = []

    async def on_catalog(event):
        received.append(event)

    async_signals.get("scene_commands_catalog").connect(on_catalog)
    try:
        catalog, _ = await build_catalog(scene)
    finally:
        async_signals.get("scene_commands_catalog").disconnect(on_catalog)

    assert len(received) == 1
    assert received[0].scene is scene
    assert received[0].catalog == catalog


# ---------------------------------------------------------------------------
# run_node_command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_node_command_executes_registered_command(scene):
    executed = []
    make_command(
        scene,
        "test/commands/Shout",
        name="shout",
        title="Shout",
        on_execute=executed.append,
    )

    loop = SceneLoop()
    with ActiveScene(scene):
        with GraphContext() as state:
            await loop.register_commands(scene, state)
            result = await run_node_command(state, "shout", {"arg_0": "loudly"})
            await wait_for(lambda: bool(executed))

    assert result is True
    assert executed == [{"arg_0": "loudly"}]


@pytest.mark.asyncio
async def test_run_node_command_passes_args_to_argument_nodes(scene):
    """The real `Command.execute_command` -> `FunctionWrapper` path: the
    kwarg value has to reach the consumer of the matching argument node."""

    captured = {}

    @register("test/commands/Aim", container=scene._NODE_DEFINITIONS)
    class AimCommand(Command):
        def __init__(self, **kwargs):
            kwargs.setdefault("title", "Aim")
            super().__init__(**kwargs)
            self.set_property("name", "aim")

            arg_node = FunctionArgument()
            arg_node.set_property("name", "target")
            sink = make_capture(captured, "target")
            self.add_node(arg_node)
            self.add_node(sink)
            self.connect(
                arg_node.get_output_socket("value"), sink.get_input_socket("target")
            )

    AimCommand._base_type = "command/Command"

    loop = SceneLoop()
    with ActiveScene(scene):
        with GraphContext() as state:
            await loop.register_commands(scene, state)
            result = await run_node_command(state, "aim", {"target": "x"})
            await wait_for(lambda: bool(captured))

    assert result is True
    assert captured == {"target": "x"}


@pytest.mark.asyncio
async def test_run_node_command_unknown_command_returns_false(scene):
    with ActiveScene(scene):
        with GraphContext() as state:
            state.data["_commands"] = {}
            assert await run_node_command(state, "nope", {}) is False


@pytest.mark.asyncio
async def test_run_node_command_without_registered_commands(scene):
    with ActiveScene(scene):
        with GraphContext() as state:
            assert await run_node_command(state, "nope", {}) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc, expect_error",
    [(GenerationCancelled("cancelled"), False), (ValueError("boom"), True)],
)
async def test_command_task_error_logging(monkeypatch, exc, expect_error):
    errors = []
    monkeypatch.setattr(
        scene_nodes.log, "error", lambda *args, **kwargs: errors.append(args)
    )

    async def fail():
        raise exc

    task = asyncio.ensure_future(fail())
    try:
        await task
    except Exception:
        pass

    scene_nodes._log_command_task_error(task)

    assert bool(errors) is expect_error


# ---------------------------------------------------------------------------
# WaitForInput.execute_node_command (regression guard on the refactor)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_node_command_parses_args(scene):
    executed = []
    make_command(
        scene,
        "test/commands/Trade",
        name="trade",
        title="Trade",
        on_execute=executed.append,
    )

    node = WaitForInput()
    loop = SceneLoop()
    with ActiveScene(scene):
        with GraphContext() as state:
            await loop.register_commands(scene, state)
            result = await node.execute_node_command(state, "!trade:apple;coin")
            await wait_for(lambda: bool(executed))

    assert result is True
    assert executed == [{"arg_0": "apple", "arg_1": "coin"}]


@pytest.mark.asyncio
async def test_execute_node_command_without_args(scene):
    executed = []
    make_command(
        scene,
        "test/commands/Rest",
        name="rest",
        title="Rest",
        on_execute=executed.append,
    )

    node = WaitForInput()
    loop = SceneLoop()
    with ActiveScene(scene):
        with GraphContext() as state:
            await loop.register_commands(scene, state)
            result = await node.execute_node_command(state, " !rest ")
            await wait_for(lambda: bool(executed))

    assert result is True
    assert executed == [{"arg_0": ""}]
