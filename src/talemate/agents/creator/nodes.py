import structlog
from typing import ClassVar
from talemate.context import active_scene
from talemate.game.engine.nodes.core import (
    GraphState,
    PropertyField,
    UNRESOLVED,
    InputValueError,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode
from talemate.agents.creator.character import CharacterGenerationRequest

log = structlog.get_logger("talemate.game.engine.nodes.agents.creator")


@register("agents/creator/Settings")
class CreatorSettings(AgentSettingsNode):
    """
    Base node to render creator agent settings.
    """

    _agent_name: ClassVar[str] = "creator"

    def __init__(self, title="Creator Settings", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/creator/DetermineContentContext")
class DetermineContentContext(AgentNode):
    """
    Determines a fitting content context label (genre / style descriptor)
    for the given description, via the creator agent.

    Inputs:

    - state: The current state of the graph
    - description: The description to determine the content context for
      (required at runtime despite the optional socket)

    Outputs:

    - content_context: The determined content context
    """

    _agent_name: ClassVar[str] = "creator"

    class Fields:
        description = PropertyField(
            name="description",
            description="Description of the context",
            type="str",
            default=UNRESOLVED,
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
        self.set_output_values({"content_context": context})


@register("agents/creator/DetermineCharacterDescription")
class DetermineCharacterDescription(AgentNode):
    """
    Determines the description for a character.

    Inputs:

    - state: The current state of the graph
    - character: The character to determine the description for
    - extra_context: Extra context to use in determining the description

    Outputs:

    - description: The determined description
    """

    _agent_name: ClassVar[str] = "creator"

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

        description = await self.agent.determine_character_description(
            character, extra_context
        )

        self.set_output_values({"description": description})


@register("agents/creator/DetermineCharacterName")
class DetermineCharacterName(AgentNode):
    """
    Determines (or clarifies) a character name from an existing or descriptive name.

    Inputs:

    - state: The current state of the graph
    - character_name: The current or descriptive character name
    - allowed_names: Optional list of allowed names to select from
    - is_group: Whether the name describes a group of characters
    - instructions: Additional instructions to guide name generation

    Outputs:

    - state: The current state of the graph (pass-through)
    - character_name: The determined name
    - original: The original character_name input
    - allowed_names: The allowed_names input (pass-through)
    - is_group: The is_group input (pass-through)
    - instructions: The instructions input (pass-through)
    """

    _agent_name: ClassVar[str] = "creator"

    class Fields:
        character_name = PropertyField(
            name="character_name",
            description="The current or descriptive character name",
            type="str",
            default="",
        )
        allowed_names = PropertyField(
            name="allowed_names",
            description="Optional list of allowed names to select from",
            type="list",
            default=[],
        )
        is_group = PropertyField(
            name="is_group",
            description="Whether the name describes a group of characters",
            type="bool",
            default=False,
        )
        instructions = PropertyField(
            name="instructions",
            description="Additional instructions to guide name generation",
            type="text",
            default="",
        )

    def __init__(self, title="Determine Character Name", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character_name", socket_type="str", optional=True)
        self.add_input("allowed_names", socket_type="list", optional=True)
        self.add_input("is_group", socket_type="bool", optional=True)
        self.add_input("instructions", socket_type="str", optional=True)

        self.set_property("character_name", "")
        self.set_property("allowed_names", [])
        self.set_property("is_group", False)
        self.set_property("instructions", "")

        self.add_output("state", socket_type="any")
        self.add_output("character_name", socket_type="str")
        self.add_output("original", socket_type="str")
        self.add_output("allowed_names", socket_type="list")
        self.add_output("is_group", socket_type="bool")
        self.add_output("instructions", socket_type="str")

    async def run(self, state: GraphState):
        state_value = self.get_input_value("state")
        character_name = self.normalized_input_value("character_name") or ""
        allowed_names = self.normalized_input_value("allowed_names") or []
        is_group = self.normalized_input_value("is_group") or False
        instructions = self.normalized_input_value("instructions") or ""
        original: str = character_name

        determined_name = await self.agent.determine_character_name(
            character_name,
            allowed_names=allowed_names,
            group=is_group,
            instructions=instructions,
        )

        self.set_output_values(
            {
                "state": state_value,
                "character_name": determined_name,
                "original": original,
                "allowed_names": allowed_names,
                "is_group": is_group,
                "instructions": instructions,
            }
        )


@register("agents/creator/DetermineCharacterDialogueInstructions")
class DetermineCharacterDialogueInstructions(AgentNode):
    """
    Determines dialogue (acting) instructions for a character, via the
    creator agent. The result is returned but not stored on the character
    by this node.

    Inputs:

    - state: The current state of the graph
    - character: The character to determine dialogue instructions for
    - instructions: Additional instructions to guide the generation (optional)
    - update_existing: Whether to base the result on the character's
      existing dialogue instructions (optional)

    Outputs:

    - state: The state input, passed through
    - character: The character, passed through
    - dialogue_instructions: The determined dialogue instructions
    - original: The character's dialogue instructions before generation
    """

    _agent_name: ClassVar[str] = "creator"

    class Fields:
        instructions = PropertyField(
            name="instructions",
            description="Any additional instructions to use in determining the dialogue instructions",
            type="text",
            default="",
        )
        update_existing = PropertyField(
            name="update_existing",
            description="Whether to update the existing dialogue instructions",
            type="bool",
            default=False,
        )

    def __init__(self, title="Determine Character Dialogue Instructions", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("update_existing", socket_type="bool", optional=True)
        self.set_property("instructions", "")
        self.set_property("update_existing", False)
        self.add_output("state", socket_type="any")
        self.add_output("character", socket_type="character")
        self.add_output("dialogue_instructions", socket_type="str")
        self.add_output("original", socket_type="str")

    async def run(self, state: GraphState):
        character = self.require_input("character")
        instructions: str | None = self.normalized_input_value("instructions")
        update_existing: bool | None = self.normalized_input_value("update_existing")
        original: str | None = character.dialogue_instructions or ""

        dialogue_instructions = (
            await self.agent.determine_character_dialogue_instructions(
                character, instructions, update_existing=update_existing
            )
        )

        self.set_output_values(
            {
                "state": state,
                "character": character,
                "dialogue_instructions": dialogue_instructions,
                "original": original,
            }
        )


@register("agents/creator/GenerateCharacter")
class GenerateCharacter(AgentNode):
    """
    Generates character data with a single consolidated prompt (the unified
    generation approach from the creator agent's "Character Creation" Fast
    Character Generation mode).

    All aspects selected via the node's properties are generated in one go.
    Aspects the consolidated response misses are handled according to the
    creator agent's "Fill in misses" setting (individual follow-up requests
    or left empty); the response budget comes from the agent's "One-shot
    token budget" setting. A completely unparseable response raises an error.

    This node only generates data - it does not add the character to the
    scene. Wire the outputs into an `agents/director/PersistCharacter` node
    to persist the character (disable `determine_name` on that node when
    wiring a generated name, and wire `description` through as well, so
    nothing is generated twice).

    Generating example dialogue requires a name: provide `character_name`
    or enable `generate_name` - the node errors otherwise.

    Inputs:

    - state: The current state of the graph
    - character_name: The current or descriptive character name (optional)
    - instructions: Guiding instructions / content for the creation (optional)
    - description: An existing description to use as context (optional)

    Properties:

    - generate_name: Determine a fitting name
    - generate_description: Generate the character description
    - generate_attributes: Generate the character sheet (attributes)
    - generate_dialogue_instructions: Generate dialogue (acting) instructions
    - generate_example_dialogue: Generate example dialogue lines

    Outputs:

    - state: The state input, passed through
    - character_name: The determined (or input) character name
    - description: The generated description (empty if not generated)
    - attributes: The generated attributes (empty if not generated)
    - dialogue_instructions: The generated dialogue instructions (empty if not generated)
    - example_dialogue: The generated example dialogue lines (empty if not generated)
    """

    _agent_name: ClassVar[str] = "creator"

    class Fields:
        generate_name = PropertyField(
            name="generate_name",
            description="Determine a fitting character name",
            type="bool",
            default=False,
        )
        generate_description = PropertyField(
            name="generate_description",
            description="Generate the character description",
            type="bool",
            default=True,
        )
        generate_attributes = PropertyField(
            name="generate_attributes",
            description="Generate the character sheet (attributes)",
            type="bool",
            default=True,
        )
        generate_dialogue_instructions = PropertyField(
            name="generate_dialogue_instructions",
            description="Generate dialogue (acting) instructions",
            type="bool",
            default=True,
        )
        generate_example_dialogue = PropertyField(
            name="generate_example_dialogue",
            description="Generate example dialogue lines",
            type="bool",
            default=False,
        )

    def __init__(self, title="Generate Character", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character_name", socket_type="str", optional=True)
        self.add_input("instructions", socket_type="str", optional=True)
        self.add_input("description", socket_type="str", optional=True)

        self.set_property("generate_name", False)
        self.set_property("generate_description", True)
        self.set_property("generate_attributes", True)
        self.set_property("generate_dialogue_instructions", True)
        self.set_property("generate_example_dialogue", False)

        self.add_output("state", socket_type="any")
        self.add_output("character_name", socket_type="str")
        self.add_output("description", socket_type="str")
        self.add_output("attributes", socket_type="dict")
        self.add_output("dialogue_instructions", socket_type="str")
        self.add_output("example_dialogue", socket_type="list")

    async def run(self, state: GraphState):
        character_name = self.normalized_input_value("character_name") or ""
        instructions = self.normalized_input_value("instructions") or ""
        description = self.normalized_input_value("description") or ""

        aspects = []
        if self.normalized_input_value("generate_name"):
            aspects.append("name")
        if self.normalized_input_value("generate_description"):
            aspects.append("description")
        if self.normalized_input_value("generate_attributes"):
            aspects.append("attributes")
        if self.normalized_input_value("generate_dialogue_instructions"):
            aspects.append("dialogue_instructions")
        if self.normalized_input_value("generate_example_dialogue"):
            aspects.append("example_dialogue")

        if not aspects:
            raise InputValueError(
                self, "generate_description", "No aspects selected for generation"
            )

        if (
            "example_dialogue" in aspects
            and "name" not in aspects
            and not character_name
        ):
            raise InputValueError(
                self,
                "character_name",
                "Example dialogue generation needs a name - provide "
                "character_name or enable generate_name",
            )

        result = await self.agent.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=aspects,
                name=character_name,
                content=instructions,
                description=description,
                unified=True,
                consolidate=aspects,
            )
        )

        self.set_output_values(
            {
                "state": state,
                "character_name": result.name or character_name,
                "description": result.description or "",
                "attributes": result.attributes or {},
                "dialogue_instructions": result.dialogue_instructions or "",
                "example_dialogue": result.example_dialogue or [],
            }
        )


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
    - character: The character object resolved from the character input
    - context_type: The context type, passed through
    - context_name: The context name, passed through
    - instructions: The instructions, passed through
    - original: The original text, passed through
    """

    _agent_name: ClassVar[str] = "creator"

    class Fields:
        context_type = PropertyField(
            name="context_type",
            description="The type of context to use in generating the text",
            type="str",
            choices=[
                "character attribute",
                "character detail",
                "character dialogue",
                "scene intro",
                "scene intent",
                "scene phase intent",
                "scene type description",
                "scene type instructions",
                "general",
                "list",
                "scene",
                "static history",
                "world context",
            ],
            default="general",
        )
        context_name = PropertyField(
            name="context_name",
            description="The name of the context to use in generating the text",
            type="str",
            default=UNRESOLVED,
        )
        instructions = PropertyField(
            name="instructions",
            description="The instructions to use in generating the text",
            type="str",
            default=UNRESOLVED,
        )
        length = PropertyField(
            name="length",
            description="The length of the text to generate",
            type="int",
            default=100,
        )
        character = PropertyField(
            name="character",
            description="The character to generate the text for",
            type="str",
            default=UNRESOLVED,
        )
        uid = PropertyField(
            name="uid",
            description="The uid to use in generating the text",
            type="str",
            default=UNRESOLVED,
        )
        context_aware = PropertyField(
            name="context_aware",
            description="Whether to use the context in generating the text",
            type="bool",
            default=True,
        )
        history_aware = PropertyField(
            name="history_aware",
            description="Whether to use the history in generating the text",
            type="bool",
            default=True,
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
        self.add_input(
            "generation_options", socket_type="generation_options", optional=True
        )

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
        self.add_output("character", socket_type="character")
        self.add_output("context_type", socket_type="str")
        self.add_output("context_name", socket_type="str")
        self.add_output("instructions", socket_type="str")
        self.add_output("original", socket_type="str")

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

        if not context_name:
            raise InputValueError(self, "context_name", "Context name is not set")

        context = f"{context_type}:{context_name}"

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
            writing_style=generation_options.writing_style
            if generation_options
            else None,
            spices=generation_options.spices if generation_options else None,
            spice_level=generation_options.spice_level if generation_options else 0.0,
            context_aware=context_aware,
            history_aware=history_aware,
        )

        self.set_output_values(
            {
                "state": state,
                "text": text,
                "character": scene.get_character(character),
                "context_type": context_type,
                "context_name": context_name,
                "instructions": instructions,
                "original": original,
            }
        )


@register("agents/creator/GenerateThematicList")
class GenerateThematicList(AgentNode):
    """
    Generates a list of thematic items based on the instructions.
    """

    _agent_name: ClassVar[str] = "creator"

    class Fields:
        instructions = PropertyField(
            name="instructions",
            description="The instructions to use in generating the list",
            type="str",
            default=UNRESOLVED,
        )
        iterations = PropertyField(
            name="iterations",
            description="The number of iterations to use in generating the list - 1 iteration will generate 20 items.",
            type="int",
            default=1,
            step=1,
            min=1,
            max=10,
        )

    def __init__(self, title="Generate Thematic List", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("instructions", socket_type="str", optional=True)

        self.set_property("instructions", UNRESOLVED)
        self.set_property("iterations", 1)

        self.add_output("state")
        self.add_output("list", socket_type="list")

    async def run(self, state: GraphState):
        instructions = self.normalized_input_value("instructions")
        iterations = self.require_number_input("iterations")

        list = await self.agent.generate_thematic_list(instructions, iterations)

        self.set_output_values({"state": state, "list": list})
