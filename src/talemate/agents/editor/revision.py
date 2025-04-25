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
from talemate.util.diff import dmp_inline_diff
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

rewrite_condition = AgentActionConditional(
    attribute="revision.config.revision_method",
    value="rewrite",
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
                    value=90,
                    min=40,
                    max=100,
                    step=1,
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
                    value=15,
                    min=1,
                    max=100,
                    step=1,
                ),
                "split_on_comma": AgentActionConfig(
                    type="bool",
                    label="Test parts of sentences, split on commas",
                    condition=rewrite_condition,
                    description="If a whole sentence does not trigger a repetition, split the sentence on commas and test each comma individually.",
                    value=False,
                ),
                "min_issues": AgentActionConfig(
                    type="number",
                    label="Minimum issues",
                    condition=rewrite_condition,
                    description="The minimum number of issues to trigger a rewrite.",
                    value=1,
                    min=1,
                    max=10,
                    step=1,
                ),
                "detect_bad_prose": AgentActionConfig(
                    type="bool",
                    label="Detect unwanted prose",
                    description="Enable / Disable unwanted prose detection. Will use the writing style selected in the scene settings to determine unwanted phrases.",
                    condition=rewrite_condition,
                    value=False,
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
    
    @property
    def revision_repetition_min_length(self):
        return self.actions["revision"].config["repetition_min_length"].value
    
    @property
    def revision_split_on_comma(self):
        return self.actions["revision"].config["split_on_comma"].value
    
    @property
    def revision_min_issues(self):
        return self.actions["revision"].config["min_issues"].value
    
    @property
    def revision_detect_bad_prose_enabled(self):
        return self.actions["revision"].config["detect_bad_prose"].value
    
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
        loading_status = LoadingStatus(0, cancellable=True)
        
        try:
            if self.revision_method == "dedupe":
                return await self.revision_dedupe(text, character=character)
            elif self.revision_method == "rewrite":
                return await self.revision_rewrite(text, character=character, loading_status=loading_status)
        except GenerationCancelled:
            log.warning("revision_revise: generation cancelled", text=text)
            return text
        except Exception as e:
            log.error("revision_revise: error", error=e)
            return text
        finally:
            loading_status.done()
    
    
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
                self.revision_repetition_threshold, 
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
    
    async def revision_detect_bad_prose(self, text: str) -> list[dict]:
        """
        Detect bad prose in the text
        """
        identified = []
        
        async def identify(phrase: str = None, reason: str = None, instructions: str = None, **kwargs):
            identified.append({
                "phrase": phrase,
                "reason": reason,
                "instructions": instructions,
            })
        
        focal_handler = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="identify",
                    arguments=[
                        focal.Argument(name="phrase", type="str"),
                        focal.Argument(name="reason", type="str"),
                        focal.Argument(name="instructions", type="str"),
                    ],
                    fn=identify,
                    multiple=True,
                ),
            ],
            max_calls=5,
            retries=0,
            scene=self.scene,
            text=text,
            instructions=self.scene.writing_style.instructions,
        )
        
        await focal_handler.request(
            "editor.revision-detection",
        )
        
        return identified
    
    async def revision_rewrite(self, text: str, character: "Character | None" = None, loading_status: LoadingStatus = None):
        """
        Revise the text by rewriting
        """
        original_text = text
        writing_style = self.scene.writing_style
        detect_bad_prose = self.revision_detect_bad_prose_enabled and writing_style
        
        if loading_status:
            loading_status.max_steps = 2
        
        # Step 1 - Find repetition
        character_name_prefix = text.startswith(f"{character.name}: ") if character else False
        
        if character_name_prefix:
            text = text[len(character.name) + 2:]
            
        compare_against:list[str] = await self.revision_collect_repetition_range()
        
        issues = []
        deduped = []
        bad_prose_identified = []
        
        def on_dedupe(match: SimilarityMatch):
            deduped.append({
                "text_a": match.original,
                "text_b": match.matched,
                "similarity": match.similarity
            })
            issues.append(f"Repetition: {match.original} -> {match.matched} (similarity: {match.similarity})")
            
        for old_text in compare_against:
            dedupe_sentences(
                text, 
                old_text, 
                self.revision_repetition_threshold, 
                on_dedupe=on_dedupe,
                min_length=self.revision_repetition_min_length,
                split_on_comma=self.revision_split_on_comma
            )
            
        log.debug("revision_rewrite: deduped", deduped=deduped)
            
        if detect_bad_prose:
            bad_prose_identified = await self.revision_detect_bad_prose(text)
            for identified in bad_prose_identified:
                issues.append(f"Bad prose: `{identified['phrase']}` (reason: {identified['reason']}, instructions: {identified['instructions']})")
            log.debug("revision_rewrite: bad_prose_identified", bad_prose_identified=bad_prose_identified)
            
        if not issues:
            # No repetition found, return original text
            return original_text
        
        num_issues = len(issues)
        
        if num_issues < self.revision_min_issues:
            log.debug("revision_rewrite: not enough issues found, returning original text", issues=num_issues, min_issues=self.revision_min_issues)
            # Not enough issues found, return original text
            await self.emit_message(
                "Aborted rewrite",
                message=[
                    {"subtitle": "Issues", "content": issues},
                    {"subtitle": "Message", "content": f"Not enough issues found, returning original text - minimum issues is {self.revision_min_issues}. Found {num_issues} issues."},
                ],
                color="orange",
            )
            return original_text
        
        
        # Step 2 - Rewrite
        token_count = count_tokens(text)
        
        log.debug("revision_rewrite: token_count", token_count=token_count)
        
        if loading_status:
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
                "bad_prose": bad_prose_identified,
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
        
        if loading_status:
            loading_status("Editor - Rewriting text...")

        await focal_handler.request(
            "editor.revision-rewrite",
        )
            
        try:
            revision = focal_handler.state.calls[0].result
        except Exception as e:
            log.error("revision_rewrite: error", error=e)
            return original_text
        
        diff = dmp_inline_diff(text, revision)
        await self.emit_message(
            "Rewrite",
            message=[
                {"subtitle": "Issues", "content": issues},
                {"subtitle": "Original", "content": text},
                {"subtitle": "Changes", "content": diff, "process": "diff"},
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
