import structlog
import pydantic
import asyncio
import re
import dataclasses
from typing import ClassVar, Callable
from talemate.game.engine.nodes.core import (
    Node,
    register,
    Graph,
    GraphState,
    ModuleError,
    PropertyField,
    StopGraphExecution,
    InputValueError,
    NodeVerbosity,
    NodeStyle,
    Socket,
    CounterPart,
    UNRESOLVED,
    PASSTHROUGH_ERRORS,
    TYPE_CHOICES,
)
from talemate.game.engine.nodes.core.exception import ExceptionWrapper
from talemate.game.engine.nodes.base_types import base_node_type
from talemate.context import active_scene
import talemate.emit.async_signals as async_signals

import talemate.game.focal as focal


log = structlog.get_logger("talemate.game.engine.nodes.core.run")

async_signals.register(
    "nodes_breakpoint",
)

TYPE_CHOICES.extend(
    [
        "exception",
    ]
)


def title_to_function_name(title: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", title)


@dataclasses.dataclass
class BreakpointEvent:
    node: Node
    state: GraphState
    module_path: str = None


class FunctionWrapper:
    def __init__(self, endpoint: Node, containing_graph: Graph, state: GraphState):
        self.state = state
        self.containing_graph = containing_graph
        self.endpoint = endpoint

    async def __call__(self, **kwargs):
        result = None

        async def handle_result(state: GraphState):
            nonlocal result
            result = state.data.get("__fn_result")
            if state.verbosity >= NodeVerbosity.VERBOSE:
                log.info("Function result", result=result, node=self.endpoint)

        if self.endpoint != self.containing_graph:
            # endpoint is not the containing graph, but a subgraph
            # we need to find the function arguments and set their values
            #
            # only arguments connected to the endpoint node are considered

            argument_nodes = await self.containing_graph.get_nodes_connected_to(
                self.endpoint, fn_filter=lambda node: isinstance(node, FunctionArgument)
            )

            await self.containing_graph.execute_to_node(
                self.endpoint,
                self.state,
                callbacks=[handle_result],
                state_values={
                    f"{arg.id}__fn_arg_value": kwargs.get(arg.get_property("name"))
                    for arg in argument_nodes
                },
                execute_forks=True,
                emit_state=True,
            )
        else:
            # endpoint is the containing graph
            # we need to find the function arguments and set their values
            #
            # all arguments are considered

            argument_nodes = await self.containing_graph.get_nodes(
                fn_filter=lambda node: isinstance(node, FunctionArgument)
            )

            await self.containing_graph.execute(
                self.state,
                callbacks=[handle_result],
                state_values={
                    f"{arg.id}__fn_arg_value": kwargs.get(arg.get_property("name"))
                    for arg in argument_nodes
                },
            )

        return result

    async def get_argument_nodes(
        self, filter_fn: Callable = None
    ) -> list["FunctionArgument"]:
        """
        Returns a list of argument nodes for the function

        Args:
            filter_fn (Callable, optional): The filter function to apply to the nodes. Defaults to None, in which case all argument nodes are returned.

        Returns:
            list[FunctionArgument]: The list of argument nodes
        """

        if filter_fn is None:

            def filter_fn(node):
                return isinstance(node, FunctionArgument)

        if self.endpoint != self.containing_graph:
            return await self.containing_graph.get_nodes_connected_to(
                self.endpoint, fn_filter=filter_fn
            )
        else:
            return await self.containing_graph.get_nodes(fn_filter=filter_fn)

    async def find_nodes(self, filter_fn: Callable) -> Node:
        result: set[Node] = set()

        if self.endpoint != self.containing_graph:
            result = set(
                await self.containing_graph.get_nodes_connected_to(
                    self.endpoint, fn_filter=filter_fn
                )
            )
        else:
            result = set(await self.containing_graph.get_nodes(fn_filter=filter_fn))

        # include endpoint if it matches the filter
        if filter_fn(self.endpoint):
            result.add(self.endpoint)

        return list(result)

    async def first_node(self, filter_fn: Callable) -> Node:
        nodes = await self.find_nodes(filter_fn)
        return nodes[0] if nodes else None

    def sync_wrapper(self) -> Callable:
        def _sync_wrapper(**kwargs):
            return asyncio.run(self(**kwargs))

        return _sync_wrapper

    async def ai_callback(
        self,
        name: str,
        allow_multiple_calls: bool = False,
    ) -> "focal.Callback":
        from talemate.game.engine.nodes.focal import Metadata

        fn_arg_nodes = await self.get_argument_nodes()

        arguments = [
            focal.Argument(
                name=node.get_property("name"),
                type=node.get_property("typ"),
            )
            for node in fn_arg_nodes
        ]

        argument_instructions = {
            node.get_property("name"): node.normalized_input_value("instructions")
            for node in fn_arg_nodes
        }

        metadata = await self.first_node(lambda node: isinstance(node, Metadata))

        return focal.Callback(
            name=name,
            arguments=arguments,
            fn=self,
            multiple=allow_multiple_calls,
            instructions=metadata.normalized_input_value("instructions")
            if metadata
            else "",
            examples=metadata.normalized_input_value("examples") if metadata else [],
            argument_instructions=argument_instructions,
        )


@register("core/functions/Argument")
class FunctionArgument(Node):
    """
    Represents an argument to a function.

    Properties:

    - type (str): The type of the argument
    - name (str): The name of the argument

    Outputs:

    - value: The value of the argument (during function execution)
    """

    class Fields:
        typ = PropertyField(
            type="str",
            name="typ",
            description="The type of the argument",
            default="str",
            choices=[
                "str",
                "int",
                "float",
                "bool",
                "list",
                "any",
            ],
        )

        name = PropertyField(
            type="str",
            name="name",
            description="The name of the argument",
            default=UNRESOLVED,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2d2c39",
            title_color="#312e57",
            icon="F0AE7",  # variable
            auto_title="{name}",
        )

    def __init__(self, title="Argument", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("name", UNRESOLVED)
        self.set_property("typ", "str")
        self.add_output("value")

    def _convert_value(
        self, value: str | int | float | bool
    ) -> str | int | float | bool:
        # if type is str any value that isnt part of str | int | float | bool
        # is passed through as is

        if self.get_property("typ") == "any":
            return value

        if self.get_property("typ") == "str" and not isinstance(
            value, (str, int, float, bool)
        ):
            return value

        if self.get_property("typ") == "str":
            return str(value)
        elif self.get_property("typ") == "list":
            # list values MAY come in as strings joined by newlines
            if isinstance(value, str):
                return value.split("\n")
            return value
        elif self.get_property("typ") == "int":
            return int(value)
        elif self.get_property("typ") == "float":
            return float(value)
        elif self.get_property("typ") == "bool":
            if isinstance(value, str):
                if value.lower() in ["true", "yes", "1"]:
                    return True
                elif value.lower() in ["false", "no", "0"]:
                    return False
                else:
                    return bool(value)
            return bool(value)
        return str(value)

    async def run(self, state: GraphState):
        value = state.data.get(f"{self.id}__fn_arg_value", UNRESOLVED)
        value = self._convert_value(value)
        self.set_output_values({"value": value})


@register("core/functions/Return")
class FunctionReturn(Node):
    """
    Represents the return value of a function.

    Inputs:

    - value: The value to return

    Outputs:

    - value: The value to return
    """

    def __init__(self, title="Return", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("value")
        self.add_output("value")

    async def run(self, state: GraphState):
        value = self.get_input_value("value")

        if value is UNRESOLVED:
            return

        self.set_output_values({"value": value})
        state.data["__fn_result"] = value

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.info(f"Function return: {self.id}", value=value)

        raise StopGraphExecution(f"Function return: {self.id}")


@register("core/functions/DefineFunction")
class DefineFunction(Node):
    """
    Does not define any outputs and is considered an isolated node.

    The correspinding GetFunction node will be used to retrieve the function object.

    Inputs:

    - nodes: The nodes to convert into a function
    - name: The name of the function
    """

    _isolated: ClassVar[bool] = True

    class Fields:
        name = PropertyField(
            type="str",
            name="name",
            description="The name of the function",
            default=UNRESOLVED,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#392f2c",
            title_color="#573a2e",
            icon="F0295",  # function
            auto_title="DEF {name}",
            counterpart=CounterPart(
                registry_name="core/functions/GetFunction",
                copy_values=["name"],
            ),
        )

    def __init__(self, title="Define Function", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("nodes")
        self.add_input("name", socket_type="str")
        self.set_property("name", UNRESOLVED)

    @property
    def never_run(self) -> bool:
        return True

    async def run(self, state: GraphState):
        return

    async def get_function(self, state: GraphState) -> FunctionWrapper:
        input_socket = self.get_input_socket("nodes")

        if not input_socket.source:
            raise ValueError("Nodes input not connected")

        input_node = input_socket.source.node

        return FunctionWrapper(input_node, state.graph, state)


@register("core/functions/GetFunction")
class GetFunction(Node):
    """
    Retrieves a function from the graph


    This has no inputs and will return the function wrapper for the
    function defined by the DefineFunction node.

    Properties:

    - name: The name of the function

    Outputs:

    - fn: The function wrapper
    """

    class Fields:
        name = PropertyField(
            type="str",
            name="name",
            description="The name of the function",
            default=UNRESOLVED,
            counterpart=CounterPart(
                registry_name="core/functions/DefineFunction",
                copy_values=["name"],
            ),
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#392f2c",
            title_color="#573a2e",
            icon="F0295",  # function
            auto_title="FN {name}",
        )

    def __init__(self, title="Get Function", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.set_property("name", UNRESOLVED)

        self.add_output("fn", socket_type="function")
        self.add_output("name", socket_type="str")

    async def get_function(self, graph: Graph, state: GraphState) -> FunctionWrapper:
        name = self.require_input("name")
        define_function_node = await graph.get_node(
            fn_filter=lambda node: isinstance(node, DefineFunction)
            and node.get_property("name") == name
        )
        return await define_function_node.get_function(state)

    async def run(self, state: GraphState):
        name = self.require_input("name")
        graph: Graph = state.graph
        define_function_node = await graph.get_node(
            fn_filter=lambda node: isinstance(node, DefineFunction)
            and node.get_property("name") == name
        )

        if not define_function_node:
            raise ValueError(f"Function {name} not found")

        fn_wrapper = await define_function_node.get_function(state)

        self.set_output_values({"fn": fn_wrapper, "name": name})

        return fn_wrapper


@register("core/functions/CallFunction")
class CallFunction(Node):
    """
    Takes a function wrapper input and a dict property to define arguments
    to pass to the function then calls the function

    Inputs:

    - fn: The function to call
    - args: The arguments to pass to the function

    Outputs:

    - result: The result of the function call
    """

    class Fields:
        args = PropertyField(
            type="dict",
            name="args",
            description="The arguments to pass to the function",
            default={},
        )

    def __init__(self, title="Call Function", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("fn", socket_type="function")
        self.add_input("args", optional=True)
        self.set_property("args", {})
        self.add_output("result")

    async def run(self, state: GraphState):
        fn = self.get_input_value("fn")
        args = self.get_input_value("args")

        if not isinstance(fn, FunctionWrapper):
            raise ValueError("fn must be a FunctionWrapper instance")

        result = await fn(**args)

        self.set_output_values({"result": result})


@register("core/functions/CallForEach")
class CallForEach(Node):
    """
    Calls the supplied function on each item in the input list

    The item is passed to the function as an argument

    Inputs:

    - state: The state of the graph
    - fn: The function to call
    - items: The list of items to iterate over

    Properties:

    - copy_items: Whether to copy the items list (default: False)
    - argument_name: The name of the argument to pass to the function (default: item)

    Outputs:

    - state: The state of the graph
    - results: The results of the function calls
    """

    class Fields:
        copy_items = PropertyField(
            type="bool",
            name="copy_items",
            description="Whether to copy the items list",
            default=False,
        )

        argument_name = PropertyField(
            type="str",
            name="argument_name",
            description="The name of the argument to pass to the function",
            default="item",
        )

    def __init__(self, title="Call For Each", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("fn", socket_type="function")
        self.add_input("items", socket_type="list,dict")

        self.set_property("copy_items", False)
        self.set_property("argument_name", "item")
        self.add_output("state")
        self.add_output("results", socket_type="list")

    async def run(self, state: GraphState):
        fn = self.get_input_value("fn")
        items = self.get_input_value("items")
        argument_name = self.get_property("argument_name")
        copy_items = self.get_property("copy_items")

        if not argument_name:
            raise InputValueError(self, "argument_name", "Argument name is required")

        if not isinstance(fn, FunctionWrapper):
            raise InputValueError(self, "fn", "fn must be a FunctionWrapper instance")

        if not isinstance(items, (list, dict)):
            raise InputValueError(self, "items", "items must be a list or dict")

        results = []

        if copy_items:
            items = items.copy()

        if isinstance(items, dict):
            items = list(items.values())

        for item in items:
            result = await fn(**{argument_name: item})
            results.append(result)

        self.set_output_values(
            {
                "state": self.get_input_value("state"),
                "results": results,
            }
        )


@base_node_type("core/functions/Function")
class Function(Graph):
    """
    A module graph that defines a function
    """

    class Fields:
        name = PropertyField(
            type="str",
            name="name",
            description="The name of the function",
            default="",
        )
        allow_multiple_calls = PropertyField(
            name="allow_multiple_calls",
            description="Function can be called multiple times during AI Function Calling",
            type="bool",
            default=False,
        )

    @pydantic.computed_field(description="Inputs")
    @property
    def inputs(self) -> list[Socket]:
        """
        Function graphs never have any direct inputs
        """
        return []

    @pydantic.computed_field(description="Outputs")
    @property
    def outputs(self) -> list[Socket]:
        """
        Function graphs have the following outputs:
        - fn: The function wrapper
        - name: The name of the function
        - allow_multiple_calls: Whether the function can be called multiple times
        - ai_callback: The AI callback for the function
        """

        if hasattr(self, "_outputs"):
            return self._outputs

        self._outputs = [
            Socket(
                name="fn",
                socket_type="function",
                node=self,
            ),
            Socket(
                name="name",
                socket_type="str",
                node=self,
            ),
            Socket(
                name="allow_multiple_calls",
                socket_type="bool",
                node=self,
            ),
            Socket(
                name="ai_callback",
                socket_type="focal/callback",
                node=self,
            ),
        ]

        return self._outputs

    @pydantic.computed_field(description="Module Fields")
    @property
    def module_properties(self) -> dict[str, PropertyField]:
        """
        Function module property definitions are static and defined in the Fields object
        """
        return self.field_definitions

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        # If a style is defined in the graph it overrides the default
        defined_style = super().style
        if defined_style:
            return defined_style

        return NodeStyle(
            node_color="#392f2c",
            title_color="#573a2e",
            icon="F0295",  # function
        )

    async def run(self, state: GraphState):
        """
        Executing the graph will return a FunctionWrapper object where
        the endpoint node is an OutputSocket node
        """
        wrapped = FunctionWrapper(self, self, state)

        name = self.normalized_input_value("name")

        sanitized_name = title_to_function_name(name or self.title)
        allow_multiple_calls = (
            self.normalized_input_value("allow_multiple_calls") or False
        )

        ai_callback = await wrapped.ai_callback(
            name=sanitized_name,
            allow_multiple_calls=allow_multiple_calls,
        )
        self.set_output_values(
            {
                "fn": wrapped,
                "name": self.get_property("name"),
                "allow_multiple_calls": allow_multiple_calls,
                "ai_callback": ai_callback,
            }
        )


@register("core/RunModule")
class RunModule(Node):
    """
    Provides a way to run a node module from memory

    Inputs:
    - module (optional)

    Outputs:
    - done: True if module was executed successfully
    - failed: Error message if module execution failed
    - cancelled: True if module execution was cancelled
    """

    def __init__(self, title="Run Module", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("module")
        self.add_output("done", socket_type="bool")
        self.add_output("failed", socket_type="str")
        self.add_output("cancelled", socket_type="bool")

    async def run(self, state: GraphState):
        module = self.get_input_value("module")

        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug("Running module")

        if not isinstance(module, Graph):
            raise ValueError("Module must be a Graph instance")

        if state.outer.data.get("_in_run_module") == module:
            raise ValueError(
                f"Infinite loop detected. Running module from within itself: {self.title}"
            )

        task_key = f"__run_{module.id}"
        try:
            state.data["_in_run_module"] = module

            quaratined_state = GraphState()
            quaratined_state.shared["creative_mode"] = state.shared.get(
                "creative_mode", False
            )
            quaratined_state.shared["nested_scene_loop"] = (
                module.base_type == "scene/SceneLoop"
            )
            quaratined_state.stack = state.stack

            if not hasattr(module, "test_run"):
                task = state.shared[task_key] = asyncio.create_task(
                    module.run(quaratined_state)
                )
            else:
                task = state.shared[task_key] = asyncio.create_task(
                    module.test_run(quaratined_state)
                )

            try:
                await task
                self.set_output_values({"done": True})
                log.info("Module execution complete", module=str(module))
            except asyncio.CancelledError:
                self.set_output_values({"cancelled": True})
                log.info("Module execution was cancelled", module=str(module))
                return
            except PASSTHROUGH_ERRORS:
                self.set_output_values({"done": True})
                log.debug("Caught scene control exception", module=str(module))
                raise
            except Exception as exc:
                self.set_output_values({"failed": str(exc)})
                log.error("Error running module", module=str(module), error=exc)
                raise ModuleError(f"Error running module: {exc}")
        finally:
            # Clean up regardless of success or failure
            state.data.pop("_in_run_module", None)
            if task_key in state.shared:
                task = state.shared.pop(task_key)
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass  # Ignore any errors during cleanup


@register("core/functions/Breakpoint")
class Breakpoint(Node):
    """
    A node that will pause execution of the graph and allow for inspection
    """

    class Fields:
        active = PropertyField(
            type="bool",
            name="active",
            description="Whether the breakpoint is active",
            default=True,
        )

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            title_color="#461515",
            icon="F03C3",  # octagon
        )

    def __init__(self, title="Breakpoint", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")

        self.set_property("active", True)

        self.add_output("state")

    async def run(self, state: GraphState):
        incoming_state = self.get_input_value("state")
        active = self.get_property("active")
        scene = active_scene.get()

        if scene.environment != "creative":
            active = False
            log.debug("Breakpoint disabled in non-creative environment", node=self.id)

        if not active:
            self.set_output_values({"state": incoming_state})
            return

        scene = active_scene.get()

        state.shared["__breakpoint"] = self.id
        if state.verbosity >= NodeVerbosity.NORMAL:
            log.info("Breakpoint", node=self.id)

        await async_signals.get("nodes_breakpoint").send(
            BreakpointEvent(
                node=self, state=incoming_state, module_path=state.graph._module_path
            )
        )

        while state.shared.get("__breakpoint"):
            if scene and not scene.active:
                log.warning("Breakpoint cancelled", node=self.id)
                self.set_output_values({"state": state})
                raise StopGraphExecution("Breakpoint cancelled")
            await asyncio.sleep(0.5)

        if state.verbosity >= NodeVerbosity.NORMAL:
            log.info("Breakpoint released", node=self.id)

        self.set_output_values({"state": incoming_state})


@register("core/ErrorHandler")
class ErrorHandler(Node):
    """
    A node that will catch unhandled errors in the graph and allow for
    custom error handling

    Inputs:

    - fn: The function to call when an error occurs
    """

    _isolated: ClassVar[bool] = True

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#2c0a0a",
            title_color="#461515",
            icon="F05D6",  # alert-circle-outline
        )

    @property
    def never_run(self) -> bool:
        return True

    def __init__(self, title="Error Handler", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("fn", socket_type="function")

    async def catch(self, state: GraphState, exc: Exception):
        log.info("Error caught", error=exc)
        fn_socket = self.get_input_socket("fn")

        fn_node = fn_socket.source.node

        fn = await fn_node.run(state)

        if not isinstance(fn, FunctionWrapper):
            log.error(f"fn must be a FunctionWrapper instance, got {fn} instead")
            return False

        exc_wrapper = ExceptionWrapper(
            name=exc.__class__.__name__,
            message=str(exc),
        )

        caught = await fn(exc=exc_wrapper)

        log.debug("Error handler result", result=caught)

        return caught


@register("core/functions/UnpackException")
class UnpackException(Node):
    """
    Unpacks an ExceptionWrapper instance into an description and message
    """

    def __init__(self, title="Unpack Exception", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("exc", socket_type="exception")
        self.add_output("name")
        self.add_output("message")

    async def run(self, state: GraphState):
        exc = self.get_input_value("exc")

        if not isinstance(exc, ExceptionWrapper):
            log.error(
                "Expected ExceptionWrapper instance, got %s instead", type(exc).__name__
            )
            return

        self.set_output_values(
            {
                "name": exc.name,
                "message": exc.message,
            }
        )
