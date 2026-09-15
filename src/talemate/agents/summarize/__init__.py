from __future__ import annotations

from talemate.knowledge.processing import evidence_writer

import re
from dataclasses import dataclass

import structlog
from typing import TYPE_CHECKING, Literal
import talemate.emit.async_signals
import talemate.util as util
from talemate.events import HistoryEvent
from talemate.prompts import Prompt
from .response_specs import SUMMARY_SPEC, SUMMARY_WITH_FACTS_SPEC, CHUNK_CLEAN_SPEC
from talemate.scene_message import (
    CharacterTransitionMessage,
    DirectorMessage,
    TimePassageMessage,
    ContextInvestigationMessage,
    ReinforcementMessage,
)
from talemate.world_state.templates import GenerationOptions
from talemate.client import ClientBase
from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentEmission,
    AgentTemplateEmission,
    RagBuildSubInstructionEmission,
    optimize_prompt_caching_action,
    set_processing,
)
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin

from talemate.history import (
    SPAN_LINE_EXCLUDED_TYPES,
    ArchiveEntry,
    HistoryEntry,
    render_span,
    resolve_history_entry,
    span_bindings,
)
from talemate.knowledge.timeline import message_times
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.presence import presence_differs, span_presence
from talemate.knowledge.facts import (
    SpanLine,
    drop_facts_for_entries,
    parse_facts,
    previous_facts,
    store_facts,
    verify_restatements,
)
from talemate.knowledge.topics import refresh_topics
from talemate.knowledge.schema import FactsStatus

from .analyze_scene import SceneAnalyzationMixin
from .context_history import ContextHistoryMixin
from .layered_history import LayeredHistoryMixin
from .tts_utils import TTSUtilsMixin
from .perceptions import PerceptionMixin
from .audience_summaries import AudienceSummaryMixin
from .source_facts import SourceFactMixin
from .fact_chronology import FactChronologyMixin
from talemate.knowledge.supported_facts import previous_audience_facts
from talemate.knowledge.perspectives import source_reference
from talemate.exceptions import GenerationCancelled

import talemate.agents.summarize.nodes  # noqa: F401
from talemate.agents.summarize.websocket_handler import SummarizeWebsocketHandler

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene


log = structlog.get_logger("talemate.agents.summarize")

MIN_CHUNK_LINE_LENGTH = 20

talemate.emit.async_signals.register(
    "agent.summarization.before_build_archive",
    "agent.summarization.after_build_archive",
    "agent.summarization.rag_build_sub_instruction",
    "agent.summarization.summarize.before",
    "agent.summarization.summarize.after",
)


class BuildArchiveEmission(AgentEmission):
    generation_options: GenerationOptions | None = None


class SummarizeEmission(AgentTemplateEmission):
    text: str = ""
    extra_context: list[str] | str | None = None
    extra_instructions: str | None = None
    generation_options: GenerationOptions | None = None
    summarization_history: list[str] | None = None
    summarization_type: Literal["dialogue", "events"] = "dialogue"


@dataclass
class ArchiveSpan:
    start: int
    end: int | None
    tokens: int
    threshold: int
    dialogue_entries: list
    recent_entry: dict | None
    time_passage_termination: bool
    presence_termination: bool


@register()
class SummarizeAgent(
    FactChronologyMixin,
    SourceFactMixin,
    AudienceSummaryMixin,
    PerceptionMixin,
    MemoryRAGMixin,
    ContextHistoryMixin,
    LayeredHistoryMixin,
    SceneAnalyzationMixin,
    TTSUtilsMixin,
    Agent,
):
    """
    An agent that can be used to summarize text
    """

    agent_type = "summarizer"
    verbose_name = "Summarizer"
    auto_squish = False
    websocket_handler = SummarizeWebsocketHandler

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {
            "prompt_caching": optimize_prompt_caching_action(),
            "archive": AgentAction(
                enabled=True,
                container=True,
                icon="mdi-archive",
                label="Summarization",
                description="Automatically summarize scene dialogue when the number of tokens in the history exceeds a threshold. This helps keep the context history from growing too large.",
                config={
                    "threshold": AgentActionConfig(
                        type="number",
                        label="Token Threshold",
                        description="Will summarize when the number of tokens in the history exceeds this threshold",
                        min=512,
                        max=64000,
                        step=256,
                        value=1536,
                        graduations=[
                            {"from": 0, "step": 128},
                            {"from": 2048, "step": 256},
                            {"from": 8192, "step": 512},
                            {"from": 16384, "step": 1024},
                        ],
                    ),
                    "method": AgentActionConfig(
                        type="text",
                        label="Summarization Method",
                        description="Which method to use for summarization",
                        value="balanced",
                        choices=[
                            {"label": "Short & Concise", "value": "short"},
                            {"label": "Balanced", "value": "balanced"},
                            {"label": "Lengthy & Detailed", "value": "long"},
                            {"label": "Factual List", "value": "facts"},
                        ],
                    ),
                    "include_previous": AgentActionConfig(
                        type="number",
                        label="Use preceeding summaries to strengthen context",
                        description="Number of entries",
                        note="Help the AI summarize by including the last few summaries as additional context. Some models may incorporate this context into the new summary directly, so if you find yourself with a bunch of similar history entries, try setting this to 0.",
                        value=6,
                        min=0,
                        max=24,
                        step=1,
                    ),
                    "instructions": AgentActionConfig(
                        type="blob",
                        label="Custom instructions",
                        description="Optional instructions to guide the summarization process.",
                        value="",
                    ),
                    "extract_facts": AgentActionConfig(
                        type="bool",
                        label="Extract facts",
                        description="Save individual facts alongside summaries for character knowledge. Leave on to build the fact record; this summary step needs no extra request.",
                        value=True,
                    ),
                    "fact_dedupe_distance": AgentActionConfig(
                        type="number",
                        label="Fact matching tolerance",
                        description="Treat sufficiently similar facts as repeats instead of saving them again. Raise to merge more similar facts; lower to keep more distinctions.",
                        value=0.15,
                        min=0.0,
                        max=1.0,
                        step=0.01,
                    ),
                },
            ),
        }
        ContextHistoryMixin.add_actions(actions)
        LayeredHistoryMixin.add_actions(actions)
        MemoryRAGMixin.add_actions(actions)
        SceneAnalyzationMixin.add_actions(actions)
        PerceptionMixin.add_actions(actions)
        FactChronologyMixin.add_actions(actions)
        return actions

    def __init__(self, client: ClientBase | None = None, **kwargs):
        self.client = client
        self.init_perceptions()
        self.init_audience_summaries()
        self.init_source_facts()

        self.actions = SummarizeAgent.init_actions()

    @property
    def archive_enabled(self):
        return self.resolve_enabled("archive")

    @property
    def threshold(self):
        return self.resolve_config("archive", "threshold")

    @property
    def estimated_entry_count(self):
        all_tokens = sum([util.count_tokens(entry) for entry in self.scene.history])
        return all_tokens // self.threshold

    @property
    def archive_threshold(self):
        return self.resolve_config("archive", "threshold")

    @property
    def archive_method(self):
        return self.resolve_config("archive", "method")

    @property
    def archive_include_previous(self):
        return self.resolve_config("archive", "include_previous")

    @property
    def archive_extract_facts(self) -> bool:
        return bool(self.resolve_config("archive", "extract_facts"))

    @property
    def archive_fact_dedupe_distance(self) -> float:
        return float(self.resolve_config("archive", "fact_dedupe_distance"))

    @property
    def archive_instructions(self):
        return self.resolve_config("archive", "instructions")

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("push_history.after").connect(
            self.on_push_history
        )

    async def on_push_history(self, emission: HistoryEvent):
        """
        Called when a conversation is generated
        """

        generation_options = GenerationOptions(
            writing_style=self.scene.writing_style,
        )

        await self.build_archive(
            self.scene, generation_options=generation_options, notify=True
        )

    def clean_result(self, result):
        if "#" in result:
            result = result.split("#")[0]

        # Removes partial sentence at the end
        result = util.strip_partial_sentences(result)
        result = result.strip()

        return result

    # RAG HELPERS

    async def rag_build_sub_instruction(self):
        # Fire event to get the sub instruction from mixins
        emission = RagBuildSubInstructionEmission(
            agent=self,
        )
        await talemate.emit.async_signals.get(
            "agent.summarization.rag_build_sub_instruction"
        ).send(emission)

        return emission.sub_instruction

    # SUMMARIZATION HELPERS

    async def previous_summaries(
        self, entry: ArchiveEntry, *, scene: "Scene | None" = None
    ) -> list[str]:
        scene = scene or self.scene
        num_previous = self.archive_include_previous

        # find entry by .id
        entry_index = next(
            (i for i, e in enumerate(scene.archived_history) if e["id"] == entry.id),
            None,
        )
        if entry_index is None:
            raise ValueError("Entry not found")
        end = entry_index - 1

        previous_summaries = []

        if entry and num_previous > 0:
            if self.layered_history_available:
                previous_summaries = self.compile_layered_history(
                    include_base_layer=True,
                    base_layer_end_id=entry.id,
                    scene=scene,
                )[-num_previous:]
            else:
                previous_summaries = [
                    entry["text"]
                    for entry in scene.archived_history[end - num_previous : end]
                ]

        return previous_summaries

    # SUMMARIZE

    def collect_archive_span(self, scene) -> ArchiveSpan:
        """
        Walk the unarchived history the way the next archive would consume
        it: from the entry after the last archive end, skipping messages that
        are not dialogue, ignoring the newest message (the user may still
        regenerate it), and stopping at a time passage, a presence change or
        the token threshold. `end` stays None while nothing is due.
        """
        if not scene.archived_history:
            start = 0
            recent_entry = None
        else:
            recent_entry = scene.archived_history[-1]
            if "end" not in recent_entry:
                # permanent historical archive entry, not tied to any specific history entry
                # meaning we are still at the beginning of the scene
                start = 0
            else:
                start = recent_entry.get("end", 0) + 1

        end = None
        tokens = 0
        dialogue_entries = []
        time_passage_termination = False
        presence_termination = False
        # presence of the span so far; an unknown message neither changes nor
        # resets it, so a known change after an unknown message still cuts
        span_present: list[str] | None = None

        token_threshold = self.archive_threshold

        log.debug("build_archive", start=start, recent_entry=recent_entry)

        for i in range(start, max(start, len(scene.history) - 1)):
            dialogue = scene.history[i]

            if isinstance(
                dialogue,
                (
                    DirectorMessage,
                    ContextInvestigationMessage,
                    ReinforcementMessage,
                    CharacterTransitionMessage,
                ),
            ):
                # these messages are not part of the dialogue and should not be summarized
                if i == start:
                    start += 1
                continue

            if isinstance(dialogue, TimePassageMessage):
                log.debug("build_archive", time_passage_message=dialogue)

                if i == start:
                    log.debug(
                        "build_archive",
                        time_passage_message=dialogue,
                        start=start,
                        i=i,
                    )
                    start += 1
                    continue
                log.debug("build_archive", time_passage_message_termination=dialogue)
                time_passage_termination = True
                end = i - 1
                break

            if dialogue_entries and presence_differs(dialogue.present, span_present):
                log.debug("build_archive", presence_termination=dialogue.present)
                presence_termination = True
                end = i - 1
                break

            if dialogue.present is not None:
                span_present = dialogue.present

            tokens += util.count_tokens(dialogue)
            dialogue_entries.append(dialogue)
            if tokens > token_threshold:
                end = i
                break

        return ArchiveSpan(
            start=start,
            end=end,
            tokens=tokens,
            threshold=token_threshold,
            dialogue_entries=dialogue_entries,
            recent_entry=recent_entry,
            time_passage_termination=time_passage_termination,
            presence_termination=presence_termination,
        )

    def archive_status(self) -> dict:
        """
        Where the next archive stands, for display. `due` is the collector's
        own cutoff state (a span cut by the threshold, a time passage or a
        presence change); `remaining_tokens` is how many more tokens take the
        gathered dialogue past the threshold, since the cutoff is strictly
        greater than.
        """
        threshold = self.archive_threshold
        if not self.archive_enabled:
            return {
                "enabled": False,
                "threshold": threshold,
                "pending_tokens": None,
                "remaining_tokens": None,
                "due": False,
                "due_reason": None,
            }
        span = self.collect_archive_span(self.scene)
        due = span.end is not None
        if span.time_passage_termination:
            due_reason = "time_passage"
        elif span.presence_termination:
            due_reason = "presence"
        elif due:
            due_reason = "threshold"
        else:
            due_reason = None
        return {
            "enabled": True,
            "threshold": threshold,
            "pending_tokens": span.tokens,
            "remaining_tokens": 0 if due else threshold - span.tokens + 1,
            "due": due,
            "due_reason": due_reason,
        }

    @set_processing
    @evidence_writer
    async def build_archive(
        self,
        scene,
        generation_options: GenerationOptions | None = None,
        *,
        notify: bool = False,
    ):
        end = None
        enabled = self.archive_enabled

        log.debug("build_archive", enabled=enabled)

        emission = BuildArchiveEmission(
            agent=self,
            generation_options=generation_options,
        )

        await talemate.emit.async_signals.get(
            "agent.summarization.before_build_archive"
        ).send(emission)

        if not enabled:
            return

        span = self.collect_archive_span(scene)
        start = span.start
        end = span.end
        dialogue_entries = span.dialogue_entries
        time_passage_termination = span.time_passage_termination
        presence_termination = span.presence_termination
        recent_entry = span.recent_entry

        # if there is a recent entry we also collect the 3 most recentries
        # as extra context

        num_previous = self.archive_include_previous
        if recent_entry and num_previous > 0:
            if self.layered_history_available:
                extra_context = self.compile_layered_history(include_base_layer=True)[
                    -num_previous:
                ]
            else:
                extra_context = [
                    entry["text"] for entry in scene.archived_history[-num_previous:]
                ]

        else:
            extra_context = None

        if end is None:
            # nothing to archive yet
            log.debug(
                "build_archive", token_threshold=span.threshold, tokens=span.tokens
            )
            return

        times = message_times(scene)

        log.debug(
            "build_archive",
            start=start,
            end=end,
            time_passage_termination=time_passage_termination,
            presence_termination=presence_termination,
        )

        # in order to summarize coherently, we need to determine if there is a favorable
        # cutoff point (e.g., the scene naturally ends or shifts meaninfully in the middle
        # of the  dialogue)
        #
        # One way to do this is to check if the last line is a TimePassageMessage, which
        # indicates a scene change or a significant pause.
        #
        # If not, we can ask the AI to find a good point of
        # termination.

        if not time_passage_termination and not presence_termination:
            # No TimePassageMessage, so we need to ask the AI to find a good point of termination

            terminating_line = await self.analyze_dialoge(dialogue_entries)

            if terminating_line:
                adjusted_dialogue = []
                for line in dialogue_entries:
                    if str(line) in terminating_line:
                        break
                    adjusted_dialogue.append(line)

                # if difference start and end is less than 4, ignore the termination
                if len(adjusted_dialogue) > 4:
                    dialogue_entries = adjusted_dialogue
                    end = start + len(dialogue_entries) - 1
                else:
                    log.debug(
                        "build_archive",
                        message="Ignoring termination",
                        start=start,
                        end=end,
                        adjusted_dialogue=adjusted_dialogue,
                    )

        intro_included = None
        lines: dict[int, SpanLine] = {}
        intro_line: SpanLine | None = None
        if dialogue_entries:
            present = span_presence(dialogue_entries)
            lines = span_bindings(scene, dialogue_entries, times=times)
            intro_text = None

            if not extra_context:
                intro_present = getattr(scene, "intro_present", None)
                intro_included = intro_present is None or (
                    present is not None and set(present) <= set(intro_present)
                )
                if intro_included:
                    intro_text = scene.intro
                    intro_line = self._intro_line(scene, dialogue_entries, lines)

            summarized = None
            parsed_facts = None
            retries = 5

            while not summarized and retries > 0:
                summarized, parsed_facts = await self.summarize(
                    render_span(dialogue_entries, intro=intro_text),
                    extra_context=extra_context,
                    generation_options=generation_options,
                    return_facts=True,
                    line_ids=True,
                )
                retries -= 1

            if not summarized:
                raise IOError("Failed to summarize dialogue", dialogue=dialogue_entries)

            facts_status = self._facts_status(parsed_facts)

        else:
            # AI has likely identified the first line as a scene change, so we can't summarize
            # just use the first line
            summarized = str(scene.history[start])
            present = scene.history[start].present
            parsed_facts = None
            facts_status = None

        # the time of the last line: a passage that ends the span is after it
        entry = ArchiveEntry(
            text=summarized,
            start=start,
            end=end,
            ts=times[scene.history[end].id],
            present=present,
            intro_included=intro_included,
            facts_status=facts_status,
        )
        await scene.push_archive(entry)

        if parsed_facts and not character_knowledge_enabled(scene):
            await store_facts(
                scene,
                entry.id,
                parsed_facts,
                self.archive_fact_dedupe_distance,
                lines=lines,
                intro=intro_line,
                notify=notify,
            )
            await refresh_topics(scene)

        scene.emit_status()

        await talemate.emit.async_signals.get(
            "agent.summarization.after_build_archive"
        ).send(emission)

        await self.queue_summary_views(
            scene, entry.id, generation_options=generation_options
        )
        return True

    @staticmethod
    def _intro_line(scene, messages, lines: dict[int, SpanLine]) -> SpanLine | None:
        """
        The opening is not a message: a fact from it binds to the first line
        of the span for time and edit tracking, with the opening's audience.
        """
        first = next(
            (lines[message.id] for message in messages if message.id in lines), None
        )
        if first is None:
            return None
        return SpanLine(
            message_id=first.message_id,
            message_digest=first.message_digest,
            present=getattr(scene, "intro_present", None),
            ts=first.ts,
        )

    def _entry_span(self, scene, entry: ArchiveEntry):
        """The span text and line bindings of a summarized base entry."""
        messages = [
            message
            for message in scene.history[entry.start : entry.end + 1]
            if message.typ not in SPAN_LINE_EXCLUDED_TYPES
        ]
        lines = span_bindings(scene, messages, times=message_times(scene))
        intro_text = scene.intro if entry.intro_included else None
        intro_line = (
            self._intro_line(scene, messages, lines) if entry.intro_included else None
        )
        return render_span(messages, intro=intro_text), lines, intro_line

    @set_processing
    async def analyze_dialoge(self, dialogue):
        response, extracted = await Prompt.request(
            "summarizer.analyze-dialogue",
            self.client,
            "analyze_freeform",
            vars={
                "dialogue": "\n".join(map(str, dialogue)),
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            },
        )

        if not extracted.get("response"):
            return None

        result = self.clean_result(extracted["response"])
        return result

    @set_processing
    async def find_natural_scene_termination(
        self, event_chunks: list[str]
    ) -> list[list[str]]:
        """
        Will analyze a list of events and return a list of events that
        has been separated at a natural scene termination points.
        """

        # scan through event chunks and split into paragraphs
        rebuilt_chunks = []

        for chunk in event_chunks:
            paragraphs = [p.strip() for p in chunk.split("\n") if p.strip()]
            rebuilt_chunks.extend(paragraphs)

        event_chunks = rebuilt_chunks

        response, extracted = await Prompt.request(
            "summarizer.find-natural-scene-termination-events",
            self.client,
            "analyze_short2",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "events": event_chunks,
            },
        )
        response = extracted["response"].strip() if extracted["response"] else ""

        items = util.extract_list(response)

        # will be a list of
        # ["Progress 1", "Progress 12", "Progress 323", ...]
        # convert to a list of just numbers

        numbers = []

        for item in items:
            match = re.match(r"Progress (\d+)", item.strip())
            if match:
                numbers.append(int(match.group(1)))

        # make sure its unique and sorted
        numbers = sorted(list(set(numbers)))

        result = []
        prev_number = 0
        for number in numbers:
            result.append(event_chunks[prev_number : number + 1])
            prev_number = number + 1

        # result = {
        #    "selected": event_chunks[:number+1],
        #    "remaining": event_chunks[number+1:]
        # }

        log.debug(
            "find_natural_scene_termination",
            response=response,
            result=result,
            numbers=numbers,
        )

        return result

    def _facts_status(self, parsed_facts, *, scene=None) -> FactsStatus | None:
        if not self.archive_extract_facts:
            return None
        if character_knowledge_enabled(scene or self.scene):
            return None
        return "ok" if parsed_facts is not None else "failed"

    @evidence_writer
    async def summarize_with_facts(
        self,
        entry: ArchiveEntry,
        extra_context: str = None,
        generation_options: GenerationOptions | None = None,
        *,
        scene=None,
        still_current=None,
    ) -> tuple[str, FactsStatus | None]:
        """
        Re-summarize an existing base entry from its span and replace its facts.

        With fact extraction off the facts of the entry are left alone.
        """
        target_scene = scene or self.scene
        if still_current is not None and not still_current():
            raise GenerationCancelled("The scene changed during history refresh")
        text, lines, intro_line = self._entry_span(target_scene, entry)
        if character_knowledge_enabled(target_scene) or not self.archive_extract_facts:
            summarized = await self.summarize(
                text,
                extra_context=extra_context,
                generation_options=generation_options,
                line_ids=True,
            )
            if self.scene is not target_scene or (
                still_current is not None and not still_current()
            ):
                raise GenerationCancelled("The scene changed during history refresh")
            return summarized, (
                None
                if character_knowledge_enabled(target_scene)
                else entry.facts_status
            )

        dedupe_distance = self.archive_fact_dedupe_distance
        summarized, parsed_facts = await self.summarize(
            text,
            extra_context=extra_context,
            generation_options=generation_options,
            return_facts=True,
            line_ids=True,
        )
        if self.scene is not target_scene or (
            still_current is not None and not still_current()
        ):
            raise GenerationCancelled("The scene changed during history refresh")
        await drop_facts_for_entries(target_scene, {entry.id})
        if still_current is not None and not still_current():
            raise GenerationCancelled("The scene changed during history refresh")
        if parsed_facts:
            await store_facts(
                target_scene,
                entry.id,
                parsed_facts,
                dedupe_distance,
                lines=lines,
                intro=intro_line,
                still_current=still_current,
            )
        if still_current is not None and not still_current():
            raise GenerationCancelled("The scene changed during history refresh")
        await refresh_topics(target_scene, force=True, still_current=still_current)
        if still_current is not None and not still_current():
            raise GenerationCancelled("The scene changed during history refresh")
        return summarized, self._facts_status(parsed_facts, scene=target_scene)

    @evidence_writer
    async def regenerate_facts(self, entry: "HistoryEntry") -> FactsStatus | None:
        """
        Re-run the summary call for one base entry and replace only its facts.
        The entry text is kept.
        """
        if entry.layer != 0:
            return None

        archive_entry = resolve_history_entry(self.scene, entry)
        if not self.archive_extract_facts:
            return archive_entry.facts_status

        if character_knowledge_enabled(self.scene):
            scene = self.scene
            reference = source_reference(scene, "summary", archive_entry.id)
            status = (
                await self.rebuild_supported_facts(scene, [reference])
                if not self.fact_source_unavailable_reason(scene, archive_entry)
                else "failed"
            )
            for stored in scene.archived_history:
                if stored.get("id") == archive_entry.id:
                    stored["facts_status"] = status
                    break
            return status

        static = archive_entry.start is None and archive_entry.end is None
        lines: dict[int, SpanLine] | None = None
        intro_line = None
        if static:
            text = archive_entry.text
        else:
            text, lines, intro_line = self._entry_span(self.scene, archive_entry)
            if not lines:
                return archive_entry.facts_status
        if not text.strip():
            return archive_entry.facts_status

        _, parsed_facts = await self.summarize(
            text,
            extra_context=[]
            if static
            else await self.previous_summaries(archive_entry),
            return_facts=True,
            include_previous_facts=not static,
            line_ids=not static,
        )
        await drop_facts_for_entries(self.scene, {archive_entry.id})
        if parsed_facts:
            await store_facts(
                self.scene,
                archive_entry.id,
                parsed_facts,
                self.archive_fact_dedupe_distance,
                lines=lines,
                intro=intro_line,
                present=archive_entry.present,
                ts=archive_entry.ts,
            )
        await refresh_topics(self.scene, force=True)
        status = self._facts_status(parsed_facts)
        stored = self.scene.archived_history[entry.index]
        if status is None:
            stored.pop("facts_status", None)
        else:
            stored["facts_status"] = status
        return status

    @set_processing
    async def summarize(
        self,
        text: str,
        extra_context: str = None,
        method: str = None,
        extra_instructions: str = None,
        generation_options: GenerationOptions | None = None,
        return_facts: bool = False,
        audience: tuple[str, ...] | None = None,
        skip_author_hooks: bool = False,
        fact_evidence: list[dict] | None = None,
        include_previous_facts: bool = True,
        line_ids: bool = False,
    ):
        """
        Summarize the given text

        With `return_facts` the same call also asks for the atomic facts and
        returns `(summary, facts)`, where `facts` is None when the model's
        FACTS output did not parse. With `line_ids` every line of the text
        starts with its bracketed message id and each fact names its line.
        """

        if audience and not character_knowledge_enabled(self.scene):
            raise ValueError("Audience summaries require perception mode")
        response_length = 1024
        extract_facts = (
            return_facts
            and self.archive_extract_facts
            and (bool(audience) or not character_knowledge_enabled(self.scene))
        )

        template_vars = {
            "dialogue": text,
            "audience_summary": audience,
            "fact_evidence": fact_evidence or [],
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "summarization_method": (self.archive_method if method is None else method),
            "extra_context": extra_context or "",
            "num_extra_context": len(extra_context) if extra_context else 0,
            "extra_instructions": extra_instructions or "",
            "agent_instructions": self.archive_instructions or "",
            "generation_options": generation_options,
            "analyze_chunks": self.layered_history_analyze_chunks,
            "response_length": response_length,
            "extract_facts": extract_facts,
            "line_ids": line_ids,
            "previous_facts": (
                previous_audience_facts(self.scene, audience)
                if audience
                else previous_facts(self.scene)
            )
            if extract_facts and include_previous_facts
            else [],
        }

        emission = SummarizeEmission(
            agent=self,
            text=text,
            extra_context=extra_context,
            extra_instructions=extra_instructions,
            generation_options=generation_options,
            template_vars=template_vars,
            summarization_history=extra_context or [],
            summarization_type="dialogue",
        )

        if not skip_author_hooks:
            await talemate.emit.async_signals.get(
                "agent.summarization.summarize.before"
            ).send(emission)

        template_vars["dynamic_instructions"] = emission.dynamic_instructions

        from talemate.knowledge.evidence import budget_evidence

        template_vars["fact_evidence"] = (
            budget_evidence(
                fact_evidence or [],
                self.client.max_token_length,
                util.count_tokens(
                    "\n".join(
                        str(template_vars[key])
                        for key in (
                            "dialogue",
                            "extra_context",
                            "extra_instructions",
                            "agent_instructions",
                            "previous_facts",
                            "dynamic_instructions",
                        )
                    )
                ),
                response_length,
            )
            if extract_facts
            else ""
        )

        response, extracted = await Prompt.request(
            "summarizer.summarize-dialogue",
            self.client,
            f"summarize_{response_length}",
            vars=template_vars,
            dedupe_enabled=False,
            response_spec=SUMMARY_WITH_FACTS_SPEC if extract_facts else SUMMARY_SPEC,
        )

        log.debug(
            "summarize", dialogue_length=len(text), summarized_length=len(response)
        )

        # Use extracted summary, fall back to full response if not found
        summary = extracted["summary"]
        if not summary:
            log.error("summarize failed", response=response)
            return ("", None) if return_facts else ""

        parsed_facts = None
        if extract_facts:
            parsed_facts = parse_facts(extracted.get("facts"))
            if parsed_facts is None:
                log.warning(
                    "summarize: facts output did not parse",
                    tail=(response or "")[-300:],
                )
            else:
                # a restatement counts only against a fact this request offered
                parsed_facts = verify_restatements(
                    parsed_facts,
                    {fact.id for fact in template_vars["previous_facts"]},
                )

        summary = summary.strip()

        # capitalize first letter
        try:
            summary = summary[0].upper() + summary[1:]
        except IndexError:
            pass

        emission.response = self.clean_result(summary)

        if not skip_author_hooks:
            await talemate.emit.async_signals.get(
                "agent.summarization.summarize.after"
            ).send(emission)

        summary = emission.response

        if return_facts:
            return self.clean_result(summary), parsed_facts

        return self.clean_result(summary)

    @set_processing
    async def summarize_events(
        self,
        text: str,
        extra_context: str = None,
        extra_instructions: str = None,
        generation_options: GenerationOptions | None = None,
        analyze_chunks: bool = False,
        chunk_size: int = 1280,
        response_length: int = 2048,
        audience: tuple[str, ...] | None = None,
        skip_author_hooks: bool = False,
    ):
        """
        Summarize the given text
        """

        if audience and not character_knowledge_enabled(self.scene):
            raise ValueError("Audience summaries require perception mode")
        if not extra_context:
            extra_context = ""

        mentioned_characters: list["Character"] = self.scene.parse_characters_from_text(
            text + extra_context, exclude_active=True
        )

        template_vars = {
            "dialogue": text,
            "audience_summary": audience,
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "extra_context": extra_context,
            "num_extra_context": len(extra_context),
            "extra_instructions": extra_instructions or "",
            "generation_options": generation_options,
            "analyze_chunks": analyze_chunks,
            "chunk_size": chunk_size,
            "response_length": response_length,
            "mentioned_characters": mentioned_characters,
        }

        emission = SummarizeEmission(
            agent=self,
            text=text,
            extra_context=extra_context,
            extra_instructions=extra_instructions,
            generation_options=generation_options,
            template_vars=template_vars,
            summarization_history=[extra_context] if extra_context else [],
            summarization_type="events",
        )

        if not skip_author_hooks:
            await talemate.emit.async_signals.get(
                "agent.summarization.summarize.before"
            ).send(emission)

        template_vars["dynamic_instructions"] = emission.dynamic_instructions

        response, extracted = await Prompt.request(
            "summarizer.summarize-events",
            self.client,
            f"summarize_{response_length}",
            vars=template_vars,
            dedupe_enabled=False,
            response_spec=CHUNK_CLEAN_SPEC,
        )

        # Use extracted cleaned response (with CHUNK/CHAPTER prefixes stripped)
        cleaned_response = extracted["cleaned"] or ""
        if not audience:
            cleaned_response = cleaned_response.replace('"', "")

        log.debug(
            "layered_history_summarize",
            original_length=len(text),
            summarized_length=len(cleaned_response),
        )

        # clean up analyzation (remove analyzation text)
        if analyze_chunks:
            # remove all lines that begin with "ANALYSIS OF"
            # Note: We check for "ANALYSIS OF" (not "ANALYSIS OF CHUNK") because
            # CHUNK_CLEAN_SPEC already stripped "CHUNK N:" from the text
            cleaned_response = "\n".join(
                [
                    line
                    for line in cleaned_response.split("\n")
                    if not line.startswith("ANALYSIS OF")
                ]
            )

        # Filter out degenerate chunk lines that are too short to be
        # meaningful summaries. LLMs sometimes produce placeholder text
        # like "[No content.]" when a chunk overlaps with prior context.
        if not audience:
            cleaned_response = "\n".join(
                line.strip()
                for line in cleaned_response.split("\n")
                if len(line.strip()) >= MIN_CHUNK_LINE_LENGTH or not line.strip()
            )

        # capitalize first letter
        try:
            cleaned_response = cleaned_response[0].upper() + cleaned_response[1:]
        except IndexError:
            pass

        emission.response = self.clean_result(cleaned_response)

        if not skip_author_hooks:
            await talemate.emit.async_signals.get(
                "agent.summarization.summarize.after"
            ).send(emission)

        result = emission.response

        log.debug(
            "summarize_events",
            original_length=len(text),
            summarized_length=len(result),
        )

        return self.clean_result(result)

    @set_processing
    async def summarize_director_chat(self, history: list) -> str:
        """
        Summarize a list of director chat messages into a concise summary that keeps
        important decisions and changes while discarding low-level function details.
        """
        response_length = 768
        response, extracted = await Prompt.request(
            "summarizer.summarize-director-chat",
            self.client,
            f"summarize_{response_length}",
            vars={
                "history": history,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "response_length": response_length,
            },
            dedupe_enabled=False,
            response_spec=SUMMARY_SPEC,
        )

        # Use extracted summary if found, otherwise fall back to full response
        result = extracted["summary"]
        if not result:
            result = (response or "").strip()
        else:
            result = result.strip()

        return self.clean_result(result)
