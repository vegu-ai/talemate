import pydantic
from typing import TYPE_CHECKING, Union
from talemate.agents.base import set_processing
from talemate.prompts import Prompt
import talemate.util as util

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

class ContentGenerationContext(pydantic.BaseModel):
    
    """
    A context for generating content.
    """
    
    context: str
    instructions: str
    length: int
    character: Union[str, None] = None
    original: Union[str, None] = None

    @property
    def computed_context(self) -> (str, str):
        typ, context = self.context.split(":", 1)
        return typ, context


class AssistantMixin:
    
    """
    Creator mixin that allows quick contextual generation of content.
    """
    
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
                "character": self.scene.get_character(generation_context.character) if generation_context.character else None,
            }
        )
        
        content = util.strip_partial_sentences(content)
        
        return content.strip()