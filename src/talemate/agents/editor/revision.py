from typing import TYPE_CHECKING
import structlog
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig
)
import talemate.emit.async_signals
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.narrator import NarratorAgentEmission
from talemate.scene_message import CharacterMessage
from talemate.util.dedupe import dedupe_sentences

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

log = structlog.get_logger()

class RevisionMixin:
    
    """
    Editor agent mixin that handles editing of dialogue and narration based on criteria and instructions
    """
    
    @classmethod
    def add_actions(cls, editor):
        editor.actions["revision"] = AgentAction(
            enabled=False,
            can_be_disabled=True,
            container=True,
            quick_toggle=True,
            label="Revision",
            icon="mdi-typewriter",
            description="Remove / rewrite dialogue and narration based on criteria and instructions",
            config={
                "revision_method": AgentActionConfig(
                    type="text",
                    label="Revision method",
                    description="The method to use to revise the text",
                    value="dedupe",
                    choices=[
                        {"label": "Dedupe (Fast)", "value": "dedupe"},
                        {"label": "Rewrite (AI assisted, Slower)", "value": "rewrite"},
                    ]
                ),
                "repetition_threshold": AgentActionConfig(
                    type="number",
                    label="Repetition threshold",
                    description="The similarity threshold for fixing repetition (%)",
                    value=0.9,
                    min=0,
                    max=1,
                    step=0.01
                ),
                "repetition_range": AgentActionConfig(
                    type="number",
                    label="Repetition range",
                    description="The range of text to revise (number of messages to go back)",
                    value=15,
                    min=1,
                    max=100,
                    step=1
                ),
            }
        )
        
    # config property helpers
    
    @property
    def revision_enabled(self):
        return self.actions["revision"].enabled
    
    @property
    def revision_method(self):
        return self.actions["revision"].config["revision_method"].value
    
    @property
    def revision_repetition_threshold(self):
        return self.actions["revision"].config["repetition_threshold"].value
    
    @property
    def revision_repetition_range(self):
        return self.actions["revision"].config["repetition_range"].value
    
    # signal connect
    
    def connect(self, scene):
        talemate.emit.async_signals.get("agent.conversation.generated").connect(
            self.revision_on_generation
        )
        talemate.emit.async_signals.get("agent.narrator.generated").connect(
            self.revision_on_generation
        )
        # connect to the super class AFTER so these run first.
        super().connect(scene)
        
        
    async def revision_on_generation(self, emission: ConversationAgentEmission | NarratorAgentEmission):
        """
        Called when a conversation or narrator message is generated
        """
        
        if not self.revision_enabled:
            return
        
        log.info("revise generation", emission=emission)

        edited = []
        for text in emission.generation:
            text = await self.revision_revise(text, character=getattr(emission, "character", None))
            edited.append(text)
        emission.generation = edited

    # helpers
    
    async def revision_collect_repetition_range(self) -> list[str]:
        """
        Collect the range of text to revise against by going through the scene's
        history and collecting narrator and character messages
        """
        
        scene:"Scene" = self.scene
        
        messages = scene.collect_messages(
            typ=["narrator", "character"],
            max_messages=self.revision_repetition_range
        )
        
        return_messages = []
        
        for message in messages:
            if isinstance(message, CharacterMessage):
                return_messages.append(message.without_name)
            else:
                return_messages.append(message.message)
                
        return return_messages

    # actions
    
    @set_processing
    async def revision_revise(self, text: str, character: "Character | None" = None):
        """
        Revise the text based on the revision method
        """
        
        if self.revision_method == "dedupe":
            return await self.revision_dedupe(text, character=character)
        elif self.revision_method == "rewrite":
            return await self.revision_rewrite(text, character=character)
    
    
    async def revision_dedupe(self, text: str, character: "Character | None" = None):
        """
        Revise the text by deduping
        """

        original_text = text
        
        character_name_prefix = text.startswith(f"{character.name}: ") if character else False
        
        if character_name_prefix:
            # remove the character name prefix
            text = text[len(character.name) + 2:]
        
        compare_against:list[str] = await self.revision_collect_repetition_range()
        
        for old_text in compare_against:
            text = dedupe_sentences(text, old_text, self.revision_repetition_threshold * 100, debug=True)
        
        log.debug("deduped text", text=text)
        
        if not text:
            log.warning("no text after dedupe", original_text=original_text)
            return original_text
        
        if character_name_prefix:
            text = f"{character.name}: {text}"
            
        return text
    
    async def revision_rewrite(self, text: str, character: "Character | None" = None):
        """
        Revise the text by rewriting
        """
        pass