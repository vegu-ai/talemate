from typing import TYPE_CHECKING, Coroutine, Callable, Any
import asyncio
import nest_asyncio
import contextvars
import structlog
from talemate.emit import emit
from talemate.client.base import ClientBase
from talemate.instance import get_agent, AGENTS
from talemate.agents.base import Agent
from talemate.prompts.base import Prompt

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character
    from talemate.game.state import GameState

__all__ = [
    "OpenScopedContext",
    "GameStateScope",
    "ClientScope",
    "AgentScope",
    "LogScope",
    "GameInstructionScope",
    "run_async",
    "scoped_context",
]

nest_asyncio.apply()

log = structlog.get_logger("talemate.game.scope")

def run_async(coro:Coroutine):
    """
    runs a coroutine
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


class ScopedContext:
    def __init__(self, scene:"Scene" = None, client:ClientBase = None):
        self.scene = scene
        self.client = client
        
scoped_context = contextvars.ContextVar("scoped_context", default=ScopedContext())


class OpenScopedContext:
    def __init__(self, scene:"Scene", client:ClientBase):
        self.scene = scene
        self.context = ScopedContext(
            scene = scene,
            client = client
        )
    
    def __enter__(self):
        self.token = scoped_context.set(
            self.context
        )
    
    def __exit__(self, *args):
        scoped_context.reset(self.token)
        
        
class ObjectScope:
    
    """
    Defines a method for getting the scoped object
    """
    
    exposed_properties = []
    exposed_methods = []
    
    def __init__(self, get_scoped_object:Callable):
        self.scope_object(get_scoped_object)
        
    def __getattr__(self, name:str):
        if name in self.scoped_properties:
            return self.scoped_properties[name]()
        
        return super().__getattr__(name)
        
    def scope_object(self, get_scoped_object:Callable):
        
        self.scoped_properties = {}
        
        for prop in self.exposed_properties:
            self.scope_property(prop, get_scoped_object)
        
        for method in self.exposed_methods:
            self.scope_method(method, get_scoped_object)

    def scope_property(self, prop:str, get_scoped_object:Callable):
        self.scoped_properties[prop] = lambda: getattr(get_scoped_object(), prop)
        
    def scope_method(self, method:str, get_scoped_object:Callable):
        
        def fn(*args, **kwargs):
            _fn = getattr(get_scoped_object(), method)
            
            # if coroutine, run it in the event loop
            if asyncio.iscoroutinefunction(_fn):
                rv = run_async(
                    _fn(*args, **kwargs)
                )
            elif callable(_fn):
                rv = _fn(*args, **kwargs)
            else:
                rv = _fn
                
            return rv
                
        fn.__name__ = method
        #log.debug("Setting", self, method, "to", fn.__name__)
        setattr(self, method, fn)


class ClientScope(ObjectScope):
    
    """
    Wraps the client with certain exposed
    methods that can be used in game logic implementations
    through the scene's game.py file.
    
    Exposed:
    
    - send_prompt
    """
    
    exposed_properties = [
        "send_prompt"
    ]
    
    def __init__(self):
        super().__init__(lambda: scoped_context.get().client)
        
    def render_and_request(self, template_name:str, kind:str="create", dedupe_enabled:bool=True, **kwargs):
        
        """ 
        Renders a prompt and sends it to the client
        """
        prompt = Prompt.get(template_name, kwargs)
        prompt.client = scoped_context.get().client
        prompt.dedupe_enabled = dedupe_enabled
        return run_async(prompt.send(scoped_context.get().client, kind))
        
    def query_text_eval(self, query: str, text: str):
        world_state = get_agent("world_state")
        query = f"{query} Answer with a yes or no."
        response = run_async(
            world_state.analyze_text_and_answer_question(text=text, query=query, short=True)
        )
        return response.strip().lower().startswith("y")
        
class AgentScope(ObjectScope):
    
    """
    Wraps agent calls with certain exposed
    methods that can be used in game logic implementations
    
    Exposed:
    
    - action: calls an agent action
    - config: returns the agent's configuration
    """
        
    def __init__(self, agent:Agent):
        
        self.exposed_properties = [
            "sanitized_action_config",
        ]
        
        self.exposed_methods = []
        
        # loop through all methods on agent and add them to the scope
        # if the function has `exposed` attribute set to True
        
        for key in dir(agent):
            value = getattr(agent, key)
            if callable(value) and hasattr(value, "exposed") and value.exposed:
                self.exposed_methods.append(key)
                
        # log.debug("AgentScope", agent=agent, exposed_properties=self.exposed_properties, exposed_methods=self.exposed_methods)
        
        super().__init__(lambda: agent)
        self.config = lambda: agent.sanitized_action_config
    
class GameStateScope(ObjectScope):
    
    exposed_methods = [
        "set_var",
        "has_var",
        "get_var",
        "get_or_set_var",
        "unset_var",
    ]
    
    def __init__(self):
        super().__init__(lambda: scoped_context.get().scene.game_state)
        
class LogScope:

    """
    Wrapper for log calls
    """
    
    def __init__(self, log:object):
        self.info = log.info
        self.error = log.error
        self.debug = log.debug
        self.warning = log.warning


class CharacterScope(ObjectScope):
    exposed_properties = [
        "name",
        "description",
        "greeting_text",
        "gender",
        "color",
        "example_dialogue",
        "base_attributes",
        "details",
        "is_player",
    ]
    
    exposed_methods = [
        "update",
        "set_detail",
        "set_base_attribute",
        "rename",
    ]
        
class SceneScope(ObjectScope):
    
    """
    Wraps scene calls with certain exposed
    methods that can be used in game logic implementations
    

    """
    
    exposed_properties = [
        "name",
        "title",
    ]
    
    exposed_methods = [
        "context",
        "context_history",
        "last_player_message",
        "npc_character_names",
        "restore",
        "set_content_context",
        "set_title",
    ]
    
    def __init__(self):
        super().__init__(lambda: scoped_context.get().scene)
    
    def get_character(self, name:str) -> "CharacterScope":
        """
        returns a character by name
        """
        character = scoped_context.get().scene.get_character(name)
        if character:
            return CharacterScope(lambda: character)
        
    def get_player_character(self) -> "CharacterScope":
        """
        returns the player character
        """
        character = scoped_context.get().scene.get_player_character()
        if character:
            return CharacterScope(lambda: character)
        
    def history(self):
        return [h for h in scoped_context.get().scene.history]

class GameInstructionScope:
    
    def __init__(self, agent:Agent, log:object, scene:"Scene", module_function:callable):
        self.game_state = GameStateScope()
        self.client = ClientScope()
        self.agents = type('', (), {})()
        self.scene = SceneScope()
        self.wait = run_async
        self.log = LogScope(log)
        self.module_function = module_function
        
        for key, agent in AGENTS.items():
            setattr(self.agents, key, AgentScope(agent))
        
        
    def __call__(self):
        self.module_function(self)
        
    def emit_status(self, status: str, message: str, **kwargs):
        if kwargs:
            emit("status", status=status, message=message, data=kwargs)
        else:
            emit("status", status=status, message=message)