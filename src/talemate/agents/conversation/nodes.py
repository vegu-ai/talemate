import structlog
from typing import TYPE_CHECKING, ClassVar
from talemate.game.engine.nodes.core import GraphState, UNRESOLVED
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentNode, AgentSettingsNode
from talemate.context import active_scene
from talemate.client.context import ConversationContext, ClientContext

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

log = structlog.get_logger("talemate.game.engine.nodes.agents.conversation")


@register("agents/conversation/Settings")
class ConversationSettings(AgentSettingsNode):
    """
    Base node to render conversation agent settings.
    """

    _agent_name: ClassVar[str] = "conversation"

    def __init__(self, title="Conversation Settings", **kwargs):
        super().__init__(title=title, **kwargs)


@register("agents/conversation/Generate")
class GenerateConversation(AgentNode):
    """
    Generate a conversation between two characters
    """

    _agent_name: ClassVar[str] = "conversation"

    def __init__(self, title="Generate Conversation", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="character")
        self.add_input("instruction", socket_type="str", optional=True)

        self.set_property("trigger_conversation_generated", True)

        self.add_output("state")
        self.add_output("generated", socket_type="str")
        self.add_output("message", socket_type="message_object")
        self.add_output("character", socket_type="character")
        self.add_output("instruction", socket_type="str")

    async def run(self, state: GraphState):
        character: "Character" = self.get_input_value("character")
        scene: "Scene" = active_scene.get()
        instruction = self.get_input_value("instruction")
        trigger_conversation_generated = self.get_property(
            "trigger_conversation_generated"
        )

        other_characters = [c.name for c in scene.characters if c != character]

        conversation_context = ConversationContext(
            talking_character=character.name,
            other_characters=other_characters,
        )

        if instruction == UNRESOLVED:
            instruction = None

        with ClientContext(conversation=conversation_context):
            messages = await self.agent.converse(
                character.actor,
                instruction=instruction,
                emit_signals=trigger_conversation_generated,
            )

            message = messages[0]

        self.set_output_values(
            {
                "generated": message.message,
                "message": message,
                "character": character,
                "instruction": instruction,
                "state": self.get_input_value("state"),
            }
        )
