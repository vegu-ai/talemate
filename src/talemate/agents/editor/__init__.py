from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

import talemate.emit.async_signals
import talemate.util as util
from talemate.prompts import Prompt

from talemate.agents.base import Agent, AgentAction, AgentActionConfig, set_processing
from talemate.agents.registry import register

import talemate.agents.editor.nodes

from talemate.agents.editor.revision import RevisionMixin

if TYPE_CHECKING:
    from talemate.agents.conversation import ConversationAgentEmission
    from talemate.agents.narrator import NarratorAgentEmission
    from talemate.tale_mate import Character

log = structlog.get_logger("talemate.agents.editor")


@register()
class EditorAgent(
    RevisionMixin,
    Agent,
):
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
                can_be_disabled=True,
                label="Fix exposition",
                description="Attempt to fix exposition and emotes, making sure they are displayed in italics. Runs automatically after each AI dialogue.",
                config={
                    "formatting": AgentActionConfig(
                        type="text",
                        label="Formatting",
                        description="The formatting to use for exposition.",
                        value="chat",
                        choices=[
                            {"label": "Chat RP: \"Speech\" *narration*", "value": "chat"},
                            {"label": "Novel: \"Speech\" narration", "value": "novel"},
                        ]
                    ),
                    "narrator": AgentActionConfig(
                        type="bool",
                        label="Fix narrator messages",
                        description="Attempt to fix exposition issues in narrator messages",
                        value=True,
                    ),
                    "user_input": AgentActionConfig(
                        type="bool",
                        label="Fix user input",
                        description="Attempt to fix exposition issues in user input",
                        value=True,
                    ),
                },
            ),
            "add_detail": AgentAction(
                enabled=False,
                can_be_disabled=True,
                label="Add detail",
                description="Attempt to add extra detail and exposition to the dialogue. Runs automatically after each AI dialogue.",
            ),
        }
        
        RevisionMixin.add_actions(self)

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
        elif self.fix_exposition_formatting == "novel":
            text = text.replace("*", "")
            text = text.replace("[", "").replace("]", "")
            text = text.replace("(", "").replace(")", "")
        
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
    async def cleanup_character_message(self, content: str, character: Character, force: bool = False):
        """
        Edits a text to make sure all narrative exposition and emotes is encased in *
        """
        
        # if not content was generated, return it as is
        if not content:
            return content

        exposition_fixed = False

        if (not character.is_player and self.fix_exposition_enabled) or force:
            content = self.fix_exposition_in_text(content, character)
            exposition_fixed = True
            if self.fix_exposition_formatting == "chat":
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
        
        # if there are uneven quotation marks, fix them by adding a closing quote
        if '"' in content and content.count('"') % 2 != 0:
            content += '"'
        
        if not self.fix_exposition_enabled and not exposition_fixed:
            return content
        
        content = self.fix_exposition_in_text(content, character)

        return content

    @set_processing
    async def clean_up_narration(self, content: str, force: bool = False):
        content = util.strip_partial_sentences(content)
        if (self.fix_exposition_enabled and self.fix_exposition_narrator or force):
            content = self.fix_exposition_in_text(content, None)
            if self.fix_exposition_formatting == "chat":
                if '"' not in content and "*" not in content:
                    content = f"*{content.strip('*')}*"

        return content

    @set_processing
    async def cleanup_user_input(self, text: str, as_narration: bool = False, force: bool = False):
        if (not self.fix_exposition_user_input or not self.fix_exposition_enabled) and not force:
            return text
        
        if not as_narration:
            if self.fix_exposition_formatting == "chat":
                if '"' not in text and "*" not in text:
                    text = f'"{text}"'
        else:
            return await self.clean_up_narration(text)
        
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