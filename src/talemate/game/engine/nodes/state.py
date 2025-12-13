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


@register("state/SetState")
class SetState(StateManipulation):
    """
    Set a variable in the graph state

    Inputs:

    - name: the name to set
    - value: the value to set
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
    - name: The key to the value to increment
    - scope: Which scope to use for the counter
    - reset: If true, the value will be reset to 0

    Properties:
    - increment: The amount to increment the value by
    - name: The key to the value to increment
    - scope: Which scope to use for the counter
    - reset: If true, the value will be reset to 0

    Outputs:
    - value: The new value
    - name: The key that was used
    - scope: The scope that was used
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
            description="If set, the value will be reset to this value when it exceeds it",
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

        self.add_output("value")
        self.add_output("reset_cap", socket_type="number")
        self.add_output("reset", socket_type="bool")
        self.add_output("new_cycle", socket_type="bool")

    async def run(self, state: GraphState):
        name = self.require_input("name")
        scope = self.require_input("scope")
        reset = self.normalized_input_value("reset", bool) or False
        reset_cap = self.normalized_input_value("reset_cap") or 0
        increment = self.get_input_value("increment")

        container = self.get_state_container(state)

        new_cycle: bool = container.get(name, 0) == 0

        if reset:
            container[name] = 0
        else:
            container[name] = container.get(name, 0) + increment

        try:
            reset_cap = int(reset_cap)
            if reset_cap > 0 and container[name] >= reset_cap:
                log.debug(
                    "Resetting counter state from reset cap",
                    node_id=self.id,
                    name=name,
                    scope=scope,
                    reset_cap=reset_cap,
                )
                reset = True
                container[name] = 0
        except Exception:
            log.error(
                "Error resetting counter state from reset cap",
                node_id=self.id,
                name=name,
                scope=scope,
                reset_cap=reset_cap,
            )
            pass

        self.set_output_values(
            {
                "state": state,
                "value": container[name],
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

        # Split path and traverse/create intermediate containers
        try:
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
    - scope: which scope to get the variable from
    - default: default value if path doesn't exist

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

        # Split path and traverse (without creating)
        try:
            parts = split_state_path(name)
            parent_container, leaf_key = get_path_parent(
                container, parts, create=False, node_for_errors=self
            )

            if parent_container is None:
                # Path doesn't exist, nothing to unset
                value = None
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
    - scope: Which scope to use for the counter
    - reset: If true, the value will be reset to 0
    - reset_cap: If set, the value will be reset to 0 when it exceeds this value

    Properties:
    - increment: The amount to increment the value by

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

        # Split path and traverse/create intermediate containers
        try:
            parts = split_state_path(name)
            parent_container, leaf_key = get_path_parent(
                container, parts, create=True, node_for_errors=self
            )

            # Get current value (defaulting to 0)
            current_value = (
                parent_container.get(leaf_key, 0)
                if hasattr(parent_container, "get")
                else (parent_container[leaf_key] if leaf_key in parent_container else 0)
            )

            new_cycle: bool = current_value == 0

            if reset:
                parent_container[leaf_key] = 0
            else:
                parent_container[leaf_key] = current_value + increment

            try:
                reset_cap = int(reset_cap)
                if reset_cap > 0 and parent_container[leaf_key] >= reset_cap:
                    log.debug(
                        "Resetting counter state from reset cap",
                        node_id=self.id,
                        name=name,
                        scope=scope,
                        reset_cap=reset_cap,
                    )
                    reset = True
                    parent_container[leaf_key] = 0
            except Exception:
                log.error(
                    "Error resetting counter state from reset cap",
                    node_id=self.id,
                    name=name,
                    scope=scope,
                    reset_cap=reset_cap,
                )
                pass

            self.set_output_values(
                {
                    "state": self.get_input_value("state"),
                    "value": parent_container[leaf_key],
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
    Get and unpack the game state
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
