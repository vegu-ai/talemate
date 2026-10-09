from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import pydantic
import structlog

import talemate.client as client
import talemate.emit.async_signals
import talemate.util as util
from talemate.events import before_generation
from talemate.client.context import (
    client_context_attribute,
    set_client_context_attribute,
    set_conversation_context_attribute,
)
from talemate.exceptions import ControlFlowException
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage
from talemate.agents.utils import handle_empty_response_limit
from talemate.ux.schema import Action

from talemate.agents.base import (
    Agent,
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    AgentDetail,
    AgentEmission,
    DynamicInstruction,
    optimize_prompt_caching_action,
    set_processing,
    store_context_state,
)
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.agents.conversation.knowledge import CharacterKnowledgeMixin
from talemate.agents.context import active_agent

from .websocket_handler import ConversationWebsocketHandler
import talemate.agents.conversation.nodes  # noqa: F401

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character

log = structlog.get_logger("talemate.agents.conversation")


class ConversationAgentEmission(AgentEmission):
    actor: "Actor | None" = None
    character: "Character"
    response: str
    dynamic_instructions: list[DynamicInstruction] = pydantic.Field(
        default_factory=list
    )
    avatar: str | None = None
    message_ids: list[int] = pydantic.Field(default_factory=list)


talemate.emit.async_signals.register(
    "agent.conversation.before_generate",
    "agent.conversation.inject_instructions",
    "agent.conversation.generated",
    "agent.conversation.finalized",
)


@register()
class ConversationAgent(CharacterKnowledgeMixin, MemoryRAGMixin, Agent):
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
            "prompt_caching": optimize_prompt_caching_action(),
            "generation_override": AgentAction(
                enabled=True,
                container=True,
                icon="mdi-atom-variant",
                label="Generation",
                note=AgentActionNote(
                    icon="mdi-information-outline",
                    color="primary",
                    text="The scene context format (Screenplay, Chat, Narrative, AI Aware) moved to the Summarizer agent's Scene History section. It applies to the scene context of every agent.",
                    actions=[
                        Action(
                            action_name="openAgentSettings",
                            arguments=["summarizer", "manage_scene_history"],
                            label="Open Scene History",
                            icon="mdi-arrow-split-vertical",
                        )
                    ],
                ),
                config={
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
                    "inject_character_names_into_stop": AgentActionConfig(
                        type="bool",
                        label="Include character names in stop tokens",
                        value=True,
                        description="Some models may generate the names of other characters during internal reasoning, which can cause generation to stop (for example, GLM 4.7 Flash). If you experience sudden generation stops, try disabling this option.",
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
        CharacterKnowledgeMixin.add_actions(actions)
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
    def agent_details(self) -> dict:
        details = {
            "client": AgentDetail(
                icon="mdi-network-outline",
                value=self.client.name if self.client else None,
                description="The client to use for prompt generation",
            ).model_dump(),
        }

        return details

    @property
    def generation_settings_task_instructions(self):
        return self.resolve_config("generation_override", "instructions")

    @property
    def generation_settings_actor_instructions(self):
        return self.resolve_config("generation_override", "actor_instructions")

    @property
    def inject_character_names_into_stop(self) -> bool:
        return self.resolve_config(
            "generation_override", "inject_character_names_into_stop"
        )

    @property
    def generation_settings_actor_instructions_offset(self):
        return self.resolve_config("generation_override", "actor_instructions_offset")

    @property
    def generation_settings_response_length(self):
        return self.resolve_config("generation_override", "length")

    @property
    def generation_settings_override_enabled(self):
        return self.resolve_enabled("generation_override")

    @property
    def content_use_scene_intent(self) -> bool:
        return self.resolve_config("content", "use_scene_intent")

    @property
    def content_use_writing_style(self) -> bool:
        return self.resolve_config("content", "use_writing_style")

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
        scene = character.actor.scene

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

        conversation_format = scene.conversation_format
        prompt = Prompt.get(
            f"conversation.dialogue-{conversation_format}",
            vars={
                "scene": scene,
                "max_tokens": self.client.max_token_length,
                "memory": None,  # DEPRECATED VARIABLE
                "characters": list(scene.get_characters()),
                "main_character": main_character,
                "formatted_names": formatted_names,
                "talking_character": character,
                "knowledge_index": KnowledgeIndex.from_scene(scene),
                "knowledge_viewer": self.rag_knowledge_viewer(character),
                "partial_message": char_message,
                "extra_instructions": self.generation_settings_task_instructions,  # backward compatibility
                "task_instructions": self.generation_settings_task_instructions,
                "actor_instructions": self.generation_settings_actor_instructions,
                "actor_instructions_offset": self.generation_settings_actor_instructions_offset,
                "direct_instruction": instruction,
                "decensor": self.client.decensor_enabled,
                "response_length": (
                    self.generation_settings_response_length
                    if self.generation_settings_override_enabled
                    else None
                ),
            },
        )

        return prompt

    async def build_prompt(
        self, character, char_message: str = "", instruction: str = None
    ):
        fn = self.build_prompt_default

        return await fn(character, char_message=char_message, instruction=instruction)

    def clean_result(self, result, character):
        if not result:
            return ""

        if "#" in result:
            result = result.split("#")[0]

        if "(Internal" in result:
            result = result.split("(Internal")[0]

        result = result.replace(" :", ":")

        result = util.handle_endofline_special_delimiter(result)
        result = util.remove_trailing_markers(result)

        return result

    def set_generation_overrides(self):
        set_conversation_context_attribute(
            "inject_character_names", self.inject_character_names_into_stop
        )

        if not self.resolve_enabled("generation_override"):
            return

        set_conversation_context_attribute(
            "length", self.resolve_config("generation_override", "length")
        )

        jiggle = self.resolve_config("generation_override", "jiggle")
        if jiggle > 0.0:
            nuke_repetition = client_context_attribute("nuke_repetition")
            if nuke_repetition == 0.0:
                # we only apply the agent override if some other mechanism isn't already
                # setting the nuke_repetition value
                set_client_context_attribute("nuke_repetition", jiggle)

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

        await before_generation(self.scene, "conversation")

        emission = ConversationAgentEmission(
            agent=self, response="", actor=actor, character=character
        )
        await talemate.emit.async_signals.get(
            "agent.conversation.before_generate"
        ).send(emission)

        self.set_generation_overrides()

        self.clear_memory_pass_record()
        prompt = await self.build_prompt(character, instruction=instruction)
        response, extracted = await prompt.send(self.client, kind="conversation")
        memory_pass = self.take_memory_pass_record()
        result = extracted["response"]

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

        scene = character.actor.scene
        conversation_format = scene.conversation_format
        other_names = [n for n in scene.character_names if n != character.name]

        if conversation_format == "narrative":
            # For narrative format, the LLM generates pure prose without character name prefixes
            # We need to store it internally in the standard {name}: {text} format
            total_result = util.clean_dialogue(
                total_result, main_name=character.name, other_names=other_names
            )
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
            total_result = util.clean_dialogue(
                total_result, main_name=character.name, other_names=other_names
            )

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
        messages[0]._avatar_pending = emit_signals
        messages[0].set_memory_pass(memory_pass)
        return messages

    async def finalize_message_avatar(self, message: CharacterMessage):
        if not message._avatar_pending:
            return
        message._avatar_pending = False
        scene = self.scene
        character = scene.get_character(message.character_name)
        if character is None:
            return
        emission = ConversationAgentEmission(
            agent=self,
            actor=character.actor,
            character=character,
            response=message.message,
            message_ids=[message.id],
        )
        try:
            await talemate.emit.async_signals.get("agent.conversation.finalized").send(
                emission
            )
            if self.scene is not scene or scene.get_message(message.id) is not message:
                return
            if emission.avatar and emission.avatar != message.asset_id:
                await scene.assets.update_message_asset(message.id, emission.avatar)
        except ControlFlowException:
            raise
        except Exception:
            log.exception(
                "finalize_message_avatar: attachment failed", message_id=message.id
            )

    def allow_repetition_break(
        self, kind: str, agent_function_name: str, auto: bool = False
    ):
        return agent_function_name == "converse"
