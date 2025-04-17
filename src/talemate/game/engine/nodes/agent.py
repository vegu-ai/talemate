import inspect
import pydantic
import structlog
from typing import ClassVar
from talemate.game.engine.nodes.core import (
    Node, 
    register, 
    GraphState, 
    InputValueError, 
    PropertyField, 
    NodeVerbosity,
    NodeStyle,
    UNRESOLVED,
)
from talemate.agents.registry import get_agent_types
from talemate.instance import get_agent


log = structlog.get_logger("talemate.game.engine.nodes.agent")

class AgentNode(Node):
    
    _agent_name:ClassVar[str | None] = None

    
    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#392c34",
            title_color="#572e44",
            icon="F1719", #robot-happy
        )
    
    @property
    def agent(self):
        return get_agent(self._agent_name)
    
    async def get_agent(self, agent_name:str):
        return get_agent(agent_name)


class AgentSettingsNode(Node):
    """
    Base node to render agent settings.
    
    Will take an _agent_name class property, then create
    outputs based on the agents' AgentAction and AgentActionConfig
    """
    
    _agent_name:ClassVar[str | None] = None
    
    def setup(self):
        agent = get_agent(self._agent_name)
        
        if not agent:
            raise InputValueError(self, "_agent_name", f"Could not find agent: {self._agent_name}")
        
        self.add_output("agent_enabled", socket_type="bool")
        
        for action_name, action in agent.actions.items():
            self.add_output(f"{action_name}_enabled", socket_type="bool")
            
            if not action.config:
                continue
            
            for config_name, config in action.config.items():
                self.add_output(f"{action_name}_{config_name}", socket_type=config.type)
                
    async def run(self, state: GraphState):
        agent = get_agent(self._agent_name)
        
        if not agent:
            raise InputValueError(self, "_agent_name", f"Could not find agent: {self._agent_name}")
        
        outputs = {
            "agent_enabled": agent.enabled
        }
        
        for action_name, action in agent.actions.items():
            outputs[f"{action_name}_enabled"] = action.enabled
            
            if not action.config:
                continue
            
            for config_name, config in action.config.items():
                outputs[f"{action_name}_{config_name}"] = config.value
                
        self.set_output_values(outputs)

@register("agents/ToggleAgentAction")
class ToggleAgentAction(Node):
    """
    Allows disabling or enabling an agent action
    
    Inputs:
    
    - agent: str,agent
    - action_name: str
    - enabled: bool
    
    Outputs:
    
    - agent: agent
    - action_name: str
    - enabled: bool
    """
    
    class Fields:
        agent = PropertyField(
            name="agent",
            type="str",
            default="",
            description="The agent to toggle the action on",
            choices=[],
            generate_choices=lambda: get_agent_types()
        )
        
        action_name = PropertyField(
            name="action_name",
            type="str",
            default="",
            description="The name of the action to toggle"
        )
        
        enabled = PropertyField(
            name="enabled",
            type="bool",
            default=True,
            description="Whether to enable or disable the action"
        )
        
    
    def setup(self):
        self.add_input("state")
        self.add_input("agent", socket_type="str,agent", optional=True)
        self.add_input("action_name", socket_type="str", optional=True)
        self.add_input("enabled", socket_type="bool", optional=True)
        
        self.set_property("agent", "")
        self.set_property("action_name", "")
        self.set_property("enabled", True)
        
        self.add_output("agent", socket_type="agent")
        self.add_output("action_name", socket_type="str")
        self.add_output("enabled", socket_type="bool")
        
    async def run(self, state: GraphState):
        agent = self.get_input_value("agent")
        action_name = self.get_input_value("action_name")
        enabled = self.get_input_value("enabled")
        
        if isinstance(agent, str):
            agent_name = agent
            agent = get_agent(agent_name)
            if not agent:
                raise InputValueError(self, "agent", f"Could not find agent: {agent_name}")
        
        action = agent.actions.get(action_name)
        
        if not action:
            raise InputValueError(self, "action_name", f"Could not find action {action_name} in agent {agent}")
        
        action.enabled = enabled
        
        self.set_output_values({
            "agent": agent,
            "action_name": action_name,
            "enabled": enabled
        })

@register("agents/CallAgentFunction")
class CallAgentFunction(Node):
    """
    Call an agent function
    """
    
    class Fields:
        agent = PropertyField(
            name="agent",
            type="str",
            default="",
            description="The agent to call the function on",
            choices=[],
            generate_choices=lambda: get_agent_types()
        )
        
        function_name = PropertyField(
            name="function_name",
            type="str",
            default="",
            description="The name of the function to call on the agent"
        )
        
        arguments = PropertyField(
            name="arguments",
            type="dict",
            default={},
            description="The arguments to pass to the function"
        )
    
    def __init__(self, title="Call Agent Function", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("agent", socket_type="str,agent")
        self.add_input("function_name", socket_type="str")
        self.add_input("arguments", socket_type="dict")
        
        self.set_property("agent", "")
        self.set_property("function_name", "")
        self.set_property("arguments", {})
        
        self.add_output("result", socket_type="any")
        
    async def run(self, state: GraphState):
        agent = self.get_input_value("agent")
        function_name = self.get_input_value("function_name")
        arguments = self.get_input_value("arguments")
        
        if isinstance(agent, str):
            agent_name = agent
            agent = get_agent(agent_name)
            if not agent:
                raise InputValueError(self, "agent", f"Could not find agent: {agent_name}")
        
        function = getattr(agent, function_name, None)
        
        if not function:
            raise InputValueError(self, "function_name", f"Could not find function {function_name} in agent {agent}")
        
        # is function a coroutine?
        if inspect.iscoroutinefunction(function):
            result = await function(**arguments)
        else:
            result = function(**arguments)
        
        if state.verbosity >= NodeVerbosity.VERBOSE:
            log.debug(f"Called agent function {function_name} on agent {agent}", result=result, arguments=arguments)
        
        self.set_output_values({
            "result": result
        })

@register("agents/GetAgent")
class GetAgent(Node):
    """
    Get an agent instance
    """

    class Fields:
        agent_name = PropertyField(
            name="agent_name",
            type="str",
            default="",
            description="The name of the agent to get the client for",
            choices=[],
            generate_choices=lambda: get_agent_types()
        )
        
    
    @pydantic.computed_field(description="Node style")
    @property
    def style(self) -> NodeStyle:
        return NodeStyle(
            node_color="#313150",
            title_color="#403f71",
            auto_title="{agent_name}",
            icon="F0D3D", #transit-connection-variant
        )
    
    def __init__(self, title="Get Agent", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.set_property("agent_name", "")
        self.add_output("agent", socket_type="agent")
        
    async def run(self, state: GraphState):
        agent_name = self.get_property("agent_name")
        
        if not agent_name:
            return
        
        agent = get_agent(agent_name)
        
        if not agent:
            raise InputValueError(self, "agent_name", f"Could not find agent: {agent_name}")
        
        self.set_output_values({
            "agent": agent
        })