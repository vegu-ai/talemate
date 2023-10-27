from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import talemate.data_objects as data_objects
import talemate.util as util
import talemate.emit.async_signals
from talemate.prompts import Prompt
from talemate.scene_message import DirectorMessage, TimePassageMessage

from .base import Agent, set_processing, AgentAction
from .registry import register

import structlog

import time
import re

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character, Scene
    from talemate.agents.conversation import ConversationAgentEmission

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
        self.is_enabled = False
        self.actions = {
            "edit_dialogue": AgentAction(enabled=False, label="Edit dialogue", description="Will attempt to improve the quality of dialogue based on the character and scene. Runs automatically after each AI dialogue."),
            "fix_exposition": AgentAction(enabled=True, label="Fix exposition", description="Will attempt to fix exposition and emotes, making sure they are displayed in italics. Runs automatically after each AI dialogue."),
            "add_detail": AgentAction(enabled=True, label="Add detail", description="Will attempt to add extra detail and exposition to the dialogue. Runs automatically after each AI dialogue.")
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
        
        response = await Prompt.request("editor.fix-exposition", self.client, "edit_fix_exposition", vars={
            "content": content,
            "character": character,
            "scene": self.scene,
            "max_length": self.client.max_token_length
        })
        
        response = util.clean_dialogue(response, main_name=character.name)        
        response = util.strip_partial_sentences(response)
        #response = util.mark_exposition(response, talking_character=character.name)
        
        return response
    
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