from __future__ import annotations

import dataclasses
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import structlog

import talemate.client as client
import talemate.emit.async_signals
import talemate.util as util
from talemate.client.context import (
    client_context_attribute,
    set_client_context_attribute,
    set_conversation_context_attribute,
)
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, DirectorMessage
from talemate.agents.utils import handle_empty_response_limit

from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    AgentDetail,
    AgentEmission,
    DynamicInstruction,
    set_processing,
    store_context_state,
)
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin
from talemate.agents.context import active_agent

from .websocket_handler import ConversationWebsocketHandler
import talemate.agents.conversation.nodes  # noqa: F401

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character

log = structlog.get_logger("talemate.agents.conversation")


@dataclasses.dataclass
class ConversationAgentEmission(AgentEmission):
    actor: Actor
    character: Character
    response: str
    dynamic_instructions: list[DynamicInstruction] = dataclasses.field(
        default_factory=list
    )
    avatar: str | None = None


talemate.emit.async_signals.register(
    "agent.conversation.before_generate",
    "agent.conversation.inject_instructions",
    "agent.conversation.generated",
)


@register()
class ConversationAgent(MemoryRAGMixin, Agent):
    """
    An agent that can be used to have a conversation with the AI

    Ideally used with a Pygmalion or GPT >= 3.5 model
    """

    agent_type = "conversation"
    verbose_name = "Conversation"

    min_dialogue_length = 75
    websocket_handler = ConversationWebsocketHandler

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {
            "generation_override": AgentAction(
                enabled=True,
                container=True,
                icon="mdi-atom-variant",
                label="Generation",
                config={
                    "format": AgentActionConfig(
                        type="text",
                        label="Format",
                        description="The generation format of the scene progression, as seen by the AI. Has no direct effect on your view of the scene, but will affect the way the AI perceives the scene and its characters, leading to changes in the response, for better or worse.",
                        choices=[
                            {"label": "Screenplay", "value": "movie_script"},
                            {"label": "Chat (legacy)", "value": "chat"},
                            {
                                "label": "Narrative (NEW, experimental)",
                                "value": "narrative",
                            },
                        ],
                        value="movie_script",
                        note_on_value={
                            "narrative": AgentActionNote(
                                color="primary",
                                text="Will attempt to generate flowing, novel-like prose with scene intent awareness and character goal consideration. A reasoning model is STRONGLY recommended. Experimental and more prone to generate out of turn character actions and dialogue.",
                            )
                        },
                    ),
                    "length": AgentActionConfig(
                        type="number",
                        label="Generation Length (tokens)",
                        description="Maximum number of tokens to generate for a conversation response.",
                        value=192,
                        min=32,
                        max=4096,
                        step=32,
                    ),
                    "jiggle": AgentActionConfig(
                        type="number",
                        label="Jiggle (Increased Randomness)",
                        description="If > 0.0 will cause certain generation parameters to have a slight random offset applied to them. The bigger the number, the higher the potential offset.",
                        value=0.0,
                        min=0.0,
                        max=1.0,
                        step=0.1,
                    ),
                    "instructions": AgentActionConfig(
                        type="blob",
                        label="Task Instructions",
                        value="",
                        description="Allows to extend the task instructions - placed above the context history.",
                    ),
                    "actor_instructions": AgentActionConfig(
                        type="blob",
                        label="Actor Instructions",
                        value="",
                        description="Allows to extend the actor instructions - placed towards the end of the context history.",
                    ),
                    "actor_instructions_offset": AgentActionConfig(
                        type="number",
                        label="Actor Instructions Offset",
                        value=3,
                        description="Offsets the actor instructions into the context history, shifting it up N number of messages. 0 = at the end of the context history.",
                        min=0,
                        max=20,
                        step=1,
                    ),
                },
            ),
            "content": AgentAction(
                enabled=True,
                can_be_disabled=False,
                container=True,
                label="Content",
                icon="mdi-script-text",
                description="Content control settings",
                config={
                    "use_scene_intent": AgentActionConfig(
                        type="bool",
                        label="Use Scene Intent",
                        description="Include the scene intent in the prompt",
                        value=True,
                    ),
                    "use_writing_style": AgentActionConfig(
                        type="bool",
                        label="Use Writing Style",
                        description="Use the writing style selected in the scene settings",
                        value=True,
                    ),
                },
            ),
        }
        MemoryRAGMixin.add_actions(actions)
        return actions

    def __init__(
        self,
        client: client.ClientBase | None = None,
        kind: Optional[str] = "pygmalion",
        logging_enabled: Optional[bool] = True,
        **kwargs,
    ):
        self.client = client
        self.kind = kind
        self.logging_enabled = logging_enabled
        self.logging_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # several agents extend this class, but we only want to initialize
        # these actions for the conversation agent

        if self.agent_type != "conversation":
            return

        self.actions = ConversationAgent.init_actions()

    @property
    def conversation_format(self):
        if self.actions["generation_override"].enabled:
            return self.actions["generation_override"].config["format"].value
        return "movie_script"

    @property
    def conversation_format_label(self):
        value = self.conversation_format

        choices = self.actions["generation_override"].config["format"].choices

        for choice in choices:
            if choice["value"] == value:
                return choice["label"]

        return value

    @property
    def agent_details(self) -> dict:
        details = {
            "client": AgentDetail(
                icon="mdi-network-outline",
                value=self.client.name if self.client else None,
                description="The client to use for prompt generation",
            ).model_dump(),
            "format": AgentDetail(
                icon="mdi-format-float-none",
                value=self.conversation_format_label,
                description="Generation format of the scene context, as seen by the AI",
            ).model_dump(),
        }

        return details

    @property
    def generation_settings_task_instructions(self):
        return self.actions["generation_override"].config["instructions"].value

    @property
    def generation_settings_actor_instructions(self):
        return self.actions["generation_override"].config["actor_instructions"].value

    @property
    def generation_settings_actor_instructions_offset(self):
        return (
            self.actions["generation_override"]
            .config["actor_instructions_offset"]
            .value
        )

    @property
    def generation_settings_response_length(self):
        return self.actions["generation_override"].config["length"].value

    @property
    def generation_settings_override_enabled(self):
        return self.actions["generation_override"].enabled

    @property
    def content_use_scene_intent(self) -> bool:
        return self.actions["content"].config["use_scene_intent"].value

    @property
    def content_use_writing_style(self) -> bool:
        return self.actions["content"].config["use_writing_style"].value

    def connect(self, scene):
        super().connect(scene)

    async def build_prompt_default(
        self,
        character: Character,
        char_message: Optional[str] = "",
        instruction: Optional[str] = None,
    ):
        """
        Builds the prompt that drives the AI's conversational response
        """
        # the amount of tokens we can use
        # we subtract 200 to account for the response

        scene = character.actor.scene

        total_token_budget = self.client.max_token_length - 200
        scene_and_dialogue_budget = total_token_budget - 500

        scene_and_dialogue = scene.context_history(
            budget=scene_and_dialogue_budget,
            keep_director=True,
            sections=False,
        )

        main_character = scene.main_character.character

        character_names = [c.name for c in scene.characters]

        if main_character:
            try:
                character_names.remove(main_character.name)
            except ValueError:
                pass

        if len(character_names) > 1:
            formatted_names = (
                ", ".join(character_names[:-1]) + " or " + character_names[-1]
                if character_names
                else ""
            )
        else:
            formatted_names = character_names[0] if character_names else ""

        try:
            director_message = isinstance(scene_and_dialogue[-1], DirectorMessage)
        except IndexError:
            director_message = False

        inject_instructions_emission = ConversationAgentEmission(
            agent=self,
            response="",
            actor=None,
            character=character,
        )
        await talemate.emit.async_signals.get(
            "agent.conversation.inject_instructions"
        ).send(inject_instructions_emission)

        agent_context = active_agent.get()
        agent_context.state["dynamic_instructions"] = (
            inject_instructions_emission.dynamic_instructions
        )

        conversation_format = self.conversation_format
        prompt = Prompt.get(
            f"conversation.dialogue-{conversation_format}",
            vars={
                "scene": scene,
                "max_tokens": self.client.max_token_length,
                "scene_and_dialogue_budget": scene_and_dialogue_budget,
                "scene_and_dialogue": scene_and_dialogue,
                "memory": None,  # DEPRECATED VARIABLE
                "characters": list(scene.get_characters()),
                "main_character": main_character,
                "formatted_names": formatted_names,
                "talking_character": character,
                "partial_message": char_message,
                "director_message": director_message,
                "extra_instructions": self.generation_settings_task_instructions,  # backward compatibility
                "task_instructions": self.generation_settings_task_instructions,
                "actor_instructions": self.generation_settings_actor_instructions,
                "actor_instructions_offset": self.generation_settings_actor_instructions_offset,
                "direct_instruction": instruction,
                "decensor": self.client.decensor_enabled,
                "response_length": self.generation_settings_response_length
                if self.generation_settings_override_enabled
                else None,
            },
        )

        return str(prompt)

    async def build_prompt(
        self, character, char_message: str = "", instruction: str = None
    ):
        fn = self.build_prompt_default

        return await fn(character, char_message=char_message, instruction=instruction)

    def clean_result(self, result, character):
        if "#" in result:
            result = result.split("#")[0]

        if "(Internal" in result:
            result = result.split("(Internal")[0]

        result = result.replace(" :", ":")

        result = util.handle_endofline_special_delimiter(result)
        result = util.remove_trailing_markers(result)

        return result

    def set_generation_overrides(self):
        if not self.actions["generation_override"].enabled:
            return

        set_conversation_context_attribute(
            "length", self.actions["generation_override"].config["length"].value
        )

        if self.actions["generation_override"].config["jiggle"].value > 0.0:
            nuke_repetition = client_context_attribute("nuke_repetition")
            if nuke_repetition == 0.0:
                # we only apply the agent override if some other mechanism isn't already
                # setting the nuke_repetition value
                nuke_repetition = (
                    self.actions["generation_override"].config["jiggle"].value
                )
                set_client_context_attribute("nuke_repetition", nuke_repetition)

    @set_processing
    @store_context_state("instruction")
    async def converse(
        self,
        actor,
        instruction: str = None,
        emit_signals: bool = True,
    ) -> list[CharacterMessage]:
        """
        Have a conversation with the AI
        """

        character = actor.character

        emission = ConversationAgentEmission(
            agent=self, response="", actor=actor, character=character
        )
        await talemate.emit.async_signals.get(
            "agent.conversation.before_generate"
        ).send(emission)

        self.set_generation_overrides()

        result = await self.client.send_prompt(
            await self.build_prompt(character, instruction=instruction)
        )

        result = self.clean_result(result, character)

        # Check response for emptiness - raise GenerationCancelled with troubleshooting message
        # This breaks out of the game loop and informs the user about potential causes
        if not result or result.strip() == "":
            handle_empty_response_limit("conversation", 1)

        total_result = result.replace(" :", ":")
        total_result = total_result.split("#")[0].strip()

        total_result = util.handle_endofline_special_delimiter(total_result)

        log.debug("conversation agent", total_result=total_result)

        if total_result.startswith(":\n") or total_result.startswith(": "):
            total_result = total_result[2:]

        conversation_format = self.conversation_format

        if conversation_format == "narrative":
            # For narrative format, the LLM generates pure prose without character name prefixes
            # We need to store it internally in the standard {name}: {text} format
            total_result = util.clean_dialogue(total_result, main_name=character.name)
            # Only add character name if it's not already there
            if not total_result.startswith(character.name + ":"):
                total_result = f"{character.name}: {total_result}"
        else:
            # movie script format
            # {uppercase character name}
            # {dialogue}
            # Use regex to handle optional whitespace between name and newline
            total_result = re.sub(
                rf"^{re.escape(character.name.upper())}\s*\n", "", total_result
            )

            # chat format
            # {character name}: {dialogue}
            total_result = total_result.replace(f"{character.name}:", "")

            # Removes partial sentence at the end
            total_result = util.clean_dialogue(total_result, main_name=character.name)

            # Check if total_result starts with character name, if not, prepend it
            if not total_result.startswith(character.name + ":"):
                total_result = f"{character.name}: {total_result}"

        total_result = total_result.strip()

        if total_result == "" or total_result == f"{character.name}:":
            log.warn("conversation agent", result="Empty result")

        # replace any white space betwen {charactrer.name}: and the first word with a single space
        total_result = re.sub(
            rf"{character.name}:\s+", f"{character.name}: ", total_result
        )

        response = total_result

        log.debug("conversation agent", response=response)
        emission = ConversationAgentEmission(
            agent=self,
            actor=actor,
            character=character,
            response=response,
        )
        if emit_signals:
            await talemate.emit.async_signals.get("agent.conversation.generated").send(
                emission
            )

        extra = {"from_choice": instruction}
        if emission.avatar:
            extra["asset_id"] = emission.avatar
            extra["asset_type"] = "avatar"
        elif character.current_avatar:
            extra["asset_id"] = character.current_avatar
            extra["asset_type"] = "avatar"
        messages = [CharacterMessage(emission.response, **extra)]
        return messages

    def allow_repetition_break(
        self, kind: str, agent_function_name: str, auto: bool = False
    ):
        return agent_function_name == "converse"

    def inject_prompt_paramters(
        self, prompt_param: dict, kind: str, agent_function_name: str
    ):
        if prompt_param.get("extra_stopping_strings") is None:
            prompt_param["extra_stopping_strings"] = []
        prompt_param["extra_stopping_strings"] += ["#"]
