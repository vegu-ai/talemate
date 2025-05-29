"""
Editor agent mixin that handles editing of dialogue and narration based on criteria and instructions

Signals:
- agent.editor.revision-analysis.before - sent before the revision analysis is requested
- agent.editor.revision-analysis.after - sent after the revision analysis is requested
"""

from typing import TYPE_CHECKING
import structlog
import uuid
import pydantic
import dataclasses
import re
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
    AgentActionNote,
    AgentTemplateEmission,
)
import talemate.emit.async_signals
from talemate.instance import get_agent
from talemate.emit import emit
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.narrator import NarratorAgentEmission
from talemate.scene_message import CharacterMessage
from talemate.util.dedupe import (
    dedupe_sentences, 
    SimilarityMatch, 
    compile_text_to_sentences, 
    split_sentences_on_comma, 
    dedupe_sentences_from_matches,
    similarity_matches
)
from talemate.util.diff import dmp_inline_diff
from talemate.util import count_tokens
from talemate.prompts import Prompt
from talemate.exceptions import GenerationCancelled
import talemate.game.focal as focal
from talemate.status import LoadingStatus
from talemate.world_state.templates.content import PhraseDetection
from contextvars import ContextVar

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

log = structlog.get_logger()

## CONFIG CONDITIONALS

dedupe_condition = AgentActionConditional(
    attribute="revision.config.revision_method",
    value="dedupe",
)

rewrite_condition = AgentActionConditional(
    attribute="revision.config.revision_method",
    value=["rewrite", "unslop"],
)

detect_bad_prose_condition = AgentActionConditional(
    attribute="revision.config.detect_bad_prose",
    value=True,
)

## CONTEXT

class RevisionContextState(pydantic.BaseModel):
    message_id: int | None = None

revision_disabled_context = ContextVar("revision_disabled", default=False)
revision_context = ContextVar("revision_context", default=RevisionContextState())

class RevisionDisabled:
    def __enter__(self):
        self.token = revision_disabled_context.set(True)

    def __exit__(self, exc_type, exc_value, traceback):
        revision_disabled_context.reset(self.token)

class RevisionContext:
    def __init__(self, message_id: int | None = None):
        self.message_id = message_id

    def __enter__(self):
        self.token = revision_context.set(RevisionContextState(message_id=self.message_id))

    def __exit__(self, exc_type, exc_value, traceback):
        revision_context.reset(self.token)


## SIGNALS

talemate.emit.async_signals.register(
    "agent.editor.revision-analysis.before",
    "agent.editor.revision-analysis.after",
)

## SCHEMAS

class Issues(pydantic.BaseModel):
    repetition: list[SimilarityMatch]
    bad_prose: list[PhraseDetection]
    repetition_instructions: list[str]
    bad_prose_instructions: list[str]
    
    @property
    def issues(self) -> list[str]:
        return self.repetition_instructions + self.bad_prose_instructions

## MIXIN

class RevisionMixin:
    
    """
    Editor agent mixin that handles editing of dialogue and narration based on criteria and instructions
    """
    
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["revision"] = AgentAction(
            enabled=False,
            can_be_disabled=True,
            container=True,
            quick_toggle=True,
            label="Revision",
            icon="mdi-typewriter",
            description="Remove / rewrite content based on criteria and instructions.",
            config={
                "automatic_revision": AgentActionConfig(
                    type="bool",
                    label="Automatic revision",
                    description="Enable / Disable automatic revision.",
                    value=True,
                    quick_toggle=True,
                ),
                "revision_method": AgentActionConfig(
                    type="text",
                    label="Revision method",
                    description="The method to use to revise the text",
                    value="dedupe",
                    choices=[
                        {"label": "Dedupe (Fast and dumb)", "value": "dedupe"},
                        {"label": "Unslop (AI assisted)", "value": "unslop"},
                        {"label": "Rewrite (AI assisted)", "value": "rewrite"},
                    ],
                    note_on_value={
                        "dedupe": AgentActionNote(
                            type="primary",
                            text="This runs after every actor or narrator generation and will attempt to dedupe the text if repetition is detected. Will remove content without substituting it, so may cause sentence structure or logic issues."
                        ),
                        "unslop": AgentActionNote(
                            type="primary",
                            text="This calls 1 additional prompt after every actor or narrator generation and will attempt to remove repetition, purple prose, unnatural dialogue, and over-description. May cause details to be lost."
                        ),
                        "rewrite": AgentActionNote(
                            type="primary",
                            text="Each narrator or actor generation will be checked for repetition and unwanted prose. If issues are found, a rewrite of the problematic part(s) will be attempted. (+2 prompts)"
                        )
                    }
                ),
                "split_on_comma": AgentActionConfig(
                    title="Preferences for rewriting",
                    type="bool",
                    label="Test parts of sentences, split on commas",
                    condition=rewrite_condition,
                    description="If a whole sentence does not trigger a revision issue, split the sentence on commas and test each comma individually.",
                    value=True,
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
                    title="Unwanted prose",
                    type="bool",
                    label="Detect unwanted prose",
                    description="Enable / Disable unwanted prose detection. Will use the writing style's phrase detection to determine unwanted phrases. The scene MUST have a writing style selected.",
                    condition=rewrite_condition,
                    value=False,
                ),
                "detect_bad_prose_threshold": AgentActionConfig(
                    type="number",
                    label="Unwanted prose threshold",
                    condition=rewrite_condition,
                    description="The threshold for detecting unwanted prose when using semantic similarity.",
                    value=0.7,
                    min=0.4,
                    max=1.0,
                    step=0.01,
                ),
                "repetition_detection_method": AgentActionConfig(
                    title="Repetition",
                    type="text",
                    label="Repetition detection method",
                    description="The method to use to detect repetition",
                    value="semantic_similarity",
                    choices=[
                       # fuzzy matching (not ai assisted)
                       # semantic similarity (ai assisted, using memory agent embedding function)
                       {"label": "Fuzzy matching", "value": "fuzzy"},
                       {"label": "Semantic similarity (embeddings)", "value": "semantic_similarity"},
                    ],
                    note_on_value={
                        "semantic_similarity": AgentActionNote(
                            type="warning",
                            text="Uses the memory agent's embedding function to compare the text. Will use batching when available, but has the potential to do A LOT of calls to the embedding model."
                        )
                    }
                ),
                "repetition_threshold": AgentActionConfig(
                    type="number",
                    label="Similarity threshold",
                    description="The similarity threshold for detecting repetition. How similar the text needs to be to be considered repetition.",
                    value=85,
                    min=50,
                    max=100,
                    step=1,
                ),
                "repetition_range": AgentActionConfig(
                    type="number",
                    label="Repetition range",
                    description="Number of message in the history to check against when analyzing repetition.",
                    value=15,
                    min=1,
                    max=100,
                    step=1,
                ),
                "repetition_min_length": AgentActionConfig(
                    type="number",
                    label="Repetition min length",
                    description="The minimum length of a sentence to be considered for repetition checking. (characters, not tokens)",
                    value=15,
                    min=1,
                    max=100,
                    step=1,
                ),
            }
        )
        
    # config property helpers
    
    @property
    def revision_enabled(self):
        return self.actions["revision"].enabled
    
    @property
    def revision_automatic_enabled(self):
        return self.actions["revision"].config["automatic_revision"].value
    
    @property
    def revision_method(self):
        return self.actions["revision"].config["revision_method"].value
    
    @property
    def revision_repetition_detection_method(self):
        return self.actions["revision"].config["repetition_detection_method"].value
    
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
    
    @property
    def revision_detect_bad_prose_threshold(self):
        return self.actions["revision"].config["detect_bad_prose_threshold"].value
    
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
        
        if not self.revision_enabled or not self.revision_automatic_enabled:
            return
        
        try:
            if revision_disabled_context.get():
                log.debug("revision_on_generation: revision disabled through context", emission=emission)
                return
        except LookupError:
            pass
        
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
        
        ctx = revision_context.get()
        
        messages = scene.collect_messages(
            typ=["narrator", "character"],
            max_messages=self.revision_repetition_range,
            start_idx=scene.message_index(ctx.message_id) -1 if ctx.message_id else None
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
            elif self.revision_method == "unslop":
                return await self.revision_unslop(text, character=character, loading_status=loading_status)
        except GenerationCancelled:
            log.warning("revision_revise: generation cancelled", text=text)
            return text
        except Exception as e:
            log.exception("revision_revise: error", error=e)
            return text
        finally:
            loading_status.done()
    
    
    async def _revision_evaluate_semantic_similarity(self, text: str, character: "Character | None" = None) -> list[SimilarityMatch]:
        """
        Detect repetition using semantic similarity
        """
        
        memory_agent = get_agent("memory")
        character_name_prefix = text.startswith(f"{character.name}: ") if character else False
        
        if character_name_prefix:
            text = text[len(character.name) + 2:]
            
        compare_against:list[str] = await self.revision_collect_repetition_range()
        
        text_sentences = compile_text_to_sentences(text)
        
        history_sentences = []
        for sentence in compare_against:
            history_sentences.extend(compile_text_to_sentences(sentence))
        
        min_length = self.revision_repetition_min_length
        
        # strip min length sentences from both lists
        text_sentences = [i for i in text_sentences if len(i[1]) >= min_length]
        history_sentences = [i for i in history_sentences if len(i[1]) >= min_length]
        
        result_matrix = await memory_agent.compare_string_lists(
            [i[1] for i in text_sentences],
            [i[1] for i in history_sentences],
            similarity_threshold=self.revision_repetition_threshold / 100,
        )
        
        similarity_matches = []
        
        for match in result_matrix["similarity_matches"]:
            index_text = match[0]
            index_history = match[1]
            sentence = text_sentences[index_text][1]
            matched = history_sentences[index_history][1]
            similarity_matches.append(SimilarityMatch(
                original=str(sentence),
                matched=str(matched),
                similarity=round(match[2] * 100, 2),
                left_neighbor=text_sentences[index_text - 1][1] if index_text > 0 else None,
                right_neighbor=text_sentences[index_text + 1][1] if index_text < len(text_sentences) - 1 else None,
            ))
        
        return list(set(similarity_matches))
        
    
    async def _revision_evaluate_fuzzy_similarity(self, text: str, character: "Character | None" = None) -> list[SimilarityMatch]:
        """
        Detect repetition using fuzzy matching and dedupe
        
        Will return a tuple with the deduped text and the deduped text
        """
            
        compare_against:list[str] = await self.revision_collect_repetition_range()
        
        matches = []
        
        for old_text in compare_against:
            matches.extend(
                similarity_matches(
                    text, 
                    old_text, 
                    similarity_threshold=self.revision_repetition_threshold,
                    min_length=self.revision_repetition_min_length,
                    split_on_comma=self.revision_split_on_comma
                )
            )

            
        return list(set(matches))
    
    async def revision_dedupe(self, text: str, character: "Character | None" = None) -> str:
        """
        Revise the text by deduping
        """

        original_text = text
        character_name_prefix = text.startswith(f"{character.name}: ") if character else False
        
        if self.revision_repetition_detection_method == "fuzzy":
            matches = await self._revision_evaluate_fuzzy_similarity(text, character)
        elif self.revision_repetition_detection_method == "semantic_similarity":
            matches = await self._revision_evaluate_semantic_similarity(text, character)
        
        deduped = []
        def on_dedupe(match: SimilarityMatch):
            deduped.append({
                "text_a": match.original,
                "text_b": match.matched,
                "similarity": match.similarity
            })
        
        text = dedupe_sentences_from_matches(text, matches, on_dedupe=on_dedupe)

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
        try:
            sentences = compile_text_to_sentences(text)
            identified = []
            
            writing_style = self.scene.writing_style
            
            if not writing_style or not writing_style.phrases:
                return []
            
            if self.revision_split_on_comma:
                sentences = split_sentences_on_comma([sentence[0] for sentence in sentences])
            
            # collect all phrases by method
            semantic_similarity_phrases = []
            regex_phrases = []
            
            for phrase in writing_style.phrases:
                if not phrase.phrase or not phrase.instructions or not phrase.active:
                    continue
                
                if phrase.match_method == "semantic_similarity":
                    semantic_similarity_phrases.append(phrase)
                elif phrase.match_method == "regex":
                    regex_phrases.append(phrase)
            
            # evaulate regex phrases first
            for phrase in regex_phrases:
                for sentence in sentences:
                    identified.extend(await self._revision_detect_bad_prose_regex(sentence, phrase))
                    
            # next evaulate semantic similarity phrases at once
            identified.extend(
                await self._revision_detect_bad_prose_semantic_similarity(sentences, semantic_similarity_phrases)
            )
            return identified
        except Exception as e:
            log.error("revision_detect_bad_prose: error", error=e)
            return []
    
    async def _revision_detect_bad_prose_semantic_similarity(self, sentences: list[str], phrases: list[PhraseDetection]) -> list[dict]:
        """
        Detect bad prose in the text using semantic similarity
        """
                
        memory_agent = get_agent("memory")
        
        if not memory_agent:
            return []
        
        """
        Compare two lists of strings using the current embedding function without touching the database.

        Returns a dictionary with:
            - 'cosine_similarity_matrix': np.ndarray of shape (len(list_a), len(list_b))
            - 'euclidean_distance_matrix': np.ndarray of shape (len(list_a), len(list_b))
            - 'similarity_matches': list of (i, j, score) (filtered if threshold set, otherwise all)
            - 'distance_matches': list of (i, j, distance) (filtered if threshold set, otherwise all)
        """
        threshold = self.revision_detect_bad_prose_threshold
        
        phrase_strings = [phrase.phrase for phrase in phrases]
        
        num_comparisons = len(sentences) * len(phrase_strings)
        
        log.debug("revision_detect_bad_prose: comparing sentences to phrases", num_comparisons=num_comparisons)
        
        result_matrix = await memory_agent.compare_string_lists(
            sentences, 
            phrase_strings, 
            similarity_threshold=threshold
        )
        
        result = []
        
        for match in result_matrix["similarity_matches"]:
            sentence = sentences[match[0]]
            phrase = phrases[match[1]]
            result.append({
                "phrase": sentence,
                "instructions": phrase.instructions,
                "reason": "Unwanted phrase found",
                "matched": phrase.phrase,
                "method": "semantic_similarity",
                "similarity": match[2],
            })
            
        return result
        
    async def _revision_detect_bad_prose_regex(self, sentence: str, phrase: PhraseDetection) -> list[dict]:
        """
        Detect bad prose in the text using regex
        """
        if str(phrase.classification).lower() != "unwanted":
            return []
        
        pattern = re.compile(phrase.phrase)
        if not pattern.search(sentence, re.IGNORECASE):
            return []
        
        return [
            {
                "phrase": sentence,
                "instructions": phrase.instructions,
                "reason": "Unwanted phrase found",
                "matched": phrase.phrase,
                "method": "regex",
            }
        ]
    
    async def revision_rewrite(self, text: str, character: "Character | None" = None, loading_status: LoadingStatus = None):
        """
        Revise the text by rewriting
        """
        original_text = text
        writing_style = self.scene.writing_style
        detect_bad_prose = self.revision_detect_bad_prose_enabled and writing_style
        
        if loading_status:
            loading_status.max_steps = 2
        
        issues = []
        deduped = []
        repetition_matches = []
        bad_prose_identified = []
        character_name_prefix = text.startswith(f"{character.name}: ") if character else False
        if character_name_prefix:
            text = text[len(character.name) + 2:]
        
        # Step 1 - Detect repetition
        if self.revision_repetition_detection_method == "fuzzy":
            repetition_matches = await self._revision_evaluate_fuzzy_similarity(text, character)
        elif self.revision_repetition_detection_method == "semantic_similarity":
            repetition_matches = await self._revision_evaluate_semantic_similarity(text, character)
            
        for match in repetition_matches:
            deduped.append({
                "text_a": match.original,
                "text_b": match.matched,
                "similarity": match.similarity
            })
            issues.append(f"Repetition: `{match.original}` -> `{match.matched}` (similarity: {match.similarity})")
        
        # Step 2 - Detect bad prose
        if detect_bad_prose:
            bad_prose_identified = await self.revision_detect_bad_prose(text)
            for identified in bad_prose_identified:
                issues.append(f"Bad prose: `{identified['phrase']}` (reason: {identified['reason']}, matched: {identified['matched']}, instructions: {identified['instructions']})")
            log.debug("revision_rewrite: bad_prose_identified", bad_prose_identified=bad_prose_identified)
            
        # Step 3 - Check if we have enough issues to warrant a rewrite
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
        
        # Step 4 - Rewrite
        token_count = count_tokens(text)
        
        log.debug("revision_rewrite: token_count", token_count=token_count)
        
        if loading_status:
            loading_status("Editor - Issues identified, analyzing text...")
           
        template_vars = {
            "text": text,
            "character": character,
            "scene": self.scene,
            "response_length": token_count,
            "max_tokens": self.client.max_token_length,
            "repetition": deduped,
            "bad_prose": bad_prose_identified,
        }
        
        emission = AgentTemplateEmission(agent=self, template_vars=template_vars)
        await talemate.emit.async_signals.get("agent.editor.revision-analysis.before").send(
            emission
        )
            
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
                "dynamic_instructions": emission.dynamic_instructions,
            },
        )
        
        emission.response = analysis
        await talemate.emit.async_signals.get("agent.editor.revision-analysis.after").send(
            emission
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
                "repetition_threshold": self.revision_repetition_threshold,
                "repetition_range": self.revision_repetition_range,
                "repetition_min_length": self.revision_repetition_min_length,
                "split_on_comma": self.revision_split_on_comma,
                "min_issues": self.revision_min_issues,
                "detect_bad_prose": self.revision_detect_bad_prose_enabled,
                "detect_bad_prose_threshold": self.revision_detect_bad_prose_threshold,
            },
            color="highlight4",
        )
        
        if character_name_prefix and not revision.startswith(f"{character.name}: "):
            revision = f"{character.name}: {revision}"
            
        return revision

    async def revision_unslop(
        self, 
        text: str, 
        character: "Character | None" = None, 
        response_length: int = 768, 
        loading_status: LoadingStatus = None,
        scene_analysis: str = None
    ) -> str:
        """
        Unslop the text
        """
        
        original_text = text
        
        character_name_prefix = text.startswith(f"{character.name}: ") if character else False
        if character_name_prefix:
            text = text[len(character.name) + 2:]
        
        issues = await self.collect_issues(text, character)
        
        log.debug("revision_unslop: issues", issues=issues)

        summarizer = get_agent("summarizer")
        scene_analysis = await summarizer.get_cached_analysis(
            "conversation" if character else "narration"
        )
        
        response = await Prompt.request(
            "editor.unslop",
            self.client,
            "edit_768",
            vars={
                "text": text,
                "scene_analysis": scene_analysis,
                "character": character,
                "scene": self.scene,
                "response_length": response_length,
                "max_tokens": self.client.max_token_length,
                "repetition": issues.repetition,
                "bad_prose": issues.bad_prose,
            },
            dedupe_enabled=False,
        )
        
        # extract <FIX>...</FIX>
        
        if "<FIX>" not in response:
            log.error("revision_unslop: no <FIX> found in response", response=response)
            return original_text

        fix = response.split("<FIX>", 1)[1]
        
        if "</FIX>" in fix:
            fix = fix.split("</FIX>", 1)[0]
        elif "<" in fix:
            log.error("revision_unslop: no </FIX> found in response, but other tags found, aborting.", response=response)
            return original_text
        
        if not fix:
            log.error("revision_unslop: no fix found", response=response)
            return original_text
        
        fix = fix.strip()
        
        # send diff to user
        diff = dmp_inline_diff(text, fix)
        await self.emit_message(
            "Unslop",
            message=[
                {"subtitle": "Issues", "content": issues.issues},
                {"subtitle": "Original", "content": text},
                {"subtitle": "Changes", "content": diff, "process": "diff"},
            ],
            meta={
                "action": "revision_unslop",
            },
            color="highlight4",
        )
        
        if character_name_prefix and not fix.startswith(f"{character.name}: "):
            fix = f"{character.name}: {fix}"
            
        return fix
        
    async def collect_issues(self, text: str, character: "Character | None" = None) -> Issues:
        """
        Collect issues from the text
        """
        writing_style = self.scene.writing_style
        detect_bad_prose = self.revision_detect_bad_prose_enabled and writing_style
        
        repetition_issues = []
        repetition_instructions = []
        bad_prose_instructions = []
        bad_prose = []
        
        # Step 1 - Detect repetition
        if self.revision_repetition_detection_method == "fuzzy":
            repetition_matches = await self._revision_evaluate_fuzzy_similarity(text, character)
        elif self.revision_repetition_detection_method == "semantic_similarity":
            repetition_matches = await self._revision_evaluate_semantic_similarity(text, character)
            
        for match in repetition_matches:
            repetition_instructions.append({
                "text_a": match.original,
                "text_b": match.matched,
                "similarity": match.similarity
            })
            repetition_issues.append(f"Repetition: `{match.original}` -> `{match.matched}` (similarity: {match.similarity})")
            
        # Step 2 - Detect bad prose
        if detect_bad_prose:
            bad_prose = await self.revision_detect_bad_prose(text)
            for identified in bad_prose:
                bad_prose_instructions.append(f"Bad prose: `{identified['phrase']}` (reason: {identified['reason']}, matched: {identified['matched']}, instructions: {identified['instructions']})")
        
        
        return Issues(
            repetition=repetition_matches,
            bad_prose=bad_prose,
            repetition_instructions=repetition_instructions,
            bad_prose_instructions=bad_prose_instructions,
        )