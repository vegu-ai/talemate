from __future__ import annotations

import asyncio
import re
import time
import traceback
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import structlog

import talemate.data_objects as data_objects
import talemate.emit.async_signals
import talemate.util as util
from talemate.events import GameLoopEvent
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage
from talemate.world_state.templates import GenerationOptions

from .base import Agent, AgentAction, AgentActionConfig, set_processing
from .registry import register

log = structlog.get_logger("talemate.agents.summarize")


@register()
class SummarizeAgent(Agent):
    """
    An agent that can be used to summarize text

    Ideally used with a GPT model or vicuna+wizard or or gpt-3.5
    gpt4-x-vicuna is also great here.
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
                    "layered_history": AgentActionConfig(
                        type="bool",
                        label="Generate layered history",
                        description="Generate a layered history with multiple levels of summarization",
                        value=True,
                    ),
                    "include_previous": AgentActionConfig(
                        type="number",
                        label="Use preceeding summaries to strengthen context",
                        description="Number of entries",
                        note="Help the AI summarize by including the last few summaries as additional context. Some models may incorporate this context into the new summary directly, so if you find yourself with a bunch of similar history entries, try setting this to 0.",
                        value=3,
                        min=0,
                        max=10,
                        step=1,
                    ),
                },
            )
        }

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
    
    @property
    def archive_layered_history(self):
        return self.actions["archive"].config["layered_history"].value
    

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop").connect(self.on_game_loop)

    async def on_game_loop(self, emission: GameLoopEvent):
        """
        Called when a conversation is generated
        """

        await self.build_archive(self.scene)
        
        if self.archive_layered_history:
            await self.summarize_to_layered_history()

    def clean_result(self, result):
        if "#" in result:
            result = result.split("#")[0]

        # Removes partial sentence at the end
        result = re.sub(r"[^\.\?\!]+(\n|$)", "", result)
        result = result.strip()

        return result

    @set_processing
    async def build_archive(
        self, scene, generation_options: GenerationOptions | None = None
    ):
        end = None

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
            extra_context = "\n\n".join(
                [entry["text"] for entry in scene.archived_history[-num_previous:]]
            )
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

            if isinstance(dialogue, DirectorMessage):
                if i == start:
                    start += 1
                continue

            if isinstance(dialogue, TimePassageMessage):
                log.debug("build_archive", time_passage_message=dialogue)
                if i == start:
                    ts = util.iso8601_add(ts, dialogue.ts)
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
                dialogue_entries = adjusted_dialogue
                end = start + len(dialogue_entries) - 1

        if dialogue_entries:
            summarized = await self.summarize(
                "\n".join(map(str, dialogue_entries)),
                extra_context=extra_context,
                generation_options=generation_options,
            )

        else:
            # AI has likely identified the first line as a scene change, so we can't summarize
            # just use the first line
            summarized = str(scene.history[start])

        # determine the appropariate timestamp for the summarization

        scene.push_archive(data_objects.ArchiveEntry(summarized, start, end, ts=ts))

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
    async def summarize(
        self,
        text: str,
        extra_context: str = None,
        method: str = None,
        extra_instructions: str = None,
        generation_options: GenerationOptions | None = None,
        source_type: str = "dialogue",
    ):
        """
        Summarize the given text
        """
        response = await Prompt.request(
            f"summarizer.summarize-{source_type}",
            self.client,
            "summarize",
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
                "extra_instructions": extra_instructions or "",
                "generation_options": generation_options,
            },
        )

        self.scene.log.info(
            "summarize", dialogue_length=len(text), summarized_length=len(response)
        )

        return self.clean_result(response)

    @set_processing
    async def generate_timeline(self) -> list[str]:
        """
        Will generate a factual and concise timeline of the scene history
        
        Events will be returned one per line, in a single sentence.
        
        Only major events and important milestones should be included.
        """
        
        events = []
        
        for ah in self.scene.archived_history:
            events.append(
                {
                    "text": ah["text"],
                    "time": util.iso8601_duration_to_human(ah["ts"], suffix="later", zero_time_default="The beginning")
                }
            )
            
        if not events:
            return []
            
        response = await Prompt.request(
            "summarizer.timeline",
            self.client,
            "analyze_extensive",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "events": events,
            },
        )
        
        log.debug("generate_timeline", response=response)
        
        return util.extract_list(response)
    
    @set_processing
    async def summarize_to_layered_history(self):
        
        """
        The layered history is a summarized archive with dynamic layers that
        will get less and less granular as the scene progresses.
        
        The most granular is still self.scene.archived_history, which holds
        all the base layer summarizations.
        
        self.scene.layered_history = [
            # first layer after archived_history
            [
                {
                    "start": 0, # index in self.archived_history
                    "end": 10, # index in self.archived_history
                    "ts": "PT5M",
                    "text": "A summary of the first 10 entries"
                },
                ...
            ],
            
            # second layer
            [
                {
                    "start": 0, # index in self.scene.layered_history[0]
                    "end": 5, # index in self.scene.layered_history[0]
                    "ts": "PT2M",
                    "text": "A summary of the first 5 entries"
                },
                ...
            ],
            
            # additional layers
            ...
        ]
        
        The same token threshold as for the base layer will be used for the
        layers.
        
        The same summarization function will be used for the layers.
        
        The next level layer will be generated automatically when the token
        threshold is reached.
        """
        
        if not self.scene.archived_history:
            return  # No base layer summaries to work with

        token_threshold = self.actions["archive"].config["threshold"].value
        include_previous = self.actions["archive"].config["include_previous"].value
        method = self.actions["archive"].config["method"].value

        if not hasattr(self.scene, 'layered_history'):
            self.scene.layered_history = []
            
        layered_history = self.scene.layered_history

        async def summarize_layer(source_layer, next_layer_index, start_from) -> bool:
            current_chunk = []
            current_tokens = 0
            start_index = start_from
            noop = True

            for i in range(start_from, len(source_layer)):
                entry = source_layer[i]
                entry_tokens = util.count_tokens(entry['text'])
                
                log.debug("summarize_to_layered_history", entry=entry["text"][:100]+"...", tokens=entry_tokens, current_layer=next_layer_index-1)
                
                if current_tokens + entry_tokens > token_threshold:
                    if current_chunk:
                        
                        try:
                            # check if the next layer exists
                            next_layer = layered_history[next_layer_index]
                        except IndexError:
                            # create the next layer
                            layered_history.append([])
                            log.debug("summarize_to_layered_history", created_layer=next_layer_index)
                            next_layer = layered_history[next_layer_index]
                        
                        # provide the previous N entries in the current layer
                        # as extra_context
                        
                        extra_context = "\n\n".join(
                            [chunk['text'] for chunk in next_layer[-include_previous:]]
                        )
                            
                        
                        summary_text = await self.summarize(
                            "\n\n".join(chunk['text'] for chunk in current_chunk),
                            method=method,
                            source_type="events",
                            extra_context=extra_context,
                        )
                        
                        noop = False
                        
                        # make sure the first letter is capitalized
                        summary_text = summary_text[0].upper() + summary_text[1:]
                        
                        log.debug("summarize_to_layered_history", original_length=util.count_tokens("\n".join(chunk['text'] for chunk in current_chunk)), summarized_length=util.count_tokens(summary_text))
                        
                        next_layer.append({
                            "start": start_index,
                            "end": i - 1,
                            "ts": current_chunk[0]['ts'],
                            "ts_start": current_chunk[0]['ts_start'] if 'ts_start' in current_chunk[0] else current_chunk[0]['ts'],
                            "ts_end": current_chunk[-1]['ts_end'] if 'ts_end' in current_chunk[-1] else current_chunk[-1]['ts'],
                            "text": summary_text
                        })
                        current_chunk = []
                        current_tokens = 0
                        start_index = i

                current_chunk.append(entry)
                current_tokens += entry_tokens
                
            log.debug("summarize_to_layered_history", tokens=current_tokens, threshold=token_threshold, next_layer=next_layer_index)
            
            return not noop
                
        
        # First layer (always the base layer)
        
        if not layered_history:
            layered_history.append([])
            log.debug("summarize_to_layered_history", layer="base", new_layer=True)
            await summarize_layer(self.scene.archived_history, 0, 0)
        else:
            # determine starting point by checking for `end` in the last entry
            last_entry = layered_history[0][-1]
            end = last_entry["end"]
            log.debug("summarize_to_layered_history", layer="base", start=end)
            await summarize_layer(self.scene.archived_history, 0, end + 1)
            
        # process layers
        async def update_layers() -> bool:
            noop = True
            for index in range(0, len(layered_history)):
                log.debug("WATCH", index=index)
                layer = layered_history[index]
                
                try:
                    # check if the next layer exists
                    next_layer = layered_history[index + 1]
                except IndexError:
                    next_layer = None
                
                end = next_layer[-1]["end"] if next_layer else 0
                
                log.debug("summarize_to_layered_history", layer=index, start=end)
                summarized = await summarize_layer(layered_history[index], index + 1, end + 1 if end else 0)
                
                if summarized:
                    noop = False
                    
            return not noop
        
        while await update_layers():
            pass