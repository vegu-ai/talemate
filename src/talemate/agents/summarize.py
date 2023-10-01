from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.data_objects as data_objects
import talemate.util as util
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage

from .base import Agent, set_processing
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

    def on_history_add(self, event):
        asyncio.ensure_future(self.build_archive(event.scene))

    def connect(self, scene):
        super().connect(scene)
        scene.signals["history_add"].connect(self.on_history_add)

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

        if not scene.archived_history:
            start = 0
            recent_entry = None
        else:
            recent_entry = scene.archived_history[-1]
            start = recent_entry.get("end", 0) + 1

        token_threshold = 1500
        tokens = 0
        dialogue_entries = []
        ts = "PT0S"
        time_passage_termination = False
        
        if recent_entry:
            ts = recent_entry.get("ts", ts)
        
        for i in range(start, len(scene.history)):
            dialogue = scene.history[i]
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
                end = start + len(dialogue_entries)
            
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
        perspective: str = None,
        pins: Union[List[str], None] = None,
        extra_context: str = None,
    ):
        """
        Summarize the given text
        """

        response = await Prompt.request("summarizer.summarize-dialogue", self.client, "summarize", vars={
            "dialogue": text,
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
        })
        
        self.scene.log.info("summarize", dialogue_length=len(text), summarized_length=len(response))

        return self.clean_result(response)

    @set_processing
    async def simple_summary(
        self, text: str, prompt_kind: str = "summarize", instructions: str = "Summarize"
    ):
        prompt = [
            text,
            "",
            f"Instruction: {instructions}",
            "<|BOT|>Short Summary: ",
        ]

        response = await self.client.send_prompt("\n".join(map(str, prompt)), kind=prompt_kind)
        if ":" in response:
            response = response.split(":")[1].strip()
        return response


    @set_processing
    async def request_world_state(self):

        t1 = time.time()

        _, world_state = await Prompt.request(
            "summarizer.request-world-state",
            self.client,
            "analyze",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "object_type": "character",
                "object_type_plural": "characters",
            }
        )
        
        self.scene.log.debug("request_world_state", response=world_state, time=time.time() - t1)
        
        return world_state
            
            
    @set_processing
    async def request_world_state_inline(self):
        
        """
        EXPERIMENTAL, Overall the one shot request seems about as coherent as the inline request, but the inline request is is about twice as slow and would need to run on every dialogue line.
        """

        t1 = time.time()

        # first, we need to get the marked items (objects etc.)

        marked_items_response = await Prompt.request(
            "summarizer.request-world-state-inline-items",
            self.client,
            "analyze_freeform",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            }
        )
        
        self.scene.log.debug("request_world_state_inline", marked_items=marked_items_response, time=time.time() - t1)
        
        return marked_items_response
    
    @set_processing
    async def analyze_time_passage(
        self,
        text: str,
    ):
        
        response = await Prompt.request(
            "summarizer.analyze-time-passage",
            self.client,
            "analyze_freeform_short",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
            }
        )
        
        duration = response.split("\n")[0].split(" ")[0].strip()
        
        if not duration.startswith("P"):
            duration = "P"+duration
        
        return duration
        

    @set_processing
    async def analyze_text_and_answer_question(
        self,
        text: str,
        query: str,
    ):
        
        response = await Prompt.request(
            "summarizer.analyze-text-and-answer-question",
            self.client,
            "analyze_freeform",
            vars = {
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "text": text,
                "query": query,
            }
        )
        
        log.debug("analyze_text_and_answer_question", query=query, text=text, response=response)
        
        return response