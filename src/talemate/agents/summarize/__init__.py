from __future__ import annotations

import re
import dataclasses

import structlog

import talemate.data_objects as data_objects
import talemate.emit.async_signals
import talemate.util as util
from talemate.emit import emit
from talemate.events import GameLoopEvent
from talemate.prompts import Prompt
from talemate.scene_message import (
    DirectorMessage, 
    TimePassageMessage, 
    ContextInvestigationMessage, 
    ReinforcementMessage,
)
from talemate.world_state.templates import GenerationOptions
from talemate.tale_mate import Character
from talemate.instance import get_agent
from talemate.exceptions import GenerationCancelled
import talemate.game.focal as focal
import talemate.emit.async_signals

from talemate.agents.base import Agent, AgentAction, AgentActionConfig, set_processing, AgentEmission
from talemate.agents.registry import register

from .analyze_scene import SceneAnalyzationMixin
from .context_investigation import ContextInvestigationMixin
from .layered_history import LayeredHistoryMixin

log = structlog.get_logger("talemate.agents.summarize")

talemate.emit.async_signals.register(
    "agent.summarization.before_build_archive",
    "agent.summarization.after_build_archive",
)

@dataclasses.dataclass
class BuildArchiveEmission(AgentEmission):
    generation_options: GenerationOptions | None = None

@register()
class SummarizeAgent(
    LayeredHistoryMixin,
    ContextInvestigationMixin,
    # Needs to be after ContextInvestigationMixin so signals are connected in the right order
    SceneAnalyzationMixin,
    Agent
):
    """
    An agent that can be used to summarize text
    """

    agent_type = "summarizer"
    verbose_name = "Summarizer"
    auto_squish = False

    def __init__(self, client, **kwargs):
        self.client = client

        self.actions = {
            "archive": AgentAction(
                enabled=True,
                label="Summarize to long-term memory archive",
                description="Automatically summarize scene dialogue when the number of tokens in the history exceeds a threshold. This helps keep the context history from growing too large.",
                config={
                    "threshold": AgentActionConfig(
                        type="number",
                        label="Token Threshold",
                        description="Will summarize when the number of tokens in the history exceeds this threshold",
                        min=512,
                        max=8192,
                        step=256,
                        value=1536,
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
                },
            ),
        }
        
        LayeredHistoryMixin.add_actions(self)
        SceneAnalyzationMixin.add_actions(self)
        ContextInvestigationMixin.add_actions(self)

    @property
    def threshold(self):
        return self.actions["archive"].config["threshold"].value

    @property
    def estimated_entry_count(self):
        all_tokens = sum([util.count_tokens(entry) for entry in self.scene.history])
        return all_tokens // self.threshold

    @property
    def archive_threshold(self):
        return self.actions["archive"].config["threshold"].value
    
    @property
    def archive_method(self):
        return self.actions["archive"].config["method"].value
    
    @property
    def archive_include_previous(self):
        return self.actions["archive"].config["include_previous"].value

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop").connect(self.on_game_loop)

    async def on_game_loop(self, emission: GameLoopEvent):
        """
        Called when a conversation is generated
        """

        await self.build_archive(self.scene)

    def clean_result(self, result):
        if "#" in result:
            result = result.split("#")[0]

        # Removes partial sentence at the end
        result = util.strip_partial_sentences(result)
        result = result.strip()

        return result

    @set_processing
    async def build_archive(
        self, scene, generation_options: GenerationOptions | None = None
    ):
        end = None
        
        emission = BuildArchiveEmission(
            agent=self,
            generation_options=generation_options,
        )
        
        await talemate.emit.async_signals.get("agent.summarization.before_build_archive").send(emission)

        if not self.actions["archive"].enabled:
            return

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

        # if there is a recent entry we also collect the 3 most recentries
        # as extra context

        num_previous = self.actions["archive"].config["include_previous"].value
        if recent_entry and num_previous > 0:
            if self.layered_history_available:
                log.warning("build_archive with layered history")
                extra_context = self.compile_layered_history(include_base_layer=True)
            else:
                extra_context = [
                    entry["text"] for entry in scene.archived_history[-num_previous:]
                ]
                
        else:
            extra_context = None

        tokens = 0
        dialogue_entries = []
        ts = "PT0S"
        time_passage_termination = False

        token_threshold = self.actions["archive"].config["threshold"].value

        log.debug("build_archive", start=start, recent_entry=recent_entry)

        if recent_entry:
            ts = recent_entry.get("ts", ts)

        # we ignore the most recent entry, as the user may still chose to
        # regenerate it
        for i in range(start, max(start, len(scene.history) - 1)):
            dialogue = scene.history[i]

            # log.debug("build_archive", idx=i, content=str(dialogue)[:64]+"...")

            if isinstance(dialogue, (DirectorMessage, ContextInvestigationMessage, ReinforcementMessage)):
                # these messages are not part of the dialogue and should not be summarized
                if i == start:
                    start += 1
                continue

            if isinstance(dialogue, TimePassageMessage):
                log.debug("build_archive", time_passage_message=dialogue)
                ts = util.iso8601_add(ts, dialogue.ts)
                
                if i == start:
                    log.debug(
                        "build_archive",
                        time_passage_message=dialogue,
                        start=start,
                        i=i,
                        ts=ts,
                    )
                    start += 1
                    continue
                log.debug("build_archive", time_passage_message_termination=dialogue)
                time_passage_termination = True
                end = i - 1
                break

            tokens += util.count_tokens(dialogue)
            dialogue_entries.append(dialogue)
            if tokens > token_threshold:  #
                end = i
                break

        if end is None:
            # nothing to archive yet
            return

        log.debug(
            "build_archive",
            start=start,
            end=end,
            ts=ts,
            time_passage_termination=time_passage_termination,
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

        if not time_passage_termination:
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
                    log.warning("build_archive", message="Ignoring termination", start=start, end=end, adjusted_dialogue=adjusted_dialogue)

        if dialogue_entries:
            
            if not extra_context:
                # prepend scene intro to dialogue
                dialogue_entries.insert(0, scene.intro)
            
            summarized = None
            retries = 5
            
            while not summarized and retries > 0:
                summarized = await self.summarize(
                    "\n".join(map(str, dialogue_entries)),
                    extra_context=extra_context,
                    generation_options=generation_options,
                )
                retries -= 1
                
            if not summarized:
                raise IOError("Failed to summarize dialogue", dialogue=dialogue_entries)

        else:
            # AI has likely identified the first line as a scene change, so we can't summarize
            # just use the first line
            summarized = str(scene.history[start])

        # determine the appropariate timestamp for the summarization

        scene.push_archive(data_objects.ArchiveEntry(summarized, start, end, ts=ts))
        
        scene.ts=ts
        scene.emit_status()
        
        await talemate.emit.async_signals.get("agent.summarization.after_build_archive").send(emission)
        
        return True

    @set_processing
    async def analyze_dialoge(self, dialogue):
        response = await Prompt.request(
            "summarizer.analyze-dialogue",
            self.client,
            "analyze_freeform",
            vars={
                "dialogue": "\n".join(map(str, dialogue)),
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            },
        )

        response = self.clean_result(response)
        return response

    @set_processing
    async def find_natural_scene_termination(self, event_chunks:list[str]) -> list[list[str]]:
        """
        Will analyze a list of events and return a list of events that
        has been separated at a natural scene termination points.
        """
        
        # scan through event chunks and split into paragraphs
        rebuilt_chunks = []
        
        for chunk in event_chunks:
            paragraphs = [
                p.strip() for p in chunk.split("\n") if p.strip()
            ]
            rebuilt_chunks.extend(paragraphs)
        
        event_chunks = rebuilt_chunks
        
        response = await Prompt.request(
            "summarizer.find-natural-scene-termination-events",
            self.client,
            "analyze_short2",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "events": event_chunks,
            },
        )
        response = response.strip()
        
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
            result.append(event_chunks[prev_number:number+1])
            prev_number = number+1
        
        #result = {
        #    "selected": event_chunks[:number+1],
        #    "remaining": event_chunks[number+1:]
        #}
        
        log.debug("find_natural_scene_termination", response=response, result=result, numbers=numbers)
        
        return result
                

    @set_processing
    async def summarize(
        self,
        text: str,
        extra_context: str = None,
        method: str = None,
        extra_instructions: str = None,
        generation_options: GenerationOptions | None = None,
    ):
        """
        Summarize the given text
        """
        
        response_length = 1024
        
        response = await Prompt.request(
            f"summarizer.summarize-dialogue",
            self.client,
            f"summarize_{response_length}",
            vars={
                "dialogue": text,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "summarization_method": (
                    self.actions["archive"].config["method"].value
                    if method is None
                    else method
                ),
                "extra_context": extra_context or "",
                "num_extra_context": len(extra_context) if extra_context else 0,
                "extra_instructions": extra_instructions or "",
                "generation_options": generation_options,
                "analyze_chunks": self.layered_history_analyze_chunks,
                "response_length": response_length,
            },
            dedupe_enabled=False
        )

        self.scene.log.info(
            "summarize", dialogue_length=len(text), summarized_length=len(response)
        )
        
        try:
            summary = response.split("SUMMARY:")[1].strip()
        except Exception as e:
            log.error("summarize failed", response=response, exc=e)
            return ""
        
        # capitalize first letter
        try:
            summary = summary[0].upper() + summary[1:]
        except IndexError:
            pass
        
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
    ):
        """
        Summarize the given text
        """
        
        response = await Prompt.request(
            f"summarizer.summarize-events",
            self.client,
            f"summarize_{response_length}",
            vars={
                "dialogue": text,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "extra_context": extra_context or "",
                "num_extra_context": len(extra_context) if extra_context else 0,
                "extra_instructions": extra_instructions or "",
                "generation_options": generation_options,
                "analyze_chunks": analyze_chunks,
                "chunk_size": chunk_size,
                "response_length": response_length,
            },
            dedupe_enabled=False
        )
        
        response = response.strip()
        response = response.replace('"', "")
        
        self.scene.log.info(
            "layered_history_summarize", original_length=len(text), summarized_length=len(response)
        )
        
        # clean up analyzation (remove analyzation text)
        if self.layered_history_analyze_chunks:
            # remove all lines that begin with "ANALYSIS OF CHUNK \d+:"
            response = "\n".join([line for line in response.split("\n") if not line.startswith("ANALYSIS OF CHUNK")])
                                        
        # strip all occurences of "CHUNK \d+: " from the summary
        response = re.sub(r"(CHUNK|CHAPTER) \d+:\s+", "", response)
            
        # capitalize first letter
        try:
            response = response[0].upper() + response[1:]
        except IndexError:
            pass
        
        log.debug("summarize_events", original_length=len(text), summarized_length=len(response))
        
        return self.clean_result(response)
