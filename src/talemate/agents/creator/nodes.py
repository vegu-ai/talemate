import structlog
from typing import ClassVar, TYPE_CHECKING
from talemate.context import active_scene
from talemate.game.engine.nodes.core import Node, GraphState, PropertyField, UNRESOLVED, InputValueError, TYPE_CHOICES
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.game.engine.nodes.agents.creator")

@register("agents/creator/Settings")
class CreatorSettings(AgentSettingsNode):
    """
    Base node to render creator agent settings.
    """
    _agent_name:ClassVar[str] = "creator"
    
    def __init__(self, title="Creator Settings", **kwargs):
        super().__init__(title=title, **kwargs)
        
        
@register("agents/creator/DetermineContentContext")
class DetermineContentContext(AgentNode):
    """
    Determines the context for the content creation.
    """
    _agent_name:ClassVar[str] = "creator"
    
    class Fields:
        description = PropertyField(
            name="description",
            description="Description of the context",
            type="str",
            default=UNRESOLVED
        )
    
    def __init__(self, title="Determine Content Context", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_input("description", socket_type="str", optional=True)
        
        self.set_property("description", UNRESOLVED)
        
        self.add_output("content_context", socket_type="str")
        
    async def run(self, state: GraphState):
        context = await self.agent.determine_content_context_for_description(
            self.require_input("description")
        )
        self.set_output_values({
            "content_context": context
        })
        
@register("agents/creator/DetermineCharacterDescription")
class DetermineCharacterDescription(AgentNode):
    """
    Determines the description for a character.
    
    Inputs:
    
    - state: The current state of the graph
    - character: The character to determine the description for
    - extra_context: Extra context to use in determining the
    
    Outputs:
    
    - description: The determined description
    """
    _agent_name:ClassVar[str] = "creator"
    
    def __init__(self, title="Determine Character Description", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("extra_context", socket_type="str", optional=True)
        
        self.add_output("description", socket_type="str")
        
    async def run(self, state: GraphState):
        
        character = self.require_input("character")
        extra_context = self.get_input_value("extra_context")
        
        if extra_context is UNRESOLVED:
            extra_context = ""
        
        description = await self.agent.determine_character_description(character, extra_context)
        
        self.set_output_values({
            "description": description
        })
        
@register("agents/creator/DetermineCharacterDialogueInstructions")
class DetermineCharacterDialogueInstructions(AgentNode):
    """
    Determines the dialogue instructions for a character.
    """
    _agent_name:ClassVar[str] = "creator"
    
    class Fields:
        instructions = PropertyField(
            name="instructions",
            description="Any additional instructions to use in determining the dialogue instructions",
            type="text",
            default=""
        )
    
    def __init__(self, title="Determine Character Dialogue Instructions", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("instructions", socket_type="str", optional=True)
        
        self.set_property("instructions", "")
        
        self.add_output("dialogue_instructions", socket_type="str")
        
    async def run(self, state: GraphState):
        character = self.require_input("character")
        instructions = self.normalized_input_value("instructions")
        
        dialogue_instructions = await self.agent.determine_character_dialogue_instructions(character, instructions)
        
        self.set_output_values({
            "dialogue_instructions": dialogue_instructions
        })
        
        
@register("agents/creator/ContextualGenerate")
class ContextualGenerate(AgentNode):
    """
    Generates text based on the given context.
    
    Inputs:
    
    - state: The current state of the graph
    - context_type: The type of context to use in generating the text
    - context_name: The name of the context to use in generating the text
    - instructions: The instructions to use in generating the text
    - length: The length of the text to generate
    - character: The character to generate the text for
    - original: The original text to use in generating the text
    - partial: The partial text to use in generating the text
    - uid: The uid to use in generating the text
    - generation_options: The generation options to use in generating the text
    
    Properties:
    
    - context_type: The type of context to use in generating the text
    - context_name: The name of the context to use in generating the text
    - instructions: The instructions to use in generating the text
    - length: The length of the text to generate
    - character: The character to generate the text for
    - uid: The uid to use in generating the text
    - context_aware: Whether to use the context in generating the text
    - history_aware: Whether to use the history in generating the text
    
    Outputs:
    
    - state: The updated state of the graph
    - text: The generated text
    """
    _agent_name:ClassVar[str] = "creator"
    
    class Fields:
        context_type = PropertyField(
            name="context_type",
            description="The type of context to use in generating the text",
            type="str",
            choices=["character attribute", "character detail", "character dialogue", "scene intro", "scene intent", "scene phase intent", "scene type description", "scene type instructions", "general", "list"],
            default="general"
        )
        context_name = PropertyField(
            name="context_name",
            description="The name of the context to use in generating the text",
            type="str",
            default=UNRESOLVED
        )
        instructions = PropertyField(
            name="instructions",
            description="The instructions to use in generating the text",
            type="str",
            default=UNRESOLVED
        )
        length = PropertyField(
            name="length",
            description="The length of the text to generate",
            type="int",
            default=100
        )
        character = PropertyField(
            name="character",
            description="The character to generate the text for",
            type="str",
            default=UNRESOLVED
        )
        uid = PropertyField(
            name="uid",
            description="The uid to use in generating the text",
            type="str",
            default=UNRESOLVED
        )
        context_aware = PropertyField(
            name="context_aware",
            description="Whether to use the context in generating the text",
            type="bool",
            default=True
        )
        history_aware = PropertyField(
            name="history_aware",
            description="Whether to use the history in generating the text",
            type="bool",
            default=True
        )
        
        
    def __init__(self, title="Contextual Generate", **kwargs):
        super().__init__(title=title, **kwargs)
        
    def setup(self):
        self.add_input("state")
        self.add_input("context_type", socket_type="str", optional=True)
        self.add_input("context_name", socket_type="str", optional=True)
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("length", socket_type="int", optional=True)
        self.add_input("character", socket_type="character,str", optional=True)
        self.add_input("original", socket_type="str", optional=True)
        self.add_input("partial", socket_type="str", optional=True)
        self.add_input("uid", socket_type="str", optional=True)
        self.add_input("generation_options", socket_type="generation_options", optional=True)
        
        self.set_property("context_type", "general")
        self.set_property("context_name", UNRESOLVED)
        self.set_property("instructions", UNRESOLVED)
        self.set_property("length", 100)
        self.set_property("character", UNRESOLVED)
        self.set_property("uid", UNRESOLVED)
        self.set_property("context_aware", True)
        self.set_property("history_aware", True)
        
        self.add_output("state")
        self.add_output("text", socket_type="str")
    
    async def run(self, state: GraphState):
        scene = active_scene.get()
        context_type = self.require_input("context_type")
        context_name = self.normalized_input_value("context_name")
        instructions = self.normalized_input_value("instructions")
        length = self.require_number_input("length")
        character = self.normalized_input_value("character")
        original = self.normalized_input_value("original")
        partial = self.normalized_input_value("partial")
        uid = self.normalized_input_value("uid")
        generation_options = self.normalized_input_value("generation_options")
        context_aware = self.normalized_input_value("context_aware")
        history_aware = self.normalized_input_value("history_aware")
        
        context = f"{context_type}:{context_name}" if context_name else context_type
        
        if isinstance(character, scene.Character):
            character = character.name
        
        text = await self.agent.contextual_generate_from_args(
            context=context,
            instructions=instructions,
            length=length,
            character=character,
            original=original,
            partial=partial or "",
            uid=uid,
            writing_style=generation_options.writing_style if generation_options else None,
            spices=generation_options.spices if generation_options else None,
            spice_level=generation_options.spice_level if generation_options else 0.0,
            context_aware=context_aware,
            history_aware=history_aware
        )
        
        self.set_output_values({
            "state": state,
            "text": text
        })