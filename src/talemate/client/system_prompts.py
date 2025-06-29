import pydantic

import structlog

__all__ = [
    "RENDER_CACHE",
    "SystemPrompts",
    "cache_all",
    "render_prompt",
]

log = structlog.get_logger(__name__)

BASIC = "Below is an instruction that describes a task. Write a response that appropriately completes the request."

RENDER_CACHE = {}

PROMPT_TEMPLATE_MAP = {
    # vanilla prompts
    "roleplay": "conversation.system-no-decensor",
    "narrator": "narrator.system-no-decensor",
    "creator": "creator.system-no-decensor",
    "director": "director.system-no-decensor",
    "analyst": "world_state.system-analyst-no-decensor",
    "analyst_freeform": "world_state.system-analyst-freeform-no-decensor",
    "editor": "editor.system-no-decensor",
    "world_state": "world_state.system-analyst-no-decensor",
    "summarize": "summarizer.system-no-decensor",
    "visualize": "visual.system-no-decensor",
    # contains some minor attempts at keeping the LLM from generating
    # refusals to generate certain types of content
    "roleplay_decensor": "conversation.system",
    "narrator_decensor": "narrator.system",
    "creator_decensor": "creator.system",
    "director_decensor": "director.system",
    "analyst_decensor": "world_state.system-analyst",
    "analyst_freeform_decensor": "world_state.system-analyst-freeform",
    "editor_decensor": "editor.system",
    "world_state_decensor": "world_state.system-analyst",
    "summarize_decensor": "summarizer.system",
    "visualize_decensor": "visual.system",
}


def cache_all() -> dict:
    for key in PROMPT_TEMPLATE_MAP:
        render_prompt(key)
    return RENDER_CACHE.copy()


def render_prompt(kind: str, decensor: bool = False):
    # work around circular import issue
    # TODO: refactor to avoid circular import
    from talemate.prompts import Prompt

    if kind not in PROMPT_TEMPLATE_MAP:
        log.warning(
            f"Invalid prompt system prompt identifier: {kind} - decensor: {decensor}"
        )
        return ""

    if decensor:
        key = f"{kind}_decensor"
    else:
        key = kind

    if key not in PROMPT_TEMPLATE_MAP:
        log.warning(
            f"Invalid prompt system prompt identifier: {kind} - decensor: {decensor}",
            key=key,
        )
        return ""

    if key in RENDER_CACHE:
        return RENDER_CACHE[key]

    prompt = str(Prompt.get(PROMPT_TEMPLATE_MAP[key]))

    RENDER_CACHE[key] = prompt
    return prompt


class SystemPrompts(pydantic.BaseModel):
    """
    System prompts and a normalized the way to access them.

    Allows specification of a parent "SystemPrompts" instance that will be
    used as a fallback, and if not so specified, will default to the
    system prompts in the globals via lambda functions that render
    the templates.

    The globals that exist now will be deprecated in favor of this later.
    """

    parent: "SystemPrompts | None" = pydantic.Field(default=None, exclude=True)

    roleplay: str | None = None
    narrator: str | None = None
    creator: str | None = None
    director: str | None = None
    analyst: str | None = None
    analyst_freeform: str | None = None
    editor: str | None = None
    world_state: str | None = None
    summarize: str | None = None
    visualize: str | None = None

    roleplay_decensor: str | None = None
    narrator_decensor: str | None = None
    creator_decensor: str | None = None
    director_decensor: str | None = None
    analyst_decensor: str | None = None
    analyst_freeform_decensor: str | None = None
    editor_decensor: str | None = None
    world_state_decensor: str | None = None
    summarize_decensor: str | None = None
    visualize_decensor: str | None = None

    class Config:
        exclude_none = True
        exclude_unset = True

    @property
    def defaults(self) -> dict:
        return RENDER_CACHE.copy()

    def alias(self, alias: str) -> str:
        if alias in PROMPT_TEMPLATE_MAP:
            return alias

        if "narrate" in alias:
            return "narrator"

        if "direction" in alias or "director" in alias:
            return "director"

        if "create" in alias or "creative" in alias:
            return "creator"

        if "conversation" in alias or "roleplay" in alias:
            return "roleplay"

        if "basic" in alias:
            return "basic"

        if "edit" in alias:
            return "editor"

        if "world_state" in alias:
            return "world_state"

        if "analyze_freeform" in alias or "investigate" in alias:
            return "analyst_freeform"

        if "analyze" in alias or "analyst" in alias or "analytical" in alias:
            return "analyst"

        if "summarize" in alias or "summarization" in alias:
            return "summarize"

        if "visual" in alias:
            return "visualize"

        return alias

    def get(self, kind: str, decensor: bool = False) -> str:
        kind = self.alias(kind)

        key = f"{kind}_decensor" if decensor else kind

        if getattr(self, key):
            return getattr(self, key)
        if self.parent is not None:
            return self.parent.get(kind, decensor)
        return render_prompt(kind, decensor)
