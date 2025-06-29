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
from talemate.game.engine.nodes.run import FunctionWrapper
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

    def __init__(self, title="AI Function Calling", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("template", socket_typoe="str")
        self.add_input("callbacks", socket_type="list")
        self.add_input("agent", socket_type="agent")
        self.add_input("template_vars", socket_type="dict", optional=True)
        self.add_input("max_calls", socket_type="int", optional=True)

        self.set_property("template", UNRESOLVED)
        self.set_property("max_calls", 1)
        self.set_property("retries", 0)

        self.add_output("state")
        self.add_output("calls", socket_type="list")
        self.add_output("response", socket_type="str")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()

        in_state = self.get_input_value("state")
        template = self.get_input_value("template")
        callbacks = self.get_input_value("callbacks")
        agent = self.get_input_value("agent")
        template_vars = self.get_input_value("template_vars")
        max_calls = self.require_number_input("max_calls", types=(int,))
        retries = self.require_number_input("retries", types=(int,))

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
            vars={
                "scene_loop": state.shared.get("scene_loop", {}),
                "local": state.data,
            },
            **template_vars,
        )

        async def process(*args, **kwargs):
            return await focal_handler.request(template)

        process.__name__ = self.title.replace(" ", "_").lower()

        with PrependTemplateDirectories([scene.template_dir]):
            response = await agent.delegate(process)

        self.set_output_values(
            {
                "state": in_state,
                "calls": focal_handler.state.calls,
                "response": response,
            }
        )


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

        self.set_property("name", "my_function")
        self.set_property("allow_multiple_calls", False)

        self.add_output("callback", socket_type="focal/callback")

    async def run(self, state: GraphState):
        fn = self.get_input_value("fn")

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

        callback = focal.Callback(
            name=self.get_property("name"),
            arguments=arguments,
            fn=fn,
            multiple=self.get_property("allow_multiple_calls"),
        )

        log.debug("Callback created", callback=callback, fn=fn)

        self.set_output_values(
            {
                "callback": callback,
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
