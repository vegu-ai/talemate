from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.data_objects as data_objects
import talemate.util as util
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage

from .base import Agent
from .registry import register

import structlog

import time

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

    async def build_archive(self, scene):
        end = None

        if not scene.archived_history:
            start = 0
            recent_entry = None
        else:
            recent_entry = scene.archived_history[-1]
            start = recent_entry["end"] + 1

        token_threshold = 1300
        tokens = 0
        dialogue_entries = []
        for i in range(start, len(scene.history)):
            dialogue = scene.history[i]
            if isinstance(dialogue, DirectorMessage):
                continue
            
            tokens += util.count_tokens(dialogue)
            dialogue_entries.append(dialogue)
            if tokens > token_threshold:  #
                end = i
                break

        if end is None:
            # nothing to archive yet
            return
        await self.emit_status(processing=True)

        extra_context = None
        if recent_entry:
            extra_context = recent_entry["text"]

        terminating_line = await self.analyze_dialoge(dialogue_entries)

        log.debug("summarize agent build archive", terminating_line=terminating_line)

        if terminating_line:
            adjusted_dialogue = []
            for line in dialogue_entries:                    
                if str(line) in terminating_line:
                    break
                adjusted_dialogue.append(line)
            dialogue_entries = adjusted_dialogue
            end = start + len(dialogue_entries)

        summarized = await self.summarize(
            "\n".join(map(str, dialogue_entries)), extra_context=extra_context
        )

        scene.push_archive(data_objects.ArchiveEntry(summarized, start, end))
        await self.emit_status(processing=False)

        return True

    async def analyze_dialoge(self, dialogue):
        instruction = "Examine the dialogue from the beginning and find the first line that marks a scene change. Repeat the line back to me exactly as it is written"
        await self.emit_status(processing=True)

        prepare_response = "The first line that marks a scene change is: "

        prompt = dialogue + ["", instruction, f"<|BOT|>{prepare_response}"]

        response = await self.client.send_prompt("\n".join(map(str, prompt)), kind="summarize")

        if prepare_response in response:
            response = response.replace(prepare_response, "")

        response = self.clean_result(response)

        await self.emit_status(processing=False)

        return response

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

        await self.emit_status(processing=True)

        response = await Prompt.request("summarizer.summarize-dialogue", self.client, "summarize", vars={
            "dialogue": text,
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
        })
        
        self.scene.log.info("summarize", dialogue=text, response=response)

        await self.emit_status(processing=False)

        return self.clean_result(response)

    async def simple_summary(
        self, text: str, prompt_kind: str = "summarize", instructions: str = "Summarize"
    ):
        await self.emit_status(processing=True)
        prompt = [
            text,
            "",
            f"Instruction: {instructions}",
            "<|BOT|>Short Summary: ",
        ]

        response = await self.client.send_prompt("\n".join(map(str, prompt)), kind=prompt_kind)
        if ":" in response:
            response = response.split(":")[1].strip()
        await self.emit_status(processing=False)
        return response


    async def request_world_state(self):

        await self.emit_status(processing=True)
        try:
            
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
        finally:
            await self.emit_status(processing=False)
            
            
    async def request_world_state_inline(self):
        
        """
        EXPERIMENTAL, Overall the one shot request seems about as coherent as the inline request, but the inline request is is about twice as slow and would need to run on every dialogue line.
        """

        await self.emit_status(processing=True)
        try:
            
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
        finally:
            await self.emit_status(processing=False)
                   