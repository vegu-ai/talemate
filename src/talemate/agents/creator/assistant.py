import asyncio
import json
import random
import uuid
from typing import TYPE_CHECKING, Tuple, Union

import pydantic
import structlog

import talemate.util as util
from talemate.agents.base import set_processing
from talemate.emit import emit
from talemate.instance import get_agent
from talemate.prompts import Prompt
from talemate.util.response import extract_list
from talemate.world_state.templates import (
    AnnotatedTemplate,
    GenerationOptions,
    Spices,
    WritingStyle,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene


log = structlog.get_logger("talemate.creator.assistant")


class ContentGenerationContext(pydantic.BaseModel):
    """
    A context for generating content.
    """

    context: str
    instructions: str = ""
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


class AssistantMixin:
    """
    Creator mixin that allows quick contextual generation of content.
    """

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
    ):
        """
        Request content from the assistant.
        """

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
        )

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

        if generation_context.length < 100:
            kind = "create_short"
        elif generation_context.length < 500:
            kind = "create_concise"
        else:
            kind = "create"

        log.debug(
            f"Contextual generate: {context_typ} - {context_name}",
            generation_context=generation_context,
        )

        content = await Prompt.request(
            f"creator.contextual-generate",
            self.client,
            kind,
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "generation_context": generation_context,
                "context_typ": context_typ,
                "context_name": context_name,
                "can_coerce": self.client.can_be_coerced,
                "character_name": generation_context.character,
                "context_aware": generation_context.context_aware,
                "history_aware": generation_context.history_aware,
                "character": (
                    self.scene.get_character(generation_context.character)
                    if generation_context.character
                    else None
                ),
                "template": generation_context.template,
            },
        )

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
            content = await editor.fix_exposition(content, generation_context.character.name)
            return content

        return content.strip().strip("*").strip()

    @set_processing
    async def autocomplete_dialogue(
        self,
        input: str,
        character: "Character",
        emit_signal: bool = True,
    ) -> str:
        """
        Autocomplete dialogue.
        """

        response = await Prompt.request(
            f"creator.autocomplete-dialogue",
            self.client,
            "create_short",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "input": input.strip(),
                "character": character,
                "can_coerce": self.client.can_be_coerced,
            },
            pad_prepended_response=False,
            dedupe_enabled=False,
        )

        response = util.clean_dialogue(response, character.name)[
            len(character.name + ":") :
        ].strip()

        # remove ellipsis

        response = response.replace("...", "").strip()

        # if sentence starts and ends with quotes, remove them
        
        if response.startswith('"') and response.endswith('"') and not "*" in response:
            response = response[1:-1]

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
    ) -> str:
        """
        Autocomplete narrative.
        """

        response = await Prompt.request(
            f"creator.autocomplete-narrative",
            self.client,
            "create_short",
            vars={
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
                "input": input.strip(),
                "can_coerce": self.client.can_be_coerced,
            },
            pad_prepended_response=False,
            dedupe_enabled=False,
        )
        response = response.strip().replace("...", "").strip()

        if response.startswith(input):
            response = response[len(input) :]

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
        Allows to fork a new scene from a specific message
        in the current scene.
        
        All content after the message will be removed and the
        context database will be re imported ensuring a clean state.
        
        All state reinforcements will be reset to their most recent
        state before the message.
        """
        
        emit("status", "Creating scene fork ...", status="busy")
        try:
            if not save_name:
                # build a save name
                uuid_str = str(uuid.uuid4())[:8]
                save_name = f"{uuid_str}-forked"
            
            log.info(f"Forking scene", message_id=message_id, save_name=save_name)
            
            world_state = get_agent("world_state")
            
            # does a message with the given id exist?
            index = self.scene.message_index(message_id)
            if index is None:
                raise ValueError(f"Message with id {message_id} not found.")
            
            # truncate scene.history keeping index as the last element
            self.scene.history = self.scene.history[:index + 1]
            
            # truncate scene.archived_history keeping the element where `end` is < `index`
            # as the last element
            self.scene.archived_history = [
                x for x in self.scene.archived_history if "end" not in x or x["end"] < index
            ]
            
            # the same needs to be done for layered history
            # where each layer is truncated based on what's left in the previous layer
            # using similar logic as above (checking `end` vs `index`)
            # layer 0 checks archived_history
            
            new_layered_history = []
            for layer_number, layer in enumerate(self.scene.layered_history):
                
                if layer_number == 0:
                    index = len(self.scene.archived_history) - 1
                else:
                    index = len(new_layered_history[layer_number - 1]) - 1
                    
                new_layer = [
                    x for x in layer if x["end"] < index
                ]
                new_layered_history.append(new_layer)
                
            self.scene.layered_history = new_layered_history

            # save the scene
            await self.scene.save(copy_name=save_name)
            
            log.info(f"Scene forked", save_name=save_name)
            
            # re-emit history
            await self.scene.emit_history()
            
            emit("status", f"Updating world state ...", status="busy")

            # reset state reinforcements
            await world_state.update_reinforcements(force = True, reset= True)
            
            # update world state
            await self.scene.world_state.request_update()
            
            emit("status", f"Scene forked", status="success")            
        except Exception as e:
            log.exception("Scene fork failed", exc=e)
            emit("status", "Scene fork failed", status="error")
        
        