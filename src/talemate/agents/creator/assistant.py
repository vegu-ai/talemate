import asyncio
from typing import TYPE_CHECKING, Tuple, Union
import random
import pydantic

import talemate.util as util
from talemate.agents.base import set_processing
from talemate.emit import emit
from talemate.prompts import Prompt
from talemate.world_state.templates import AnnotatedTemplate, Spices, WritingStyle
from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene


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
    writing_style: WritingStyle | None = None
    spices: Spices | None = None
    spice_level: float = 0.0
    template: AnnotatedTemplate | None = None

    @property
    def computed_context(self) -> Tuple[str, str]:
        typ, context = self.context.split(":", 1)
        return typ, context

    @property
    def scene(self) -> "Scene":
        return get_agent("creator").scene

    @property
    def spice(self):
        
        if self.template and not getattr(self.template, "supports_spice", False):
            # template supplied that doesn't support spice
            return ""
        
        if self.spice_level == 0:
            # no spice
            return ""
        
        if not self.spices:
            # no spices
            return ""
        
        # randomly determine if we should add spice (0.0 - 1.0)
        if random.random() > self.spice_level:
            return ""
        
        return self.spices.render(
            self.scene, self.character
        )
        
    @property
    def style(self):
        
        if self.template and not getattr(self.template, "supports_style", False):
            # template supplied that doesn't support style
            return ""
        
        if not self.writing_style:
            # no writing style
            return ""
        
        return self.writing_style.render(
            self.scene, self.character
        )        
        

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
        template: AnnotatedTemplate | None = None
    ):
        """
        Request content from the assistant.
        """

        generation_context = ContentGenerationContext(
            context=context,
            instructions=instructions,
            length=length,
            character=character,
            original=original,
            partial=partial,
            uid=uid,
            writing_style=writing_style,
            spices=spices,
            spice_level=spice_level,
            template=template,
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
                "character": (
                    self.scene.get_character(generation_context.character)
                    if generation_context.character
                    else None
                ),
                "spices": generation_context.spices,
                "writing_style": generation_context.writing_style,
                "template": generation_context.template,
            },
        )

        if not generation_context.partial:
            content = util.strip_partial_sentences(content)

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
