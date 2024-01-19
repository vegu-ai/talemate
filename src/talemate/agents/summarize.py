from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.data_objects as data_objects
import talemate.emit.async_signals
import talemate.util as util
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage
from talemate.events import GameLoopEvent

from .base import Agent, set_processing, AgentAction, AgentActionConfig
from .registry import register

import structlog

import time
import re

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
                        ],
                    ),
                }
            )
        }
        
    
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop").connect(self.on_game_loop)
        
        
    async def on_game_loop(self, emission:GameLoopEvent):
        """
        Called when a conversation is generated
        """

        await self.build_archive(self.scene)
        
        
    def clean_result(self, result):
        if "#" in result:
            result = result.split("#")[0]

        # Removes partial sentence at the end
        result = re.sub(r"[^\.\?\!]+(\n|$)", "", result)
        result = result.strip()

        return result

    @set_processing
    async def build_archive(self, scene):
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
                start = recent_entry.get("end", 0)+1

        tokens = 0
        dialogue_entries = []
        ts = "PT0S"
        time_passage_termination = False
        
        token_threshold = self.actions["archive"].config["threshold"].value
        
        log.debug("build_archive", start=start, recent_entry=recent_entry)
        
        if recent_entry:
            ts = recent_entry.get("ts", ts)
        
        for i in range(start, len(scene.history)):
            dialogue = scene.history[i]
            
            #log.debug("build_archive", idx=i, content=str(dialogue)[:64]+"...")
            
            if isinstance(dialogue, DirectorMessage):
                if i == start:
                    start += 1
                continue
            
            if isinstance(dialogue, TimePassageMessage):
                log.debug("build_archive", time_passage_message=dialogue)
                if i == start:
                    ts = util.iso8601_add(ts, dialogue.ts)
                    log.debug("build_archive", time_passage_message=dialogue, start=start, i=i, ts=ts)
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
        
        log.debug("build_archive", start=start, end=end, ts=ts, time_passage_termination=time_passage_termination)

        extra_context = None
        if recent_entry:
            extra_context = recent_entry["text"]
            
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
                end = start + len(dialogue_entries)-1
            
        if dialogue_entries:
            summarized = await self.summarize(
                "\n".join(map(str, dialogue_entries)), extra_context=extra_context
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
        response = await Prompt.request("summarizer.analyze-dialogue", self.client, "analyze_freeform", vars={
            "dialogue": "\n".join(map(str, dialogue)),
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
        })
        
        response = self.clean_result(response)
        return response
        
    @set_processing
    async def summarize(
        self,
        text: str,
        extra_context: str = None,
        method: str = None,
    ):
        """
        Summarize the given text
        """

        response = await Prompt.request("summarizer.summarize-dialogue", self.client, "summarize", vars={
            "dialogue": text,
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "summarization_method": self.actions["archive"].config["method"].value if method is None else method,
        })
        
        self.scene.log.info("summarize", dialogue_length=len(text), summarized_length=len(response))

        return self.clean_result(response)