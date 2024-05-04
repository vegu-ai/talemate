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
    ):
        """
        Summarize the given text
        """

        response = await Prompt.request(
            "summarizer.summarize-dialogue",
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
            },
        )

        self.scene.log.info(
            "summarize", dialogue_length=len(text), summarized_length=len(response)
        )

        return self.clean_result(response)

    async def build_stepped_archive_for_level(self, level: int):
        """
        WIP - not yet used

        This will iterate over existing archived_history entries
        and stepped_archived_history entries and summarize based on time duration
        indicated between the entries.

        The lowest level of summarization (based on token threshold and any time passage)
        happens in build_archive. This method is for summarizing furhter levels based on
        long time pasages.

        Level 0: small timestap summarize (summarizes all token summarizations when time advances +1 day)
        Level 1: medium timestap summarize (summarizes all small timestep summarizations when time advances +1 week)
        Level 2: large timestap summarize (summarizes all medium timestep summarizations when time advances +1 month)
        Level 3: huge timestap summarize (summarizes all large timestep summarizations when time advances +1 year)
        Level 4: massive timestap summarize (summarizes all huge timestep summarizations when time advances +10 years)
        Level 5: epic timestap summarize (summarizes all massive timestep summarizations when time advances +100 years)
        and so on (increasing by a factor of 10 each time)

        ```
        @dataclass
        class ArchiveEntry:
            text: str
            start: int = None
            end: int = None
            ts: str = None
        ```

        Like token summarization this will use ArchiveEntry and start and end will refer to the entries in the
        lower level of summarization.

        Ts is the iso8601 timestamp of the start of the summarized period.
        """

        # select the list to use for the entries

        if level == 0:
            entries = self.scene.archived_history
        else:
            entries = self.scene.stepped_archived_history[level - 1]

        # select the list to summarize new entries to

        target = self.scene.stepped_archived_history[level]

        if not target:
            raise ValueError(f"Invalid level {level}")

        # determine the start and end of the period to summarize

        if not entries:
            return

        # determine the time threshold for this level

        # first calculate all possible thresholds in iso8601 format, starting with 1 day
        thresholds = [
            "P1D",
            "P1W",
            "P1M",
            "P1Y",
        ]

        # TODO: auto extend?

        time_threshold_in_seconds = util.iso8601_to_seconds(thresholds[level])

        if not time_threshold_in_seconds:
            raise ValueError(f"Invalid level {level}")

        # determine the most recent summarized entry time, and then find entries
        # that are newer than that in the lower list

        ts = target[-1].ts if target else entries[0].ts

        # determine the most recent entry at the lower level, if its not newer or
        # the difference is less than the threshold, then we don't need to summarize

        recent_entry = entries[-1]

        if util.iso8601_diff(recent_entry.ts, ts) < time_threshold_in_seconds:
            return

        log.debug("build_stepped_archive", level=level, ts=ts)

        # if target is empty, start is 0
        # otherwise start is the end of the last entry

        start = 0 if not target else target[-1].end

        # collect entries starting at start until the combined time duration
        # exceeds the threshold

        entries_to_summarize = []

        for entry in entries[start:]:
            entries_to_summarize.append(entry)
            if util.iso8601_diff(entry.ts, ts) > time_threshold_in_seconds:
                break

        # summarize the entries
        # we also collect N entries of previous summaries to use as context

        num_previous = self.actions["archive"].config["include_previous"].value
        if num_previous > 0:
            extra_context = "\n\n".join(
                [entry["text"] for entry in target[-num_previous:]]
            )
        else:
            extra_context = None

        summarized = await self.summarize(
            "\n".join(map(str, entries_to_summarize)), extra_context=extra_context
        )

        # push summarized entry to target

        ts = entries_to_summarize[-1].ts

        target.append(
            data_objects.ArchiveEntry(
                summarized, start, len(entries_to_summarize) - 1, ts=ts
            )
        )
