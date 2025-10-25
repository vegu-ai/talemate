from typing import TYPE_CHECKING

from talemate.world_state.templates.base import Template, register

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["AgentPersona"]


@register("agent_persona")
class AgentPersona(Template):
    description: str | None = None
    # Optional initial greeting for Director Chat. If provided, this will be used
    # as the first director message when a chat is created or cleared.
    initial_chat_message: str | None = None

    def render(self, scene: "Scene", agent_name: str | None = None):
        return self.formatted("instructions", scene, agent_name or "")
