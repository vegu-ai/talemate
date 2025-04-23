from typing import TYPE_CHECKING
import structlog
import uuid
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
)
import talemate.emit.async_signals
from talemate.emit import emit
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.narrator import NarratorAgentEmission
from talemate.scene_message import CharacterMessage
from talemate.util.dedupe import dedupe_sentences, SimilarityMatch
from talemate.util import count_tokens
from talemate.prompts import Prompt
from talemate.exceptions import GenerationCancelled
import talemate.game.focal as focal
from talemate.status import LoadingStatus, set_loading

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

log = structlog.get_logger()

dedupe_condition = AgentActionConditional(
    attribute="revision.config.revision_method",
    value="dedupe",
)

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
                        {"label": "Dedupe (Fast and dumb)", "value": "dedupe"},
                        {"label": "Rewrite (AI assisted, slower and less dumb, propbably)", "value": "rewrite"},
                    ]
                ),
                "repetition_threshold": AgentActionConfig(
                    type="number",
                    label="Similarity threshold",
                    description="The similarity threshold for detecting repetition (percentage)",
                    value=0.9,
                    min=0.5,
                    max=1,
                    step=0.01,
                ),
                "repetition_range": AgentActionConfig(
                    type="number",
                    label="Repetition range",
                    description="Number of message in the backlog to check against when analyzing repetition.",
                    value=15,
                    min=1,
                    max=100,
                    step=1,
                ),
                "repetition_min_length": AgentActionConfig(
                    type="number",
                    label="Repetition min length",
                    description="The minimum length of a sentence to be considered for repetition checking.",
                    value=20,
                    min=1,
                    max=100,
                    step=1,
                )
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
    
    @property
    def revision_repetition_min_length(self):
        return self.actions["revision"].config["repetition_min_length"].value
    
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
        
        try:
            if self.revision_method == "dedupe":
                return await self.revision_dedupe(text, character=character)
            elif self.revision_method == "rewrite":
                return await self.revision_rewrite(text, character=character)
        except GenerationCancelled:
            log.warning("revision_revise: generation cancelled", text=text)
            return text
        except Exception as e:
            log.error("revision_revise: error", error=e)
            return text
    
    
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
        
        deduped = []
        
        def on_dedupe(match: SimilarityMatch):
            deduped.append({
                "text_a": match.original,
                "text_b": match.matched,
                "similarity": match.similarity
            })
        
        for old_text in compare_against:
            text = dedupe_sentences(
                text, 
                old_text, 
                self.revision_repetition_threshold * 100, 
                on_dedupe=on_dedupe,
                min_length=self.revision_repetition_min_length
            )
        
        length_diff_percentage = 0
        
        if deduped:
            length_diff_percentage = round((len(original_text) - len(text)) / len(original_text) * 100, 2)
            log.debug("revision_dedupe: deduped text", text=text, length_diff_percentage=length_diff_percentage)
        
        if not text:
            log.warning("revision_dedupe: no text after dedupe, reverting to original text", original_text=original_text)
            emit("agent_message", 
                message=f"No text remained after dedupe, reverting to original text - similarity threshold is likely too low.",
                data={
                    "uuid": str(uuid.uuid4()),
                    "agent": "editor",
                    "header": "Aborted dedupe",
                    "color": "red",
                }, 
                meta={
                    "action": "revision_dedupe",
                    "threshold": self.revision_repetition_threshold,
                    "range": self.revision_repetition_range,
                },
                websocket_passthrough=True
            )
            return original_text
        
        if character_name_prefix:
            text = f"{character.name}: {text}"
            
        for dedupe in deduped:
            text_a = dedupe['text_a']
            text_b = dedupe['text_b']
            
            message = f"{text_a} -> {text_b}"
            emit("agent_message", 
                message=message,
                data={
                    "uuid": str(uuid.uuid4()),
                    "agent": "editor",
                    "header": "Removed repetition",
                    "color": "highlight4",
                }, 
                meta={
                    "action": "revision_dedupe",
                    "similarity": dedupe['similarity'],
                    "threshold": self.revision_repetition_threshold,
                    "range": self.revision_repetition_range,
                },
                websocket_passthrough=True
            )
            
        return text
    
    async def revision_rewrite(self, text: str, character: "Character | None" = None):
        """
        Revise the text by rewriting
        """
        
        original_text = text

        # Step 1 - Find repetition
        character_name_prefix = text.startswith(f"{character.name}: ") if character else False
        
        if character_name_prefix:
            text = text[len(character.name) + 2:]
            
        compare_against:list[str] = await self.revision_collect_repetition_range()
        
        reasons = []
        deduped = []
        
        def on_dedupe(match: SimilarityMatch):
            deduped.append({
                "text_a": match.original,
                "text_b": match.matched,
                "similarity": match.similarity
            })
            reasons.append(f"Repetition: {match.original} -> {match.matched} (similarity: {match.similarity})")
            
        for old_text in compare_against:
            dedupe_sentences(
                text, 
                old_text, 
                self.revision_repetition_threshold * 100, 
                on_dedupe=on_dedupe,
                min_length=self.revision_repetition_min_length
            )
            
        log.debug("revision_rewrite: deduped", deduped=deduped)
            
        if not deduped:
            # No repetition found, return original text
            return original_text
        
        
        loading_status = LoadingStatus(2, cancellable=True)
        
        # Step 2 - Rewrite
        token_count = count_tokens(text)
        
        log.debug("revision_rewrite: token_count", token_count=token_count)
        
        loading_status("Editor - Issues identified, analyzing text...")
        analysis = await Prompt.request(
            "editor.revision-analysis",
            self.client,
            f"edit_768",
            vars={
                "text": text,
                "character": character,
                "scene": self.scene,
                "response_length": token_count,
                "max_tokens": self.client.max_token_length,
                "repetition": deduped,
            },
        )
        
        async def rewrite_text(text:str) -> str:
            return text
            
        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="rewrite_text",
                    arguments=[
                        focal.Argument(name="text", type="str", preserve_newlines=True),
                    ],
                    fn=rewrite_text,
                    multiple=False,
                ),
            ],
            max_calls=1,
            retries=1,
            scene=self.scene,
            analysis=analysis,
            text=text,
        )
        
        loading_status("Editor - Rewriting text...")
        try:
            await focal_handler.request(
                "editor.revision-rewrite",
            )
                
            try:
                revision = focal_handler.state.calls[0].result
            except Exception as e:
                log.error("revision_rewrite: error", error=e)
                return original_text

            await self.emit_message(
                "Rewrite",
                message=[
                    {"subtitle": "Reasons", "content": reasons},
                    {"subtitle": "Original", "content": text},
                    {"subtitle": "Revision", "content": revision},
                ],
                meta={
                    "action": "revision_rewrite",
                    "threshold": self.revision_repetition_threshold,
                    "range": self.revision_repetition_range,
                },
                color="highlight4",
            )
            
            if character_name_prefix:
                revision = f"{character.name}: {revision}"
                
            return revision
        finally:
            loading_status.done()
