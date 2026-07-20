import structlog
from typing import ClassVar, TYPE_CHECKING
from talemate.game.engine.nodes.core import (
    GraphState,
    PropertyField,
)
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode, AgentNode

if TYPE_CHECKING:
    from talemate.agents.editor import EditorAgent

log = structlog.get_logger("talemate.game.engine.nodes.agents.editor")


@register("agents/editor/Settings")
class EditorSettings(AgentSettingsNode):
    """
    Base node to render editor agent settings.
    """

    _agent_name: ClassVar[str] = "editor"

    def __init__(self, title="Editor Settings", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/editor/CleanUpUserInput")
class CleanUpUserInput(AgentNode):
    """
    Cleans up user input via the editor agent, fixing exposition
    formatting (quotes for speech, asterisks for narration) according to
    the editor's formatting settings. Input starting with a command prefix
    (!, @, /) is never edited, and cleanup is skipped entirely when the
    editor's fix-user-input setting is disabled - unless force is set.

    Inputs:

    - user_input: The user input text to clean up
    - as_narration: Whether to treat the input as narration instead of speech

    Properties:

    - force: Clean up even when the editor's fix-user-input setting is disabled

    Outputs:

    - cleaned_user_input: The cleaned up user input
    """

    _agent_name: ClassVar[str] = "editor"

    class Fields:
        force = PropertyField(
            name="force",
            description="Force clean up",
            type="bool",
            default=False,
        )

    def __init__(self, title="Clean Up User Input", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("user_input", socket_type="str")
        self.add_input("as_narration", socket_type="bool")

        self.set_property("force", False)

        self.add_output("cleaned_user_input", socket_type="str")

    async def run(self, state: GraphState):
        editor: "EditorAgent" = self.agent
        user_input = self.get_input_value("user_input")
        force = self.get_property("force")
        as_narration = self.get_input_value("as_narration")
        cleaned_user_input = await editor.cleanup_user_input(
            user_input, as_narration=as_narration, force=force
        )
        self.set_output_values(
            {
                "cleaned_user_input": cleaned_user_input,
            }
        )


@register("agents/editor/CleanUpNarration")
class CleanUpNarration(AgentNode):
    """
    Cleans up narration text via the editor agent, stripping partial
    sentences and fixing exposition formatting according to the editor's
    formatting settings (skipped unless the narrator fix-exposition
    setting is enabled or force is set).

    Inputs:

    - narration: The narration text to clean up

    Properties:

    - force: Clean up even when the editor's fix-exposition setting is disabled

    Outputs:

    - cleaned_narration: The cleaned up narration
    """

    _agent_name: ClassVar[str] = "editor"

    class Fields:
        force = PropertyField(
            name="force",
            description="Force clean up",
            type="bool",
            default=False,
        )

    def __init__(self, title="Clean Up Narration", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("narration", socket_type="str")
        self.set_property("force", False)
        self.add_output("cleaned_narration", socket_type="str")

    async def run(self, state: GraphState):
        editor: "EditorAgent" = self.agent
        narration = self.get_input_value("narration")
        force = self.get_property("force")
        cleaned_narration = await editor.clean_up_narration(narration, force=force)
        self.set_output_values(
            {
                "cleaned_narration": cleaned_narration,
            }
        )


@register("agents/editor/CleanUpCharacterMessage")
class CleanUpCharacterMessage(AgentNode):
    """
    Cleans up a character's dialogue text via the editor agent: fixes
    exposition formatting (per the editor's formatting settings), cleans
    up stray dialogue from other characters, strips partial sentences and
    balances quotation marks.

    Inputs:

    - text: The character message text to clean up
    - character: The character the message belongs to

    Properties:

    - force: Fix exposition even when the editor's fix-exposition setting
      is disabled or the character is a player character

    Outputs:

    - cleaned_character_message: The cleaned up character message
    """

    _agent_name: ClassVar[str] = "editor"

    class Fields:
        force = PropertyField(
            name="force",
            description="Force clean up",
            type="bool",
            default=False,
        )

    def __init__(self, title="Clean Up Character Message", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("text", socket_type="str")
        self.add_input("character", socket_type="character")
        self.set_property("force", False)
        self.add_output("cleaned_character_message", socket_type="str")

    async def run(self, state: GraphState):
        editor: "EditorAgent" = self.agent
        text = self.get_input_value("text")
        force = self.get_property("force")
        character = self.get_input_value("character")
        cleaned_character_message = await editor.cleanup_character_message(
            text, character, force=force
        )
        self.set_output_values(
            {
                "cleaned_character_message": cleaned_character_message,
            }
        )
