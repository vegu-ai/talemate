from typing import TYPE_CHECKING
import pydantic
from talemate.game.engine.api.base import ScopedAPI
from talemate.prompts.base import Prompt
from talemate.client.base import ClientBase
from talemate.game.engine.api.base import ScopedAPI, run_async


if TYPE_CHECKING:
    from talemate.tale_mate import Scene


def create(scene: "Scene", client: "ClientBase") -> "ScopedAPI":
    class API(ScopedAPI):
        
        def request(
            self,
            template_name: str,
            dedupe_enabled: bool = True,
            kind: str = "create",
            **kwargs
        ) -> str:
            
            """
            Renders a prompt template and sends it to the LLM for
            generation
            
            Arguments:
            
            - template_name: str - The name of the template to render
              This should be the name of a template file without the extension
            - dedupe_enabled: bool - Whether to dedupe the prompt
            - kind: str - The kind of prompt to render
            - kwargs: dict - The arguments to pass to the template
            
            Returns:
            
            - str - The generated response
            """
            
            class Arguments(pydantic.BaseModel):
                template_name: str
                dedupe_enabled: bool
                kind: str
                kwargs: dict
            
            validated = Arguments(
                template_name=template_name,
                dedupe_enabled=dedupe_enabled,
                kind=kind,
                kwargs=kwargs
            )
            
            prompt = Prompt.get(validated.template_name, validated.kwargs)
            prompt.client = client
            prompt.dedupe_enabled = validated.dedupe_enabled
            return run_async(prompt.send(client, validated.kind))

    return API()