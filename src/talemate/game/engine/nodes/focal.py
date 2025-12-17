"""
This set of nodes represents integration with talemate's FOCAL system
for function orchestration with abstraction of creative tasks.
"""

from typing import TYPE_CHECKING
import structlog
from talemate.game.engine.nodes.core import (
    PropertyField,
    Node,
    GraphState,
    InputValueError,
    register,
    UNRESOLVED,
    TYPE_CHOICES as SOCKET_TYPES,
)
from talemate.context import active_scene
from talemate.prompts.base import PrependTemplateDirectories
from talemate.game.engine.nodes.run import FunctionWrapper, FunctionArgument
import talemate.game.focal as focal

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "Focal",
    "Callback",
    "ProcessCall",
]

log = structlog.get_logger("talemate.game.engine.nodes.focal")

# extend the socket types
SOCKET_TYPES.extend(
    [
        "focal/callback",
        "focal/call",
    ]
)


@register("focal/Argument")
class FocalArgument(FunctionArgument):
    """
    Represents an argument to an AI function.
    """

    class Fields(FunctionArgument.Fields):
        instructions = PropertyField(
            name="instructions",
            description="The instructions for the argument",
            type="text",
            default="",
        )

    def __init__(self, title="AI Function Argument", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.set_property("instructions", "")


@register("focal/Focal")
class Focal(Node):
    """
    Main node for calling AI functions using the FOCAL system.

    Inputs:
    - state: The current graph state
    - template: The prompt template name; This template will be used to generate the prompt that facilitates the AI function call(s)
    - callbacks: A list of focal.Callback instances that define the functions to call
    - agent: The agent to use for the AI function call
    - template_vars: A dictionary of variables to use in the template
    - max_calls: The maximum number of calls to make

    Properties:
    - template: The prompt template name
    - max_calls: The maximum number of calls to make
    - response_length: The maximum length of the response

    Outputs:
    - state: The current graph state
    - calls: The list of calls made
    - response: The raw response from the processed prompt
    """

    class Fields:
        template = PropertyField(
            name="template",
            description="The prompt template",
            type="str",
            default=UNRESOLVED,
        )

        max_calls = PropertyField(
            name="max_calls",
            description="The maximum number of calls to make",
            type="int",
            default=1,
            step=1,
            min=1,
            max=10,
        )

        retries = PropertyField(
            name="retries",
            description="The number of retries to make",
            type="int",
            default=0,
            step=1,
            min=0,
            max=10,
        )

        response_length = PropertyField(
            name="response_length",
            description="The maximum length of the response",
            type="int",
            default=1024,
            step=128,
            min=1,
            max=8192,
        )

    def __init__(self, title="AI Function Calling", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("template", socket_typoe="str", optional=True)
        self.add_input("prompt", socket_type="prompt", optional=True)
        self.add_input("callbacks", socket_type="list")
        self.add_input("agent", socket_type="agent")
        self.add_input("template_vars", socket_type="dict", optional=True)
        self.add_input("max_calls", socket_type="int", optional=True)

        self.set_property("template", UNRESOLVED)
        self.set_property("max_calls", 1)
        self.set_property("retries", 0)
        self.set_property("response_length", 1024)

        self.add_output("state")
        self.add_output("calls", socket_type="list")
        self.add_output("call_payloads", socket_type="list")
        self.add_output("response", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        in_state = self.get_input_value("state")

        template = self.normalized_input_value("template")
        prompt = self.normalized_input_value("prompt")

        callbacks = self.get_input_value("callbacks")
        agent = self.get_input_value("agent")
        template_vars = self.normalized_input_value("template_vars") or {}
        max_calls = self.require_number_input("max_calls", types=(int,))
        retries = self.require_number_input("retries", types=(int,))
        response_length = self.require_number_input("response_length", types=(int,))

        if not template and not prompt:
            raise InputValueError(
                self,
                "template",
                "Must provide either template or prompt",
            )

        if not hasattr(agent, "client"):
            raise InputValueError(
                self,
                "agent",
                "The specified agent does not have an appropriate LLM client configured.",
            )

        for callback in callbacks:
            if not isinstance(callback, focal.Callback):
                raise InputValueError(
                    self,
                    "callbacks",
                    f"Callback must be a focal.Callback instance. Got {type(callback)} instead.",
                )

        if template_vars:
            template_vars.pop("scene", None)

        focal_handler = focal.Focal(
            agent.client,
            callbacks=callbacks,
            max_calls=max_calls,
            scene=scene,
            retries=retries,
            response_length=response_length,
            vars={
                "scene_loop": state.shared.get("scene_loop", {}),
                "local": state.data,
                "response_length": response_length,
            },
            **template_vars,
        )

        async def process(*args, **kwargs):
            return await focal_handler.request(
                template_name=template,
                prompt=prompt,
            )

        process.__name__ = self.title.replace(" ", "_").lower()

        with PrependTemplateDirectories([scene.template_dir]):
            response = await agent.delegate(process)

        self.set_output_values(
            {
                "state": in_state,
                "calls": focal_handler.state.calls,
                "call_payloads": [call.payload for call in focal_handler.state.calls],
                "response": response,
            }
        )


@register("focal/Metadata")
class Metadata(Node):
    """
    Represents metadata within a callback in the focal system.

    Allowing to specify instructions and examples for the callback.
    """

    class Fields:
        instructions = PropertyField(
            name="instructions",
            description="The instructions for the callback",
            type="text",
            default="",
        )

        examples = PropertyField(
            name="examples",
            description="The examples for the callback",
            type="list",
            default=[],
        )

    def __init__(self, title="AI Function Callback Metadata", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.set_property("instructions", "")
        self.set_property("examples", [])
        self.add_output("state")

    async def run(self, state: GraphState):
        pass


@register("focal/Callback")
class Callback(Node):
    """
    Defines an AI function callback for use with the FOCAL system.

    Inputs:
    - fn: The function to call (Returned from an GetFunction node)

    Properties:
    - name: The name of the callback as the AI will see it

    Outputs:
    - callback: The focal.Callback instance
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the callback",
            type="str",
            default="my_function",
        )

        allow_multiple_calls = PropertyField(
            name="allow_multiple_calls",
            description="Whether the function can be called multiple times",
            type="bool",
            default=False,
        )

    def __init__(self, title="AI Function Callback", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        # self.add_input("arguments", socket_type="list")
        self.add_input("fn", socket_type="function")
        self.add_input("name", socket_type="str", optional=True)

        self.set_property("name", "my_function")
        self.set_property("allow_multiple_calls", False)

        self.add_output("callback", socket_type="focal/callback")

    async def run(self, state: GraphState):
        fn = self.get_input_value("fn")
        name: str = self.normalized_input_value("name")

        if not isinstance(fn, FunctionWrapper):
            raise InputValueError(
                self, "fn", f"Function must be FunctionWrapper. Got {type(fn)} instead."
            )

        fn_arg_nodes = await fn.get_argument_nodes()

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

        metadata = await fn.first_node(lambda node: isinstance(node, Metadata))

        callback = focal.Callback(
            name=name,
            arguments=arguments,
            fn=fn,
            multiple=self.get_property("allow_multiple_calls"),
            instructions=metadata.normalized_input_value("instructions")
            if metadata
            else "",
            examples=metadata.normalized_input_value("examples") if metadata else [],
            argument_instructions=argument_instructions,
        )

        log.debug("Callback created", callback=callback, fn=fn)

        self.set_output_values(
            {
                "callback": callback,
            }
        )


@register("focal/UnpackCall")
class UnpackCall(Node):
    """
    Unpacks a focal.Call instance
    """

    def __init__(self, title="Unpack AI Function Call", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("call", socket_type="focal/call")
        self.add_output("name", socket_type="str")
        self.add_output("arguments", socket_type="dict")
        self.add_output("result", socket_type="any")
        self.add_output("uid", socket_type="str")
        self.add_output("called", socket_type="bool")
        self.add_output("error", socket_type="str")

    async def run(self, state: GraphState):
        call = self.get_input_value("call")
        self.set_output_values(
            {
                "name": call.name,
                "arguments": call.arguments,
                "result": call.result,
                "uid": call.uid,
                "called": call.called,
                "error": call.error,
            }
        )


@register("focal/ProcessCall")
class ProcessCall(Node):
    """
    Process the AI function call result.

    Inputs:

    - calls: The list of calls made (focal.Call instances)

    Properties:

    - name: The name of the call to process

    Outputs:

    - name: The name of the call
    - arguments: The arguments of the call
    - result: The result of the call
    - uid: The UID of the call
    - called: Whether the call was made (if this is False, likely something went wrong)
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the call to process",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Process AI Function Call", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("calls", socket_type="list")

        self.set_property("name", UNRESOLVED)

        self.add_output("name", socket_type="str")
        self.add_output("arguments", socket_type="dict")
        self.add_output("result", socket_type="any")
        self.add_output("uid", socket_type="str")
        self.add_output("called", socket_type="bool")

    async def run(self, state: GraphState):
        name = self.require_input("name")
        calls = self.require_input("calls")

        for call in calls:
            if call.name == name:
                self.set_output_values(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "result": call.result,
                        "uid": call.uid,
                        "called": call.called,
                    }
                )
                break


@register("focal/CollectResults")
class CollectResults(Node):
    """
    Collects the results of a list of calls
    """

    class Fields:
        name = PropertyField(
            name="name",
            description="The name of the call to collect results from",
            type="str",
            default=UNRESOLVED,
        )

    def __init__(self, title="Collect AI Function Call Results", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("calls", socket_type="list")
        self.add_input("name", socket_type="str", optional=True)
        self.set_property("name", UNRESOLVED)

        self.add_output("calls", socket_type="list")
        self.add_output("results", socket_type="list")

    async def run(self, state: GraphState):
        calls = self.require_input("calls")
        name = self.normalized_input_value("name")

        results = []
        for call in calls:
            if not name or call.name == name:
                results.append(call.result)

        self.set_output_values(
            {
                "calls": calls,
                "results": results,
            }
        )
