import json
import re
import random
from typing import TYPE_CHECKING, Tuple
import dataclasses
import traceback
import uuid
import pydantic
import structlog

import talemate.util as util
from talemate.agents.base import set_processing
from talemate.emit import emit
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.prompts.base import StripMode
from talemate.util.response import extract_list
from talemate.scene_message import CharacterMessage
from talemate.world_state.templates import (
    AnnotatedTemplate,
    GenerationOptions,
    Spices,
    WritingStyle,
)
from talemate.changelog import write_reconstructed_scene
from talemate.save import SceneEncoder
import os
from talemate.agents.base import AgentAction, AgentActionConfig, AgentTemplateEmission
import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene


log = structlog.get_logger("talemate.creator.assistant")


# EVENTS

async_signals.register(
    "agent.creator.contextual_generate.before",
    "agent.creator.contextual_generate.after",
    "agent.creator.autocomplete.before",
    "agent.creator.autocomplete.after",
)


@dataclasses.dataclass
class ContextualGenerateEmission(AgentTemplateEmission):
    """
    A context for generating content.
    """

    content_generation_context: "ContentGenerationContext | None" = None
    character: "Character | None" = None

    @property
    def context_type(self) -> str:
        return self.content_generation_context.computed_context[0]

    @property
    def context_name(self) -> str:
        return self.content_generation_context.computed_context[1]


@dataclasses.dataclass
class AutocompleteEmission(AgentTemplateEmission):
    """
    A context for generating content.
    """

    input: str = ""
    type: str = ""
    character: "Character | None" = None


class ContentGenerationContext(pydantic.BaseModel):
    """
    A context for generating content.
    """

    # character attribute:Attribute name
    # character detail:Detail name
    # character dialogue:
    # scene intro:
    context: str
    instructions: str = ""
    information: str = ""
    length: int = 100
    character: str | None = None
    original: str | None = None
    partial: str = ""
    uid: str | None = None
    generation_options: GenerationOptions = pydantic.Field(
        default_factory=GenerationOptions
    )
    template: AnnotatedTemplate | None = None
    context_aware: bool = True
    history_aware: bool = True
    allow_partial: bool = True
    state: dict[str, int | str | float | bool] = pydantic.Field(default_factory=dict)

    @property
    def computed_context(self) -> Tuple[str, str]:
        typ, context = self.context.split(":", 1)
        return typ, context

    @property
    def scene(self) -> "Scene":
        return get_agent("creator").scene

    @property
    def spice(self) -> str:
        spice_level = self.generation_options.spice_level

        if self.template and not getattr(self.template, "supports_spice", False):
            # template supplied that doesn't support spice
            return ""

        if spice_level == 0:
            # no spice
            return ""

        if not self.generation_options.spices:
            # no spices
            return ""

        # randomly determine if we should add spice (0.0 - 1.0)
        if random.random() > spice_level:
            return ""

        spice = self.generation_options.spices.render(self.scene, self.character)

        log.debug(
            "spice_applied",
            spice=spice,
            uid=self.uid,
            character=self.character,
            context=self.computed_context,
        )

        emit(
            "spice_applied",
            websocket_passthrough=True,
            data={
                "spice": spice,
                "uid": self.uid,
                "character": self.character,
                "context": self.computed_context,
            },
        )

        return spice

    @property
    def style(self):
        if self.template and not getattr(self.template, "supports_style", False):
            # template supplied that doesn't support style
            return ""

        if not self.generation_options.writing_style:
            # no writing style
            return ""

        return self.generation_options.writing_style.render(self.scene, self.character)

    def set_state(self, key: str, value: str | int | float | bool):
        self.state[key] = value

    def get_state(self, key: str) -> str | int | float | bool | None:
        return self.state.get(key)


class AssistantMixin:
    """
    Creator mixin that allows quick contextual generation of content.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["autocomplete"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Autocomplete",
            icon="mdi-auto-fix",
            description="Controls settings for autocomplete suggestions.",
            config={
                "dialogue_suggestion_length": AgentActionConfig(
                    type="number",
                    label="Dialogue Suggestion Length",
                    description="Length of the generated suggestion when using autocomplete for dialogue.",
                    value=64,
                    min=32,
                    max=256,
                    step=16,
                ),
                "narrative_suggestion_length": AgentActionConfig(
                    type="number",
                    label="Narrative Suggestion Length",
                    description="Length of the generated suggestion when using autocomplete for narrative.",
                    value=96,
                    min=32,
                    max=256,
                    step=16,
                ),
            },
        )

    # property helpers

    @property
    def autocomplete_dialogue_suggestion_length(self):
        return self.actions["autocomplete"].config["dialogue_suggestion_length"].value

    @property
    def autocomplete_narrative_suggestion_length(self):
        return self.actions["autocomplete"].config["narrative_suggestion_length"].value

    # actions

    async def contextual_generate_from_args(
        self,
        context: str,
        instructions: str = "",
        length: int = 100,
        character: str | None = None,
        original: str | None = None,
        partial: str = "",
        uid: str | None = None,
        writing_style: WritingStyle | None = None,
        spices: Spices | None = None,
        spice_level: float = 0.0,
        template: AnnotatedTemplate | None = None,
        context_aware: bool = True,
        history_aware: bool = True,
        information: str = "",
        **kwargs,
    ):
        """
        Request content from the assistant.
        """

        if not writing_style:
            writing_style = self.scene.writing_style

        generation_options = GenerationOptions(
            spices=spices,
            spice_level=spice_level,
            writing_style=writing_style,
        )

        generation_context = ContentGenerationContext(
            context=context,
            instructions=instructions,
            length=length,
            character=character,
            original=original,
            partial=partial,
            uid=uid,
            generation_options=generation_options,
            template=template,
            context_aware=context_aware,
            history_aware=history_aware,
            information=information,
        )

        for key, value in kwargs.items():
            generation_context.set_state(key, value)

        return await self.contextual_generate(generation_context)

    @set_processing
    async def contextual_generate(
        self,
        generation_context: ContentGenerationContext,
    ):
        """
        Request content from the assistant.
        """

        context_typ, context_name = generation_context.computed_context
        editor = get_agent("editor")

        kind = f"create_{generation_context.length}"

        log.debug(
            f"Contextual generate: {context_typ} - {context_name}",
            generation_context=generation_context,
        )

        character = (
            self.scene.get_character(generation_context.character)
            if generation_context.character
            else None
        )

        template_vars = {
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "generation_context": generation_context,
            "context_typ": context_typ,
            "context_name": context_name,
            "can_coerce": self.client.can_be_coerced,
            "character_name": generation_context.character,
            "context_aware": generation_context.context_aware,
            "history_aware": generation_context.history_aware,
            "character": character,
            "template": generation_context.template,
        }

        emission = ContextualGenerateEmission(
            agent=self,
            content_generation_context=generation_context,
            character=character,
            template_vars=template_vars,
        )

        await async_signals.get("agent.creator.contextual_generate.before").send(
            emission
        )

        template_vars["dynamic_instructions"] = emission.dynamic_instructions

        content = await Prompt.request(
            "creator.contextual-generate",
            self.client,
            kind,
            vars=template_vars,
        )

        emission.response = content

        if not generation_context.partial:
            content = util.strip_partial_sentences(content)

        if context_typ == "list":
            try:
                content = json.dumps(extract_list(content), indent=2)
            except Exception as e:
                log.warning("Failed to extract list", error=e)
                content = "[]"
        elif context_typ == "character dialogue":
            if not content.startswith(generation_context.character + ":"):
                content = generation_context.character + ": " + content
            content = util.strip_partial_sentences(content)

            character = self.scene.get_character(generation_context.character)

            if not character:
                log.warning(
                    "Character not found", character=generation_context.character
                )
                return content

            emission.response = await editor.cleanup_character_message(
                content, character
            )
            await async_signals.get("agent.creator.contextual_generate.after").send(
                emission
            )
            return emission.response

        if content.lower().startswith(context_name + ": "):
            content = content[len(context_name) + 2 :]

        emission.response = content.strip().strip("*").strip()

        await async_signals.get("agent.creator.contextual_generate.after").send(
            emission
        )
        return emission.response

    @set_processing
    async def generate_character_attribute(
        self,
        character: "Character",
        attribute_name: str,
        instructions: str = "",
        original: str | None = None,
        length: int = 192,
        generation_options: GenerationOptions = None,
    ) -> str:
        """
        Wrapper for contextual_generate that generates a character attribute.
        """
        if not generation_options:
            generation_options = GenerationOptions()

        return await self.contextual_generate_from_args(
            context=f"character attribute:{attribute_name}",
            character=character.name,
            instructions=instructions,
            original=original,
            length=length,
            **generation_options.model_dump(),
        )

    @set_processing
    async def generate_character_detail(
        self,
        character: "Character",
        detail_name: str,
        instructions: str = "",
        original: str | None = None,
        length: int = 512,
        generation_options: GenerationOptions = None,
    ) -> str:
        """
        Wrapper for contextual_generate that generates a character detail.
        """

        if not generation_options:
            generation_options = GenerationOptions()

        return await self.contextual_generate_from_args(
            context=f"character detail:{detail_name}",
            character=character.name,
            instructions=instructions,
            original=original,
            length=length,
            **generation_options.model_dump(),
        )

    @set_processing
    async def generate_scene_title(
        self,
        instructions: str = "",
        length: int = 20,
        generation_options: GenerationOptions = None,
    ) -> str:
        """
        Wrapper for contextual_generate that generates a scene title.
        """
        if not generation_options:
            generation_options = GenerationOptions()

        title = await self.contextual_generate_from_args(
            context="scene title:scene title",
            instructions=instructions,
            length=length,
            **generation_options.model_dump(),
        )

        # replace special characters
        title = re.sub(r"[^a-zA-Z0-9\s-]", "", title)
        if title.lower().startswith("scene title "):
            title = title[11:]

        return title.split("\n")[0].strip()

    @set_processing
    async def generate_thematic_list(
        self,
        instructions: str,
        iterations: int = 1,
        length: int = 256,
        generation_options: GenerationOptions = None,
    ) -> list[str]:
        """
        Wrapper for contextual_generate that generates a list of items.
        """
        if not generation_options:
            generation_options = GenerationOptions()

        i = 0

        result = []

        while i < iterations:
            i += 1
            _result = await self.contextual_generate_from_args(
                context="list:",
                instructions=instructions,
                length=length,
                original="\n".join(result) if result else None,
                extend=i > 1,
                **generation_options.model_dump(),
            )

            _result = json.loads(_result)

            result = list(set(result + _result))

        return result

    @set_processing
    async def autocomplete_dialogue(
        self,
        input: str,
        character: "Character",
        emit_signal: bool = True,
        response_length: int | None = None,
    ) -> str:
        """
        Autocomplete dialogue.
        """
        if not response_length:
            response_length = self.autocomplete_dialogue_suggestion_length

        # continuing recent character message
        non_anchor, anchor = util.split_anchor_text(input, 10)

        self.scene.log.debug(
            "autocomplete_anchor", anchor=anchor, non_anchor=non_anchor, input=input
        )

        continuing_message = False
        message = None

        try:
            message = self.scene.history[-1]
            if (
                isinstance(message, CharacterMessage)
                and message.character_name == character.name
            ):
                continuing_message = input.strip() == message.without_name.strip()
        except IndexError:
            pass

        outvar = {
            "tag_name": "CONTINUE",
        }

        def set_tag_name(tag_name: str) -> str:
            outvar["tag_name"] = tag_name
            return tag_name

        template_vars = {
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "input": input.strip(),
            "character": character,
            "can_coerce": self.client.can_be_coerced,
            "response_length": response_length,
            "continuing_message": continuing_message,
            "message": message,
            "anchor": anchor,
            "non_anchor": non_anchor,
            "set_tag_name": set_tag_name,
        }

        emission = AutocompleteEmission(
            agent=self,
            input=input,
            type="dialogue",
            character=character,
            template_vars=template_vars,
        )

        await async_signals.get("agent.creator.autocomplete.before").send(emission)

        template_vars["dynamic_instructions"] = emission.dynamic_instructions

        response = await Prompt.request(
            "creator.autocomplete-dialogue",
            self.client,
            f"create_{response_length}",
            vars=template_vars,
            pad_prepended_response=False,
            dedupe_enabled=False,
            strip_mode=StripMode.RIGHT,
        )

        # attempt to extract the continuation from the response
        try:
            tag_name = outvar["tag_name"]
            response = (
                response.split(f"<{tag_name}>")[1].split(f"</{tag_name}>")[0].rstrip()
            )
        except IndexError:
            pass

        response = (
            response.replace("...", "").lstrip("").rstrip().replace("END-OF-LINE", "")
        )

        emission.response = response

        await async_signals.get("agent.creator.autocomplete.after").send(emission)

        if not response:
            if emit_signal:
                emit("autocomplete_suggestion", "")
            return ""

        response = util.strip_partial_sentences(response).replace("*", "")

        if response.startswith(input):
            response = response[len(input) :]

        self.scene.log.debug(
            "autocomplete_suggestion", suggestion=response, input=input
        )

        if emit_signal:
            emit("autocomplete_suggestion", response)

        return response

    @set_processing
    async def autocomplete_narrative(
        self,
        input: str,
        emit_signal: bool = True,
        response_length: int | None = None,
    ) -> str:
        """
        Autocomplete narrative.
        """
        if not response_length:
            response_length = self.autocomplete_narrative_suggestion_length

        # Split the input text into non-anchor and anchor parts
        non_anchor, anchor = util.split_anchor_text(input, 10)

        self.scene.log.debug(
            "autocomplete_narrative_anchor",
            anchor=anchor,
            non_anchor=non_anchor,
            input=input,
        )

        outvar = {
            "tag_name": "CONTINUE",
        }

        def set_tag_name(tag_name: str) -> str:
            outvar["tag_name"] = tag_name
            return tag_name

        template_vars = {
            "scene": self.scene,
            "max_tokens": self.client.max_token_length,
            "input": input.strip(),
            "can_coerce": self.client.can_be_coerced,
            "response_length": response_length,
            "anchor": anchor,
            "non_anchor": non_anchor,
            "set_tag_name": set_tag_name,
        }

        emission = AutocompleteEmission(
            agent=self,
            input=input,
            type="narrative",
            template_vars=template_vars,
        )

        await async_signals.get("agent.creator.autocomplete.before").send(emission)

        template_vars["dynamic_instructions"] = emission.dynamic_instructions

        response = await Prompt.request(
            "creator.autocomplete-narrative",
            self.client,
            f"create_{response_length}",
            vars=template_vars,
            pad_prepended_response=False,
            dedupe_enabled=False,
            strip_mode=StripMode.RIGHT,
        )

        # attempt to extract the continuation from the response
        try:
            tag_name = outvar["tag_name"]
            response = (
                response.split(f"<{tag_name}>")[1].split(f"</{tag_name}>")[0].rstrip()
            )
        except IndexError:
            pass

        response = response.replace("...", "").rstrip()

        if response.startswith(input):
            response = response[len(input) :]

        emission.response = response

        await async_signals.get("agent.creator.autocomplete.after").send(emission)

        self.scene.log.debug(
            "autocomplete_suggestion", suggestion=response, input=input
        )

        if emit_signal:
            emit("autocomplete_suggestion", response)

        return response

    @set_processing
    async def fork_scene(
        self,
        message_id: int,
        save_name: str | None = None,
    ):
        """
        Creates a new scene forked from a specific message.

        This properly creates a new scene file without modifying the current scene,
        then signals the frontend to load the new scene.
        """
        try:
            emit("status", "Preparing to fork scene...", status="busy")

            if not save_name:
                save_name = self.scene.generate_name()

            # Find the message to fork from
            message = self.scene.get_message(message_id)
            if not message:
                raise ValueError(f"Message with id {message_id} not found.")

            # Determine fork type based on message revision
            use_reconstructive_fork = message.rev > 0

            if use_reconstructive_fork:
                log.info(
                    "Creating reconstructive fork",
                    message_id=message_id,
                    rev=message.rev,
                )
                emit("status", "Creating reconstructive fork...", status="busy")

                # Create fork file with reconstructed scene data (shared_context will be disconnected)
                fork_file_path = await write_reconstructed_scene(
                    self.scene,
                    message.rev,
                    f"{save_name}.json",
                    overrides={
                        "immutable_save": False,
                        "memory_id": str(uuid.uuid4())[:10],
                    },
                )

                log.info(
                    "Reconstructive fork created",
                    save_name=save_name,
                    rev=message.rev,
                    path=fork_file_path,
                )
            else:
                log.info("Creating shallow fork", message_id=message_id)
                emit("status", "Creating shallow fork...", status="busy")

                # Create a copy of current scene data
                scene_data = self.scene.serialize

                scene_data["immutable_save"] = False
                scene_data["memory_id"] = str(uuid.uuid4())[:10]

                # Truncate history to the fork point
                index = self.scene.message_index(message_id)
                if index is None:
                    raise ValueError(f"Message with id {message_id} not found.")

                # Truncate history (keeping index as the last element)
                scene_data["history"] = self.scene.history[: index + 1]

                # Truncate archived_history (keeping elements where 'end' < index)
                scene_data["archived_history"] = [
                    x
                    for x in self.scene.archived_history
                    if "end" not in x or x["end"] < index
                ]

                # Truncate layered history (same logic as original)
                new_layered_history = []
                for layer_number, layer in enumerate(self.scene.layered_history):
                    if layer_number == 0:
                        layer_index = len(scene_data["archived_history"]) - 1
                    else:
                        layer_index = len(new_layered_history[layer_number - 1]) - 1

                    new_layer = [x for x in layer if x["end"] < layer_index]
                    new_layered_history.append(new_layer)

                scene_data["layered_history"] = new_layered_history

                # Clear shared_context for fork (same logic as reconstructive fork)
                if scene_data.get("shared_context"):
                    log.info(
                        "Disconnecting forked scene from shared_context",
                        shared_context=scene_data.get("shared_context"),
                    )
                    scene_data["shared_context"] = ""

                # Write the fork file
                fork_file_path = os.path.join(self.scene.save_dir, f"{save_name}.json")
                with open(fork_file_path, "w") as f:
                    json.dump(scene_data, f, indent=2, cls=SceneEncoder)

                log.info(
                    "Shallow fork created", save_name=save_name, path=fork_file_path
                )

            emit("status", "Scene forked successfully", status="success")

            # Return the fork file path so the websocket handler can load it
            return fork_file_path

        except Exception:
            log.error("Scene fork failed", exc=traceback.format_exc())
            emit("status", "Scene fork failed", status="error")
