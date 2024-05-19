import asyncio
from typing import TYPE_CHECKING, Tuple, Union
import random
import pydantic
import structlog
import json

import talemate.util as util
from talemate.util.response import extract_list
from talemate.agents.base import set_processing
from talemate.emit import emit
from talemate.prompts import Prompt
from talemate.world_state.templates import AnnotatedTemplate, Spices, WritingStyle, GenerationOptions
from talemate.instance import get_agent

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
    generation_options: GenerationOptions = pydantic.Field(default_factory=GenerationOptions)
    template: AnnotatedTemplate | None = None
    context_aware: bool = True
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
        
        spice = self.generation_options.spices.render(
            self.scene, self.character
        )
        
        log.debug("spice_applied", spice=spice, uid=self.uid, character=self.character, context=self.computed_context)
        
        emit(
            'spice_applied',
            websocket_passthrough=True, 
            data={
                "spice": spice, 
                "uid": self.uid, 
                "character": self.character, 
                "context": self.computed_context
            }
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
        
        return self.generation_options.writing_style.render(
            self.scene, self.character
        )
        
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
        )

        return await self.contextual_generate(generation_context)

    contextual_generate_from_args.exposed = True

    @set_processing
    async def contextual_generate(
        self,
        generation_context: ContentGenerationContext,
    ):
        """
        Request content from the assistant.
        """

        context_typ, context_name = generation_context.computed_context

        if generation_context.length < 100:
            kind = "create_short"
        elif generation_context.length < 500:
            kind = "create_concise"
        else:
            kind = "create"

        log.debug(f"Contextual generate: {context_typ} - {context_name}", generation_context=generation_context)

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
            
        if generation_context.computed_context[0] == 'list':
            try:
                content = json.dumps(extract_list(content), indent=2)
            except Exception as e:
                log.warning("Failed to extract list", error=e)
                content = "[]"

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

        response = response.replace("...","").strip()

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
        ).strip()
        response = response.replace("...","").strip()
        
        if response.startswith(input):
            response = response[len(input) :]

        self.scene.log.debug(
            "autocomplete_suggestion", suggestion=response, input=input
        )

        if emit_signal:
            emit("autocomplete_suggestion", response)

        return response
