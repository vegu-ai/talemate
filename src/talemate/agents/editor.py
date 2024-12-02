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
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage

from .base import Agent, AgentAction, AgentActionConfig, set_processing
from .registry import register

if TYPE_CHECKING:
    from talemate.agents.conversation import ConversationAgentEmission
    from talemate.agents.narrator import NarratorAgentEmission
    from talemate.tale_mate import Actor, Character, Scene

log = structlog.get_logger("talemate.agents.editor")


@register()
class EditorAgent(Agent):
    """
    Editor agent

    will attempt to improve the quality of dialogue
    """

    agent_type = "editor"
    verbose_name = "Editor"

    def __init__(self, client, **kwargs):
        self.client = client
        self.is_enabled = True
        self.actions = {
            "fix_exposition": AgentAction(
                enabled=True,
                label="Fix exposition",
                description="Will attempt to fix exposition and emotes, making sure they are displayed in italics. Runs automatically after each AI dialogue.",
                config={
                    "formatting": AgentActionConfig(
                        type="text",
                        label="Formatting",
                        description="The formatting to use for exposition.",
                        value="chat",
                        choices=[
                            {"label": "Chat RP: \"Speech\" *narration*", "value": "chat"},
                        ]
                    ),
                    "narrator": AgentActionConfig(
                        type="bool",
                        label="Fix narrator messages",
                        description="Will attempt to fix exposition issues in narrator messages",
                        value=True,
                    ),
                    "user_input": AgentActionConfig(
                        type="bool",
                        label="Fix user input",
                        description="Will attempt to fix exposition issues in user input",
                        value=True,
                    ),
                },
            ),
            "add_detail": AgentAction(
                enabled=False,
                label="Add detail",
                description="Will attempt to add extra detail and exposition to the dialogue. Runs automatically after each AI dialogue.",
            ),
            "check_continuity_errors": AgentAction(
                enabled=False,
                label="Check continuity errors",
                description="Will attempt to fix continuity errors in the dialogue. Runs automatically after each AI dialogue. (super experimental)",
            ),
        }

    @property
    def enabled(self):
        return self.is_enabled

    @property
    def has_toggle(self):
        return True

    @property
    def experimental(self):
        return True
    
    @property
    def fix_exposition_enabled(self):
        return self.actions["fix_exposition"].enabled
    
    @property
    def fix_exposition_formatting(self):
        return self.actions["fix_exposition"].config["formatting"].value

    @property
    def fix_exposition_narrator(self):
        return self.actions["fix_exposition"].config["narrator"].value
    
    @property
    def fix_exposition_user_input(self):
        return self.actions["fix_exposition"].config["user_input"].value
    

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.conversation.generated").connect(
            self.on_conversation_generated
        )
        talemate.emit.async_signals.get("agent.narrator.generated").connect(
            self.on_narrator_generated
        )

    def fix_exposition_in_text(self, text: str, character: Character | None = None):
        if self.fix_exposition_formatting == "chat":
            formatting = "md"
        else:
            formatting = None
        
        if self.fix_exposition_formatting == "chat":
            text = text.replace("**", "*")
            text = text.replace("[", "*").replace("]", "*")
            text = text.replace("(", "*").replace(")", "*")
        
        cleaned = util.ensure_dialog_format(
            text, 
            talking_character=character.name if character else None, 
            formatting=formatting
        )
        
        return cleaned


    async def on_conversation_generated(self, emission: ConversationAgentEmission):
        """
        Called when a conversation is generated
        """

        if not self.enabled:
            return

        log.info("editing conversation", emission=emission)

        edited = []
        for text in emission.generation:
            edit = await self.add_detail(text, emission.character)

            edit = await self.cleanup_character_message(edit, emission.character)

            edit = await self.check_continuity_errors(edit, emission.character)

            edited.append(edit)

        emission.generation = edited

    async def on_narrator_generated(self, emission: NarratorAgentEmission):
        """
        Called when a narrator message is generated
        """

        if not self.enabled:
            return

        log.info("editing narrator", emission=emission)

        edited = []

        for text in emission.generation:
            edit = await self.clean_up_narration(text)
            edited.append(edit)

        emission.generation = edited

    @set_processing
    async def cleanup_character_message(self, content: str, character: Character):
        """
        Edits a text to make sure all narrative exposition and emotes is encased in *
        """
        
        # if not content was generated, return it as is
        if not content:
            return content

        if not character.is_player and self.fix_exposition_enabled:
            if '"' not in content and "*" not in content:
                character_prefix = f"{character.name}: "
                message = content.split(character_prefix)[1]
                content = f'{character_prefix}"{message.strip()}"'
                return content
            elif '"' in content:
                # silly hack to clean up some LLMs that always start with a quote
                # even though the immediate next thing is a narration (indicated by *)
                content = content.replace(
                    f'{character.name}: "*', f"{character.name}: *"
                )

        content = util.clean_dialogue(content, main_name=character.name)
        content = util.strip_partial_sentences(content)
        
        if not self.fix_exposition_enabled:
            return content
        
        content = self.fix_exposition_in_text(content, character)

        return content

    @set_processing
    async def clean_up_narration(self, content: str):
        content = util.strip_partial_sentences(content)
        if self.fix_exposition_enabled and self.fix_exposition_narrator:
            if '"' not in content:
                if self.fix_exposition_formatting == "chat":
                    content = f"*{content.strip('*')}*"
            else:
                content = self.fix_exposition_in_text(content, None)

        return content

    @set_processing
    async def cleanup_user_input(self, text: str):
        if not self.fix_exposition_user_input or not self.fix_exposition_enabled:
            return text
        
        if '"' not in text and "*" not in text:
            text = f'"{text}"'
        
        return self.fix_exposition_in_text(text)
        

    @set_processing
    async def add_detail(self, content: str, character: Character):
        """
        Edits a text to increase its length and add extra detail and exposition
        """

        if not self.actions["add_detail"].enabled:
            return content

        response = await Prompt.request(
            "editor.add-detail",
            self.client,
            "edit_add_detail",
            vars={
                "content": content,
                "character": character,
                "scene": self.scene,
                "max_length": self.client.max_token_length,
            },
        )

        response = util.replace_exposition_markers(response)
        response = util.clean_dialogue(response, main_name=character.name)
        response = util.strip_partial_sentences(response)

        return response

    @set_processing
    async def check_continuity_errors(
        self,
        content: str,
        character: Character,
        force: bool = False,
        fix: bool = True,
        message_id: int = None,
    ) -> str:
        """
        Edits a text to ensure that it is consistent with the scene
        so far
        """

        if not self.actions["check_continuity_errors"].enabled and not force:
            return content

        MAX_CONTENT_LENGTH = 255
        count = util.count_tokens(content)

        if count > MAX_CONTENT_LENGTH:
            log.warning(
                "check_continuity_errors content too long",
                length=count,
                max=MAX_CONTENT_LENGTH,
                content=content[:255],
            )
            return content

        log.debug(
            "check_continuity_errors START",
            content=content,
            character=character,
            force=force,
            fix=fix,
            message_id=message_id,
        )

        response = await Prompt.request(
            "editor.check-continuity-errors",
            self.client,
            "basic_analytical_medium2",
            vars={
                "content": content,
                "character": character,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "message_id": message_id,
            },
        )

        # loop through response line by line, checking for lines beginning
        # with "ERROR {number}:

        errors = []

        for line in response.split("\n"):
            if "ERROR" not in line:
                continue

            errors.append(line)

        if not errors:
            log.debug("check_continuity_errors NO ERRORS")
            return content

        log.debug("check_continuity_errors ERRORS", fix=fix, errors=errors)

        if not fix:
            return content

        state = {}

        response = await Prompt.request(
            "editor.fix-continuity-errors",
            self.client,
            "editor_creative_medium2",
            vars={
                "content": content,
                "character": character,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "errors": errors,
                "set_state": lambda k, v: state.update({k: v}),
            },
        )

        content_fix_identifer = state.get("content_fix_identifier")

        try:
            content = response.strip().strip("```").split("```")[0].strip()
            content = content.replace(content_fix_identifer, "").strip()
            content = content.strip(":")

            # if content doesnt start with {character_name}: then add it
            if not content.startswith(f"{character.name}:"):
                content = f"{character.name}: {content}"

        except Exception as e:
            log.error(
                "check_continuity_errors FAILED",
                content_fix_identifer=content_fix_identifer,
                response=response,
                e=e,
            )
            return content

        log.debug("check_continuity_errors FIXED", content=content)

        return content
