from typing import TYPE_CHECKING, Any
import structlog
import pydantic
from talemate.context import active_scene

from talemate.game.engine.nodes.core import (
    Node,
    register,
    GraphState,
    NodeVerbosity,
    UNRESOLVED,
    NodeStyle,
    CounterPart,
    PropertyField,
    InputValueError,
)
from talemate.game.state import (
    pin_game_state_path,
    set_game_state_value,
    unset_game_state_value,
    update_game_state,
)
from talemate.util.path import split_state_path, get_path_parent

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    from talemate.game.state import GameState
log = structlog.get_logger("talemate.game.engine.nodes.state")


def coerce_to_type(value: Any, type_name: str):
    if type_name == "str":
        return str(value)
    elif type_name == "number":
        return float(value)
    elif type_name == "bool":
        if value in ["true", "True", "1", 1]:
            return True
        return False
    else:
        raise ValueError(f"Cannot coerce value to type {type_name}")


class StateManipulation(Node):
    """
    Base class for state manipulation nodes
    """

    class Fields:
        scope = PropertyField(
            name="scope",
            description="Which scope to manipulate",
            type="str",
            default="local",
            choices=["local", "parent", "shared", "scene loop", "game"],
        )

        name = PropertyField(
            name="name",
            description="The name of the variable to manipulate",
            type="str",
            default=UNRESOLVED,
        )

    def setup(self):
        self.add_input("name", socket_type="str", optional=True)

        self.set_property("name", UNRESOLVED)
        self.set_property("scope", "local")

        self.add_output("name", socket_type="str")
        self.add_output("value")
        self.add_output("scope", socket_type="str")

    def get_state_container(self, state: GraphState):
        scope = self.get_property("scope")

        if scope == "local":
            return state.data
        elif scope == "parent":
            return state.outer.data if state.outer else {}
        elif scope == "shared":
            return state.shared
        elif scope == "scene loop":
            container = state.shared.get("scene_loop")
            if container is None:
                log.warning("Not inside a scene loop, returning empty scope")
                container = {}
            return container
        elif scope == "game":
            scene: "Scene" = active_scene.get()
            return scene.game_state
        else:
            raise InputValueError(self, "scope", f"Unknown scope: {scope}")

    def game_scene(self) -> "Scene | None":
        # the game scope writes through talemate.game.state, which sends
        # game_state.changed for each changed value
        return active_scene.get() if self.get_property("scope") == "game" else None


@register("state/SetState")
class SetState(StateManipulation):
    """
    Set a variable in the graph state

    Inputs:

    - name: the name to set
    - value: the value to set

    Properties:

    - scope: which scope to set the variable in

    Outputs:

    - value: the value that was set
    - name: the name that was set
    - scope: the scope that was set
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#2e4657",
            icon="F01DA",  # upload
            auto_title="SET {scope}.{name}",
            counterpart=CounterPart(
                registry_name="state/GetState",
                copy_values=["name", "scope"],
            ),
        )

    def __init__(self, title="Set State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("value")

    async def run(self, state: GraphState):
        name = self.require_input("name")
        value = self.require_input("value", none_is_set=True)
        scope = self.require_input("scope")

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Setting state variable", name=name, value=value, scope=scope)

        container = self.get_state_container(state)

        container[name] = value

        self.set_output_values({"name": name, "value": value, "scope": scope})


@register("state/GetState")
class GetState(StateManipulation):
    """
    Get a variable from the graph state

    Inputs:

    - name: the name to get
    - default: value to return if the variable is not set (optional)

    Properties:

    - scope: which scope to get the variable from

    Outputs:

    - value: the value that was retrieved
    - name: the name that was retrieved
    - scope: the scope that was retrieved
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#44552f",
            icon="F0552",  # download
            auto_title="GET {scope}.{name}",
            counterpart=CounterPart(
                registry_name="state/SetState",
                copy_values=["name", "scope"],
            ),
        )

    def __init__(self, title="Get State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("default", optional=True)

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")

        default = self.get_input_value("default")

        if default is UNRESOLVED:
            default = None

        container = self.get_state_container(state)

        value = container.get(name, default)

        self.set_output_values({"name": name, "value": value, "scope": scope})


@register("state/UnsetState")
class UnsetState(StateManipulation):
    """
    Unset a variable in the graph state

    Inputs:

    - name: the name to unset

    Properties:

    - scope: which scope to unset the variable in

    Outputs:

    - name: the name that was unset
    - scope: the scope that was unset
    - value: the value that was unset
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#7f2e2e",
            icon="F0683",  # delete-circle
            auto_title="UNSET {scope}.{name}",
        )

    def __init__(self, title="Unset State", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")

        container = self.get_state_container(state)

        value = container.pop(name, None)

        self.set_output_values({"name": name, "value": value, "scope": scope})


@register("state/HasState")
class HasState(StateManipulation):
    """
    Check if a variable exists in the graph state

    Inputs:

    - name: the name to check

    Properties:

    - scope: which scope to check the variable in

    Outputs:

    - name: the name that was checked
    - scope: the scope that was checked
    - exists: whether the variable exists (True) or not (False)
    """

    def __init__(self, title="Has State", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")

        container = self.get_state_container(state)

        exists = name in container

        self.set_output_values({"name": name, "scope": scope, "exists": exists})


@register("state/CounterState")
class CounterState(StateManipulation):
    """
    Counter node that increments a numeric value in the state and returns the new value.

    Inputs:
    - state: required state input (conditional execution)
    - name: The key to the value to increment
    - reset: If true, the value will be reset to 0
    - reset_cap: If set, the counter resets to 0 once it reaches this value

    Properties:
    - increment: The amount to increment the value by
    - scope: Which scope to use for the counter

    Outputs:
    - state: the state that was passed in
    - value: The new value
    - name: The key that was used
    - scope: The scope that was used
    - reset_cap: The reset cap that was used
    - reset: Whether the counter was reset
    - new_cycle: True if the counter was at 0 before this run
    """

    class Fields(StateManipulation.Fields):
        increment = PropertyField(
            name="increment",
            type="number",
            default=1,
            step=1,
            min=1,
            description="The amount to increment the value by",
        )

        reset = PropertyField(
            name="reset",
            type="bool",
            default=False,
            description="If true, the value will be reset to 0",
        )

        reset_cap = PropertyField(
            name="reset_cap",
            type="number",
            default=0,
            description="If set (> 0), the counter resets to 0 once the value reaches this cap",
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#2e4657",
            icon="F0199",  # counter
            auto_title="COUNT {scope}.{name}",
        )

    def __init__(self, title="State Counter", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        super().setup()
        self.add_input("reset", socket_type="bool", optional=True)
        self.add_input("reset_cap", socket_type="number", optional=True)

        self.set_property("increment", 1)
        self.set_property("reset", False)
        self.set_property("reset_cap", 0)

        self.add_output("reset_cap", socket_type="number")
        self.add_output("reset", socket_type="bool")
        self.add_output("new_cycle", socket_type="bool")

    def count(self, current_value, increment, reset, reset_cap, name, scope):
        """The counter's next value, and the reset and cap it used."""
        value = 0 if reset else current_value + increment
        try:
            reset_cap = int(reset_cap)
            if reset_cap > 0 and value >= reset_cap:
                log.debug(
                    "Resetting counter state from reset cap",
                    node_id=self.id,
                    name=name,
                    scope=scope,
                    reset_cap=reset_cap,
                )
                reset = True
                value = 0
        except Exception:
            log.error(
                "Error resetting counter state from reset cap",
                node_id=self.id,
                name=name,
                scope=scope,
                reset_cap=reset_cap,
            )
        return value, reset, reset_cap

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")
        reset = self.normalized_input_value("reset", bool) or False
        reset_cap = self.normalized_input_value("reset_cap") or 0
        increment = self.get_input_value("increment")

        container = self.get_state_container(state)

        current_value = container.get(name, 0)
        new_cycle: bool = current_value == 0
        value, reset, reset_cap = self.count(
            current_value, increment, reset, reset_cap, name, scope
        )
        # one write: a counter that reaches its cap changes once, to 0
        container[name] = value

        self.set_output_values(
            {
                "state": state,
                "value": value,
                "name": name,
                "scope": scope,
                "reset_cap": reset_cap,
                "reset": reset,
                "new_cycle": new_cycle,
            }
        )


@register("state/ConditionalSetState")
class ConditionalSetState(SetState):
    """
    Set a variable in the graph state

    Provides a required `state` input causing the node to only run when a state is provided
    """

    def __init__(self, title="Set State (Conditional)", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        super().setup()

    async def run(self, state: GraphState):
        await super().run(state)
        self.set_output_values({"state": self.get_input_value("state")})


@register("state/ConditionalUnsetState")
class ConditionalUnsetState(UnsetState):
    """
    Unset a variable in the graph state

    Provides a required `state` input causing the node to only run when a state is provided
    """

    def __init__(self, title="Unset State (Conditional)", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        super().setup()

    async def run(self, state: GraphState):
        await super().run(state)
        self.set_output_values({"state": self.get_input_value("state")})


@register("state/ConditionalCounterState")
class ConditionalCounterState(CounterState):
    """
    Counter node that increments a numeric value in the state and returns the new value.

    Provides a required `state` input causing the node to only run when a state is provided
    """

    def __init__(self, title="Counter State (Conditional)", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run(self, state: GraphState):
        await super().run(state)
        self.set_output_values({"state": self.get_input_value("state")})


@register("state/SetStatePath")
class SetStatePath(SetState):
    """
    Set a variable in the graph state using a path (e.g., 'a/b/c').

    Creates intermediate dictionaries as needed (mkdir -p semantics).
    Mutating operation - conditional by default with required state input.

    Inputs:
    - state: required state input (conditional execution)
    - name: the path name to set (e.g., 'a/b/c')
    - value: the value to set

    Properties:
    - scope: which scope to set the variable in

    Outputs:
    - state: the state that was passed in
    - value: the value that was set
    - name: the name that was set
    - scope: the scope that was set
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#2e4657",
            icon="F01DA",  # upload
            auto_title="SET {scope}.{name}",
            counterpart=CounterPart(
                registry_name="state/GetStatePath",
                copy_values=["name", "scope"],
            ),
        )

    def __init__(self, title="Set State (Path)", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        super().setup()

    async def run(self, state: GraphState):
        name = self.require_input("name")
        value = self.require_input("value", none_is_set=True)
        scope = self.require_input("scope")

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug(
                "Setting state variable (path)", name=name, value=value, scope=scope
            )

        container = self.get_state_container(state)
        game_scene = self.game_scene()

        # Split path and traverse/create intermediate containers
        try:
            if game_scene is not None:
                set_game_state_value(game_scene, name, value)
            else:
                parts = split_state_path(name)
                parent_container, leaf_key = get_path_parent(
                    container, parts, create=True, node_for_errors=self
                )
                parent_container[leaf_key] = value
        except ValueError as e:
            raise InputValueError(self, "name", str(e))

        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "name": name,
                "value": value,
                "scope": scope,
            }
        )


@register("state/GetStatePath")
class GetStatePath(GetState):
    """
    Get a variable from the graph state using a path (e.g., 'a/b/c').

    Does not create missing containers - returns default if path doesn't exist.

    Inputs:
    - name: the path name to get (e.g., 'a/b/c')
    - default: default value if path doesn't exist

    Properties:
    - scope: which scope to get the variable from

    Outputs:
    - value: the value that was retrieved
    - name: the name that was retrieved
    - scope: the scope that was retrieved
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#44552f",
            icon="F0552",  # download
            auto_title="GET {scope}.{name}",
            counterpart=CounterPart(
                registry_name="state/SetStatePath",
                copy_values=["name", "scope"],
            ),
        )

    def __init__(self, title="Get State (Path)", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")

        default = self.get_input_value("default")
        if default is UNRESOLVED:
            default = None

        container = self.get_state_container(state)

        # Split path and traverse (without creating)
        try:
            parts = split_state_path(name)
            parent_container, leaf_key = get_path_parent(
                container, parts, create=False, node_for_errors=self
            )

            if parent_container is None:
                # Path doesn't exist
                value = default
            else:
                # Get value from parent container
                value = (
                    parent_container.get(leaf_key, default)
                    if hasattr(parent_container, "get")
                    else (
                        parent_container[leaf_key]
                        if leaf_key in parent_container
                        else default
                    )
                )
        except ValueError as e:
            raise InputValueError(self, "name", str(e))

        self.set_output_values({"name": name, "value": value, "scope": scope})


@register("state/UnsetStatePath")
class UnsetStatePath(UnsetState):
    """
    Unset a variable in the graph state using a path (e.g., 'a/b/c').

    Does not create missing containers - returns None if path doesn't exist.
    Mutating operation - conditional by default with required state input.

    Inputs:
    - state: required state input (conditional execution)
    - name: the path name to unset (e.g., 'a/b/c')

    Properties:
    - scope: which scope to unset the variable in

    Outputs:
    - state: the state that was passed in
    - name: the name that was unset
    - scope: the scope that was unset
    - value: the value that was unset
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#7f2e2e",
            icon="F0683",  # delete-circle
            auto_title="UNSET {scope}.{name}",
        )

    def __init__(self, title="Unset State (Path)", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_output("state")
        super().setup()

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")

        container = self.get_state_container(state)
        game_scene = self.game_scene()

        # Split path and traverse (without creating)
        try:
            parts = split_state_path(name)
            parent_container, leaf_key = get_path_parent(
                container, parts, create=False, node_for_errors=self
            )

            if parent_container is None:
                # Path doesn't exist, nothing to unset
                value = None
            elif game_scene is not None:
                value = unset_game_state_value(game_scene, name)
            else:
                # Pop value from parent container
                if hasattr(parent_container, "pop"):
                    value = parent_container.pop(leaf_key, None)
                elif leaf_key in parent_container:
                    value = parent_container[leaf_key]
                    del parent_container[leaf_key]
                else:
                    value = None
        except ValueError as e:
            raise InputValueError(self, "name", str(e))

        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "name": name,
                "value": value,
                "scope": scope,
            }
        )


@register("state/HasStatePath")
class HasStatePath(HasState):
    """
    Check if a variable exists in the graph state using a path (e.g., 'a/b/c').

    Does not create missing containers - returns False if path doesn't exist.

    Inputs:
    - name: the path name to check (e.g., 'a/b/c')

    Properties:
    - scope: which scope to check the variable in

    Outputs:
    - name: the name that was checked
    - scope: the scope that was checked
    - exists: whether the variable exists (True) or not (False)
    """

    def __init__(self, title="Has State (Path)", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")

        container = self.get_state_container(state)

        # Split path and traverse (without creating)
        try:
            parts = split_state_path(name)
            parent_container, leaf_key = get_path_parent(
                container, parts, create=False, node_for_errors=self
            )

            if parent_container is None:
                # Path doesn't exist
                exists = False
            else:
                # Check if leaf key exists in parent container
                exists = leaf_key in parent_container
        except ValueError as e:
            raise InputValueError(self, "name", str(e))

        self.set_output_values({"name": name, "scope": scope, "exists": exists})


@register("state/CounterStatePath")
class CounterStatePath(CounterState):
    """
    Counter node that increments a numeric value in the state using a path (e.g., 'a/b/c').

    Creates intermediate dictionaries as needed (mkdir -p semantics).
    Mutating operation - conditional by default with required state input.

    Inputs:
    - state: required state input (conditional execution)
    - name: The path key to the value to increment (e.g., 'a/b/c')
    - reset: If true, the value will be reset to 0
    - reset_cap: If set, the value will be reset to 0 when it reaches this value

    Properties:
    - increment: The amount to increment the value by
    - scope: Which scope to use for the counter

    Outputs:
    - state: the state that was passed in
    - value: The new value
    - name: The key that was used
    - scope: The scope that was used
    - reset_cap: The reset cap value
    - reset: Whether reset occurred
    - new_cycle: Whether this is a new cycle (value was 0)
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#2e4657",
            icon="F0199",  # counter
            auto_title="COUNT {scope}.{name}",
        )

    def __init__(self, title="State Counter (Path)", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")
        reset = self.normalized_input_value("reset", bool) or False
        reset_cap = self.normalized_input_value("reset_cap") or 0
        increment = self.get_input_value("increment")

        container = self.get_state_container(state)
        game_scene = self.game_scene()

        # Split path and traverse/create intermediate containers; the game
        # scope only reads here and creates them in its one write
        try:
            parts = split_state_path(name)
            parent_container, leaf_key = get_path_parent(
                container, parts, create=game_scene is None, node_for_errors=self
            )

            # Get current value (defaulting to 0)
            if parent_container is None:
                current_value = 0
            elif hasattr(parent_container, "get"):
                current_value = parent_container.get(leaf_key, 0)
            else:
                current_value = (
                    parent_container[leaf_key] if leaf_key in parent_container else 0
                )

            new_cycle: bool = current_value == 0
            value, reset, reset_cap = self.count(
                current_value, increment, reset, reset_cap, name, scope
            )
            if game_scene is not None:
                set_game_state_value(game_scene, name, value)
            else:
                parent_container[leaf_key] = value

            self.set_output_values(
                {
                    "state": self.get_input_value("state"),
                    "value": value,
                    "name": name,
                    "scope": scope,
                    "reset_cap": reset_cap,
                    "reset": reset,
                    "new_cycle": new_cycle,
                }
            )
        except ValueError as e:
            raise InputValueError(self, "name", str(e))


@register("state/Gamestate")
class UnpackGameState(Node):
    """
    Get the game state variables of the active scene. Change them with
    Update Game State or a state node in the game scope: a change made in
    place sends no game_state.changed event.

    Outputs:

    - variables: Dict of the scene's game state variables
    """

    def __init__(self, title="Game State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_output("variables", socket_type="dict")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        game_state: "GameState" = scene.game_state
        variables = game_state.variables
        self.set_output_values({"variables": variables})


@register("state/UpdateGameState")
class UpdateGameState(Node):
    """
    Apply update dicts to the game state variables, in order; each changed
    value sends game_state.changed.

    Inputs:

    - state: graph state
    - updates: one dict, or a list of dicts applied one after another

    Properties:

    - merge: merge nested dicts (an empty dict clears its key); off, each
      top-level key is replaced

    Outputs:

    - state: graph state
    - variables: the game state variables after the update
    """

    class Fields:
        merge = PropertyField(
            name="merge",
            description="Merge nested dicts; off replaces each top-level key",
            type="bool",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(title_color="#2e4657", icon="F01DA")  # upload

    def __init__(self, title="Update Game State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("updates", socket_type="dict,list")
        self.set_property("merge", True)
        self.add_output("state")
        self.add_output("variables", socket_type="dict")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        updates = self.require_input("updates")
        try:
            variables = update_game_state(
                scene, updates, merge=bool(self.get_property("merge"))
            )
        except (TypeError, ValueError) as exc:
            raise InputValueError(self, "updates", str(exc)) from exc
        self.set_output_values(
            {"state": self.get_input_value("state"), "variables": variables}
        )


def _game_state_path(node: Node, path) -> str:
    try:
        return "/".join(split_state_path(path))
    except ValueError as e:
        raise InputValueError(node, "path", str(e))


@register("state/GetGameStatePathSettings")
class GetGameStatePathSettings(Node):
    """
    How a game state path is pinned: a control in the scene header (knob),
    listed in Debug Tools (debug), and the control's settings.

    Inputs:

    - path: the game state path (e.g. 'player/health')

    Outputs:

    - path: the normalized path
    - pinned: True when the path is shown in the header or in Debug Tools
    - knob: True when the path is a control in the scene header
    - debug: True when the path is listed in Debug Tools
    - read_only: True when the path or a pinned container above it is read only
    - settings: label, description, minimum, maximum, step, slider, choices, read_only and order, as set
    """

    def __init__(self, title="Get Game State Path Settings", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("path", socket_type="str")
        self.set_property("path", "")
        self.add_output("path", socket_type="str")
        self.add_output("pinned", socket_type="bool")
        self.add_output("knob", socket_type="bool")
        self.add_output("debug", socket_type="bool")
        self.add_output("read_only", socket_type="bool")
        self.add_output("settings", socket_type="dict")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        path = _game_state_path(self, self.require_input("path"))
        settings = scene.game_state_path_settings.get(path)
        self.set_output_values(
            {
                "path": path,
                "pinned": path in scene.pinned_game_state_paths,
                "knob": path in scene.game_state_knob_paths,
                "debug": path in scene.game_state_watch_paths,
                "read_only": scene.game_state_path_is_read_only(path),
                "settings": settings.model_dump(exclude_defaults=True)
                if settings
                else {},
            }
        )


@register("state/PinGameStatePath")
class PinGameStatePath(Node):
    """
    Pin or unpin a game state path: `knob` shows it as a control in the scene
    header, `debug` lists it in Debug Tools. `settings` changes only the
    fields given. Unpinning from both targets removes the settings.

    Inputs:

    - state: graph state (passthrough)
    - path: the game state path (e.g. 'player/health')
    - enabled: pin (true) or unpin (false)
    - settings: control settings to apply (optional)

    Properties:

    - target: knob or debug

    Outputs:

    - state: graph state
    - path: the normalized path
    - settings: the path's settings after the change
    """

    class Fields:
        target = PropertyField(
            name="target",
            description="Where the path is pinned",
            type="str",
            default="knob",
            choices=["knob", "debug"],
        )
        enabled = PropertyField(
            name="enabled",
            description="Pin (true) or unpin (false)",
            type="bool",
            default=True,
        )

    def __init__(self, title="Pin Game State Path", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("path", socket_type="str")
        self.add_input("enabled", socket_type="bool", optional=True)
        self.add_input("settings", socket_type="dict", optional=True)
        self.set_property("path", "")
        self.set_property("target", "knob")
        self.set_property("enabled", True)
        self.add_output("state")
        self.add_output("path", socket_type="str")
        self.add_output("settings", socket_type="dict")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        path = _game_state_path(self, self.require_input("path"))
        enabled = self.normalized_input_value("enabled")
        try:
            pin_game_state_path(
                scene,
                path,
                self.get_property("target"),
                True if enabled is None else bool(enabled),
                self.normalized_input_value("settings") or None,
            )
        except pydantic.ValidationError as e:
            raise InputValueError(self, "settings", str(e))
        except ValueError as e:
            raise InputValueError(self, "target", str(e))
        scene.emit_status()

        current = scene.game_state_path_settings.get(path)
        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "path": path,
                "settings": current.model_dump(exclude_defaults=True)
                if current
                else {},
            }
        )
