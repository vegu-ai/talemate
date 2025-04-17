import inspect
import pydantic
import structlog
from typing import TYPE_CHECKING, Callable
from talemate.game.engine.nodes.core import (
    Node, 
    register, 
    GraphState, 
    InputValueError, 
    PropertyField, 
    NodeVerbosity,
    NodeStyle,
    UNRESOLVED,
    TYPE_CHOICES,
)
from talemate.agents.registry import get_agent_types
from talemate.agents.base import Agent, set_processing
from talemate.instance import get_agent
from talemate.prompts.base import Prompt, PrependTemplateDirectories
from talemate.client.presets import make_kind
from talemate.context import active_scene

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.nodes.prompt")

TYPE_CHOICES.extend([
    "prompt",
])

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
            default="scene"
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
            raise InputValueError(self, "template_file", "Cannot provide both template_file and template_text")
        
        if template_file:
            if scope != "scene":
                template_uid = f"{scope}.{template_file}"
            else:
                template_uid = template_file
                
            prompt: Prompt = Prompt.get(template_uid, vars=variables)
        elif template_text:
            prompt: Prompt = Prompt.from_text(template_text, vars=variables)
        else:
            raise InputValueError(self, "template_file", "Must provide either template_file or template_text")
        
        self.set_output_values({
            "prompt": prompt
        })
        
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
        prompt:Prompt = self.require_input("prompt")
        rendered = prompt.render()
        
        self.set_output_values({
            "rendered": rendered,
        })
    

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
        agent:Agent = self.require_input("agent")
        merge_with:dict = self.normalized_input_value("merge_with") or {}
        if not hasattr(agent, "client"):
            raise InputValueError(self, "agent", "Agent does not have a client")
        
        variables = {
            "scene": active_scene.get(),
            "max_tokens": agent.client.max_token_length,
        }
        
        variables.update(merge_with)
        
        self.set_output_values({
            "variables": variables,
            "agent": agent
        })

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
            icon="F1719", #robot-happy
        )
        
    class Fields:
        data_output = PropertyField(
            name="data_output",
            type="bool",
            default=False,
            description="Output the response as a data structure"
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
            choices=sorted([
                "conversation",
                "narrate",
                "create",
                "scene_direction",
                "analyze",
                "edit",
                "world_state",
                "summarize",
            ]),
            default="scene_direction"
        )
    
    
    def __init__(self, title="Generate Response", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_input("agent", socket_type="agent")
        self.add_input("prompt", socket_type="prompt")
        self.add_input("action_type", socket_type="str", optional=True)
        
        self.set_property("data_output", False)
        self.set_property("response_length", 256)
        self.set_property("action_type", "scene_direction")
        self.set_property("attempts", 1)
        
        self.add_output("response", socket_type="str")
        self.add_output("data_obj", socket_type="dict")
        self.add_output("rendered_prompt", socket_type="str")
        self.add_output("agent", socket_type="agent")
        
        
    async def run(self, state: GraphState):
        scene:"Scene" = active_scene.get()
        agent:Agent = self.require_input("agent")
        prompt:Prompt = self.require_input("prompt")
        action_type = self.get_property("action_type")
        response_length = self.get_property("response_length")
        data_output = self.get_property("data_output")
        attempts = self.get_property("attempts") or 1
        
        kind = make_kind(
            action_type=action_type,
            length=response_length,
            expect_json=data_output
        )
        
        if data_output:
            prompt.data_response = True
        
        if state.verbosity >= NodeVerbosity.NORMAL:
            log.info(f"Sending prompt to agent {agent.agent_type} with kind {kind}")
        
        async def send_prompt(*args, **kwargs):
            return await prompt.send(agent.client, kind=kind)
        send_prompt.__name__= self.title.replace(" ", "_").lower()
        
        with PrependTemplateDirectories(scene.template_dir):
            for _ in range(attempts):
                response = await agent.delegate(send_prompt)
                if response:
                    break
        
        if isinstance(response, tuple):
            response, data_obj = response
        else:
            data_obj = None
        
        self.set_output_values({
            "response": response.strip(),
            "data_obj": data_obj,
            "rendered_prompt": prompt.prompt,
            "agent": agent
        })
        
        