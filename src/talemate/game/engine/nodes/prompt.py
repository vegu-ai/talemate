import pydantic
import structlog
import jinja2
from typing import TYPE_CHECKING
from talemate.game.engine.nodes.core import (
    Node,
    register,
    GraphState,
    InputValueError,
    PropertyField,
    NodeVerbosity,
    NodeStyle,
    TYPE_CHOICES,
)
from talemate.agents.base import DynamicInstruction
from talemate.agents.registry import get_agent_types
from talemate.agents.base import Agent
from talemate.prompts.base import Prompt, PrependTemplateDirectories
from talemate.client.presets import make_kind
from talemate.context import active_scene
from talemate.util import strip_partial_sentences

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.nodes.prompt")

TYPE_CHOICES.extend(
    [
        "prompt",
    ]
)


@register("prompt/PromptFromTemplate")
class PromptFromTemplate(Node):
    """
    Loads a talemate template prompt

    Inputs:

    - template_file: The template file to load
    - variables: The variables to use in the template (optional)

    Properties:

    - scope: the template scope (choices of agents or scene)

    Outputs:

    - prompt: The Prompt instance
    """

    class Fields:
        scope = PropertyField(
            name="scope",
            type="str",
            generate_choices=lambda: ["scene"] + list(get_agent_types()),
            description="The template scope",
            default="scene",
        )

        template_file = PropertyField(
            name="template_file",
            type="str",
            description="The template to load",
            default="",
        )

        template_text = PropertyField(
            name="template_text",
            type="text",
            description="The template text to use",
            default="",
        )

    def __init__(self, title="Prompt From Template", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("template_file", socket_type="str", optional=True)
        self.add_input("template_text", socket_type="str", optional=True)
        self.add_input("variables", socket_type="dict", optional=True)

        self.set_property("scope", "scene")
        self.set_property("template_file", "")
        self.set_property("template_text", "")

        self.add_output("prompt", socket_type="prompt")

    async def run(self, graph_state: GraphState):
        template_file = self.normalized_input_value("template_file")
        template_text = self.normalized_input_value("template_text")
        variables = self.normalized_input_value("variables") or {}
        scope = self.get_property("scope")

        if template_file and template_text:
            raise InputValueError(
                self,
                "template_file",
                "Cannot provide both template_file and template_text",
            )

        if template_file:
            if scope != "scene":
                template_uid = f"{scope}.{template_file}"
            else:
                template_uid = template_file

            prompt: Prompt = Prompt.get(template_uid, vars=variables)
        elif template_text:
            # Pass agent_type to preserve template context for includes
            agent_type = scope if scope != "scene" else ""
            prompt: Prompt = Prompt.from_text(
                template_text, vars=variables, agent_type=agent_type
            )
        else:
            raise InputValueError(
                self,
                "template_file",
                "Must provide either template_file or template_text",
            )

        self.set_output_values({"prompt": prompt})


@register("prompt/LoadTemplate")
class LoadTemplate(Node):
    """
    Loads the raw unrendered jinja2 template content based on scope and name

    Inputs:

    - name: The template name (without .jinja2 extension)
    - scope: The template scope (optional, defaults to property)

    Properties:

    - scope: the template scope (choices of agents or scene)
    - name: The template name to load

    Outputs:

    - template_content: The raw unrendered template content as a string
    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            auto_title="{scope}/{name}",
        )

    class Fields:
        scope = PropertyField(
            name="scope",
            type="str",
            generate_choices=lambda: ["scene"] + list(get_agent_types()),
            description="The template scope",
            default="scene",
        )

        name = PropertyField(
            name="name",
            type="str",
            description="The template name to load (without .jinja2 extension)",
            default="",
        )

    def __init__(self, title="Load Template", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("name", socket_type="str", optional=True)
        self.add_input("scope", socket_type="str", optional=True)

        self.set_property("scope", "scene")
        self.set_property("name", "")

        self.add_output("template_content", socket_type="str")
        self.add_output("scope", socket_type="str")

    async def run(self, graph_state: GraphState):
        name = self.normalized_input_value("name") or self.get_property("name")
        scope = self.normalized_input_value("scope") or self.get_property("scope")

        if not name:
            raise InputValueError(
                self,
                "name",
                "Must provide template name",
            )

        # Determine agent_type from scope
        if scope == "scene":
            agent_type = ""
        else:
            agent_type = scope

        try:
            # When scope is "scene", prepend the scene's template directory
            scene = active_scene.get()
            if scope == "scene" and scene:
                with PrependTemplateDirectories([scene.template_dir]):
                    template_content = Prompt.load_template_source(agent_type, name)
            else:
                # Use Prompt's class method to load the template source
                template_content = Prompt.load_template_source(agent_type, name)
        except jinja2.TemplateNotFound:
            raise InputValueError(
                self,
                "name",
                f"Template '{name}' not found in scope '{scope}'",
            )
        except Exception as e:
            log.error("load_template", name=name, scope=scope, error=str(e))
            raise InputValueError(
                self,
                "name",
                f"Error loading template '{name}': {e}",
            )

        self.set_output_values(
            {
                "template_content": template_content,
                "scope": scope,
            }
        )


@register("prompt/RenderPrompt")
class RenderPrompt(Node):
    """
    Renders a prompt

    Input:

    - prompt: The prompt to render

    Outputs:

    - rendered: The rendered prompt
    """

    def __init__(self, title="Render Prompt", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("prompt", socket_type="prompt")

        self.add_output("rendered", socket_type="str")

    async def run(self, graph_state: GraphState):
        prompt: Prompt = self.require_input("prompt")
        rendered = prompt.render()

        self.set_output_values(
            {
                "rendered": rendered,
            }
        )


@register("prompt/BuildPrompt")
class BuildPrompt(Node):
    """
    Builds a prompt based on needs and dynamic instructions
    """

    class Fields:
        template_file = PropertyField(
            name="template_file",
            type="str",
            description="The template file to use",
            default="base",
        )
        scope = PropertyField(
            name="scope",
            type="str",
            description="The scope of the template",
            default="common",
        )
        instructions = PropertyField(
            name="instructions",
            type="text",
            description="The instructions to include in the prompt",
            default="",
        )
        reserved_tokens = PropertyField(
            name="reserved_tokens",
            type="int",
            description="The number of tokens to reserve to account for any overhead",
            default=312,
            step=16,
            min=16,
            max=1024,
        )
        limit_max_tokens = PropertyField(
            name="limit_max_tokens",
            type="int",
            description="Limit the maximum number of tokens used for the prompt (0 = client context limit)",
            default=0,
            min=0,
        )
        technical = PropertyField(
            name="technical",
            type="bool",
            description="Include the technical context where applicable (ids, typing etc.)",
            default=False,
        )
        include_scene_intent = PropertyField(
            name="include_scene_intent",
            type="bool",
            description="Include the scene intent",
            default=True,
        )
        include_extra_context = PropertyField(
            name="include_extra_context",
            type="bool",
            description="Include the extra context (pins, reinforcements, content classification)",
            default=True,
        )
        include_memory_context = PropertyField(
            name="include_memory_context",
            type="bool",
            description="Include the memory context",
            default=True,
        )
        include_scene_context = PropertyField(
            name="include_scene_context",
            type="bool",
            description="Include the scene context",
            default=True,
        )
        include_character_context = PropertyField(
            name="include_character_context",
            type="bool",
            description="Include the active character context",
            default=False,
        )
        include_gamestate_context = PropertyField(
            name="include_gamestate_context",
            type="bool",
            description="Include the game state context",
            default=False,
        )
        memory_prompt = PropertyField(
            name="memory_prompt",
            type="str",
            description="Semantic query / retrieval prompt for memory",
            default="",
        )
        prefill_prompt = PropertyField(
            name="prefill_prompt",
            type="str",
            description="Prefill the prompt with a response",
            default="",
        )
        return_prefill_prompt = PropertyField(
            name="return_prefill_prompt",
            type="bool",
            description="Return the prefill prompt with the response",
            default=False,
        )
        dedupe_enabled = PropertyField(
            name="dedupe_enabled",
            type="bool",
            description="Enable deduplication",
            default=True,
        )
        response_length = PropertyField(
            name="response_length",
            type="int",
            description="The length of the response",
            default=0,
        )

    def __init__(self, title="Build Prompt", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("agent", socket_type="agent")
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("dynamic_context", socket_type="list", optional=True)
        self.add_input("dynamic_instructions", socket_type="list", optional=True)
        self.add_input("memory_prompt", socket_type="str", optional=True)
        self.set_property("template_file", "base")
        self.set_property("scope", "common")
        self.set_property("instructions", "")
        self.set_property("reserved_tokens", 312)
        self.set_property("limit_max_tokens", 0)
        self.set_property("include_scene_intent", True)
        self.set_property("include_extra_context", True)
        self.set_property("include_memory_context", True)
        self.set_property("include_scene_context", True)
        self.set_property("include_character_context", False)
        self.set_property("include_gamestate_context", False)
        self.set_property("memory_prompt", "")
        self.set_property("prefill_prompt", "")
        self.set_property("return_prefill_prompt", False)
        self.set_property("dedupe_enabled", True)
        self.set_property("response_length", 0)
        self.set_property("technical", False)
        self.add_output("state", socket_type="state")
        self.add_output("agent", socket_type="agent")
        self.add_output("prompt", socket_type="prompt")
        self.add_output("rendered", socket_type="str")
        self.add_output("response_length", socket_type="int")

    async def run(self, state: GraphState):
        state: GraphState = self.require_input("state")
        agent: Agent = self.require_input("agent")
        scene: "Scene" = active_scene.get()
        dynamic_context: list[DynamicInstruction] = self.normalized_input_value(
            "dynamic_context"
        )
        dynamic_instructions: list[DynamicInstruction] = self.normalized_input_value(
            "dynamic_instructions"
        )
        instructions: str = self.normalized_input_value("instructions")
        template_file: str = self.get_property("template_file")
        scope: str = self.get_property("scope")
        reserved_tokens: int = self.get_property("reserved_tokens")
        limit_max_tokens: int = self.normalized_input_value("limit_max_tokens")
        include_scene_intent: bool = self.get_property("include_scene_intent")
        include_extra_context: bool = self.get_property("include_extra_context")
        include_memory_context: bool = self.get_property("include_memory_context")
        include_scene_context: bool = self.get_property("include_scene_context")
        include_character_context: bool = self.get_property("include_character_context")
        include_gamestate_context: bool = self.get_property("include_gamestate_context")
        memory_prompt: str = self.get_property("memory_prompt")
        prefill_prompt: str = self.get_property("prefill_prompt")
        return_prefill_prompt: bool = self.get_property("return_prefill_prompt")
        dedupe_enabled: bool = self.get_property("dedupe_enabled")
        response_length: int = self.get_property("response_length")
        technical: bool = self.get_property("technical")
        variables: dict = {
            "scene": scene,
            "agent": agent,
            "max_tokens": agent.client.max_token_length
            if not limit_max_tokens
            else limit_max_tokens,
            "reserved_tokens": reserved_tokens,
            "limit_max_tokens": limit_max_tokens,
            "include_scene_intent": include_scene_intent,
            "include_extra_context": include_extra_context,
            "include_memory_context": include_memory_context,
            "include_scene_context": include_scene_context,
            "include_character_context": include_character_context,
            "include_gamestate_context": include_gamestate_context,
            "memory_prompt": memory_prompt,
            "prefill_prompt": prefill_prompt,
            "return_prefill_prompt": return_prefill_prompt,
            "dynamic_instructions": dynamic_instructions,
            "dynamic_context": dynamic_context,
            "instructions": instructions,
            "response_length": response_length,
            "technical": technical,
            "gamestate": scene.game_state.variables,
        }

        prompt: Prompt = Prompt.get(f"{scope}.{template_file}", vars=variables)

        prompt.client = getattr(agent, "client", None)
        prompt.dedupe_enabled = dedupe_enabled

        prompt.render()

        self.set_output_values(
            {
                "state": state,
                "agent": agent,
                "prompt": prompt,
                "rendered": prompt.prompt,
                "response_length": response_length,
            }
        )


@register("prompt/TemplateVariables")
class TemplateVariables(Node):
    """
    Helper node that returns a pre defined set of common
    template variables

    Variables:

    - scene: The current scene
    - max_tokens: The maximum number of tokens in the response

    Inputs:

    - agent: The relevant agent
    - merge_with: A dictionary of variables to merge with the pre defined variables (optional)

    Outputs:

    - variables: A dictionary of variables
    - agent: The relevant agent
    """

    def __init__(self, title="Template Variables", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("agent", socket_type="agent")
        self.add_input("merge_with", socket_type="dict", optional=True)
        self.add_output("variables", socket_type="dict")
        self.add_output("agent", socket_type="agent")

    async def run(self, graph_state: GraphState):
        agent: Agent = self.require_input("agent")
        merge_with: dict = self.normalized_input_value("merge_with") or {}
        if not hasattr(agent, "client"):
            raise InputValueError(self, "agent", "Agent does not have a client")

        scene = active_scene.get()

        variables = {
            "scene": scene,
            "scene_title": scene.title or scene.name,
            "max_tokens": agent.client.max_token_length,
            "agent": agent,
        }

        variables.update(merge_with)

        self.set_output_values({"variables": variables, "agent": agent})


@register("prompt/GenerateResponse")
class GenerateResponse(Node):
    """
    Sends a prompt to the agent and generates a response

    Inputs:

    - agent: The agent to send the prompt to
    - prompt: The prompt to send to the agent

    Properties

    - data_output: Output the response as data structure
    - attempts: The number of attempts to attempt (on empty response)

    Outputs:

    - response: The response from the agent
    - data_obj: The data structure of the response
    - rendered_prompt: The rendered prompt
    - agent: The agent that generated the response

    """

    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#392c34",
            title_color="#572e44",
            icon="F1719",  # robot-happy
        )

    class Fields:
        data_output = PropertyField(
            name="data_output",
            type="bool",
            default=False,
            description="Output the response as a data structure",
        )

        data_multiple = PropertyField(
            name="data_multiple",
            type="bool",
            default=False,
            description="Allow multiple data structures in the response",
        )

        attempts = PropertyField(
            name="attempts",
            type="int",
            description="The number of attempts (retry on empty response)",
            default=1,
        )

        response_length = PropertyField(
            name="response_length",
            type="int",
            description="The maximum length of the response",
            default=256,
        )

        action_type = PropertyField(
            name="action_type",
            type="str",
            description="Classification of the generated response",
            choices=sorted(
                [
                    "conversation",
                    "narrate",
                    "create",
                    "scene_direction",
                    "analyze",
                    "edit",
                    "world_state",
                    "summarize",
                    "visualize",
                ]
            ),
            default="scene_direction",
        )

    def __init__(self, title="Generate Response", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("agent", socket_type="agent")
        self.add_input("prompt", socket_type="prompt")
        self.add_input("action_type", socket_type="str", optional=True)
        self.add_input("response_length", socket_type="int", optional=True)

        self.set_property("data_output", False)
        self.set_property("data_multiple", False)
        self.set_property("response_length", 256)
        self.set_property("action_type", "scene_direction")
        self.set_property("attempts", 1)

        self.add_output("state", socket_type="state")
        self.add_output("agent", socket_type="agent")
        self.add_output("prompt", socket_type="prompt")
        self.add_output("response", socket_type="str")
        self.add_output("data_obj", socket_type="dict,list")
        self.add_output("captured_context", socket_type="str")
        self.add_output("rendered_prompt", socket_type="str")
        self.add_output("agent", socket_type="agent")

    async def run(self, state: GraphState):
        scene: "Scene" = active_scene.get()
        agent: Agent = self.require_input("agent")
        prompt: Prompt = self.require_input("prompt")
        action_type = self.get_property("action_type")
        response_length = self.require_number_input("response_length", types=(int,))
        data_output = self.get_property("data_output")
        data_multiple = self.get_property("data_multiple")
        attempts = self.get_property("attempts") or 1

        prompt.agent_type = agent.agent_type

        kind = make_kind(
            action_type=action_type, length=response_length, expect_json=data_output
        )

        if data_output:
            prompt.data_response = True
            prompt.data_allow_multiple = data_multiple

        if state.verbosity >= NodeVerbosity.NORMAL:
            log.info(f"Sending prompt to agent {agent.agent_type} with kind {kind}")

        async def send_prompt(*args, **kwargs):
            prompt.vars.update(
                {
                    "response_length": response_length,
                }
            )
            return await prompt.send(agent.client, kind=kind)

        send_prompt.__name__ = self.title.replace(" ", "_").lower()

        with PrependTemplateDirectories(scene.template_dir):
            for _ in range(attempts):
                response = await agent.delegate(send_prompt)
                if response:
                    break

        if isinstance(response, tuple):
            response, data_obj = response
        else:
            data_obj = None

        self.set_output_values(
            {
                "response": response.strip(),
                "data_obj": data_obj,
                "prompt": prompt,
                "state": self.get_input_value("state"),
                "agent": agent,
                "rendered_prompt": prompt.prompt,
                "captured_context": prompt.captured_context,
            }
        )


@register("prompt/CleanResponse")
class CleanResponse(Node):
    """
    Cleans a response

    Inputs:

    - response: The response to clean

    Properties:

    - partial_sentences: Strip partial sentences from the response

    Outputs:

    - cleaned: The cleaned response
    """

    class Fields:
        strip_partial_sentences = PropertyField(
            name="partial_sentences",
            type="bool",
            description="Strip partial sentences from the response",
            default=True,
        )

    def __init__(self, title="Clean Response", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("response", socket_type="str")

        self.set_property("partial_sentences", True)

        self.add_output("cleaned", socket_type="str")

    async def run(self, graph_state: GraphState):
        response = self.require_input("response")
        partial_sentences = self.get_property("partial_sentences")

        if partial_sentences:
            response = strip_partial_sentences(response)

        self.set_output_values({"cleaned": response})
