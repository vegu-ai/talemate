from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.data_objects as data_objects
import talemate.util as util
import talemate.emit.async_signals
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage

from .base import Agent, set_processing, AgentAction, AgentActionConfig
from .registry import register

import structlog

import time
import re

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character, Scene
    from talemate.agents.conversation import ConversationAgentEmission
    from talemate.agents.narrator import NarratorAgentEmission

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
            "edit_dialogue": AgentAction(enabled=False, label="Edit dialogue", description="Will attempt to improve the quality of dialogue based on the character and scene. Runs automatically after each AI dialogue."),
            "fix_exposition": AgentAction(enabled=True, label="Fix exposition", description="Will attempt to fix exposition and emotes, making sure they are displayed in italics. Runs automatically after each AI dialogue.", config={
                "narrator": AgentActionConfig(type="bool", label="Fix narrator messages", description="Will attempt to fix exposition issues in narrator messages", value=True),
            }),
            "add_detail": AgentAction(enabled=False, label="Add detail", description="Will attempt to add extra detail and exposition to the dialogue. Runs automatically after each AI dialogue.")
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

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.conversation.generated").connect(self.on_conversation_generated)
        talemate.emit.async_signals.get("agent.narrator.generated").connect(self.on_narrator_generated)
        
    async def on_conversation_generated(self, emission:ConversationAgentEmission):
        """
        Called when a conversation is generated
        """
        
        if not self.enabled:
            return
        
        log.info("editing conversation", emission=emission)
        
        edited = []
        for text in emission.generation:

            
            edit = await self.add_detail(
                text,
                emission.character
            )
            
            edit = await self.edit_conversation(
                edit,
                emission.character
            )
            
            edit = await self.fix_exposition(
                edit,
                emission.character
            )
            
            edited.append(edit)
            
        emission.generation = edited
        
    async def on_narrator_generated(self, emission:NarratorAgentEmission):
        """
        Called when a narrator message is generated
        """
        
        if not self.enabled:
            return
        
        log.info("editing narrator", emission=emission)
        
        edited = []
        
        for text in emission.generation:
            edit = await self.fix_exposition_on_narrator(text)
            edited.append(edit)
            
        emission.generation = edited
        
        
    @set_processing
    async def edit_conversation(self, content:str, character:Character):
        """
        Edits a conversation
        """
        
        if not self.actions["edit_dialogue"].enabled:
            return content
        
        response = await Prompt.request("editor.edit-dialogue", self.client, "edit_dialogue", vars={
            "content": content,
            "character": character,
            "scene": self.scene,
            "max_length": self.client.max_token_length
        })
        
        response = response.split("[end]")[0]
        
        response = util.replace_exposition_markers(response)
        response = util.clean_dialogue(response, main_name=character.name)        
        response = util.strip_partial_sentences(response)
        
        return response
        
    @set_processing
    async def fix_exposition(self, content:str, character:Character):
        """
        Edits a text to make sure all narrative exposition and emotes is encased in *
        """
        
        if not self.actions["fix_exposition"].enabled:
            return content
        
        if not character.is_player:
            if '"' not in content and '*' not in content:
                content = util.strip_partial_sentences(content)
                character_prefix = f"{character.name}: "
                message = content.split(character_prefix)[1]
                content = f"{character_prefix}*{message.strip('*')}*"
                return content
            elif '"' in content and '*' in content:
                # if both are present we strip the * and add them back later
                # through ensure_dialog_format - right now most LLMs aren't
                # smart enough to do quotes and italics at the same time
                content = content.replace('*', '')
        
        content = util.clean_dialogue(content, main_name=character.name)        
        content = util.strip_partial_sentences(content)
        content = util.ensure_dialog_format(content, talking_character=character.name)
        
        return content
    
    @set_processing
    async def fix_exposition_on_narrator(self, content:str):
        
        if not self.actions["fix_exposition"].enabled:
            return content
        
        if not self.actions["fix_exposition"].config["narrator"].value:
            return content
        
        content = util.strip_partial_sentences(content)
        
        if '"' not in content:
            content = f"*{content.strip('*')}*"
        else:
            content = util.ensure_dialog_format(content)
               
        return content
    
    @set_processing
    async def add_detail(self, content:str, character:Character):
        """
        Edits a text to increase its length and add extra detail and exposition
        """
        
        if not self.actions["add_detail"].enabled:
            return content
        
        response = await Prompt.request("editor.add-detail", self.client, "edit_add_detail", vars={
            "content": content,
            "character": character,
            "scene": self.scene,
            "max_length": self.client.max_token_length
        })
        
        response = util.replace_exposition_markers(response)
        response = util.clean_dialogue(response, main_name=character.name)        
        response = util.strip_partial_sentences(response)
        
        return response