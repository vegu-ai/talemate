import structlog

from talemate.agents.base import Agent, AgentAction
from talemate.agents.registry import register
from talemate.client import ClientBase

from .chat import HelpChatMixin
from .websocket_handler import HelpWebsocketHandler

__all__ = ["HelpAgent"]

log = structlog.get_logger("talemate.agents.help")


@register()
class HelpAgent(HelpChatMixin, Agent):
    """
    Help agent

    Answers user questions about Talemate itself by consulting the bundled
    documentation. Available regardless of whether a scene is loaded and
    never modifies scene state - scene changes are the director's job.
    """

    agent_type = "help"
    verbose_name = "Help"
    essential = False
    websocket_handler = HelpWebsocketHandler

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {}
        HelpChatMixin.add_actions(actions)
        return actions

    def __init__(self, client: ClientBase | None = None, **kwargs):
        self.client = client
        self.scene = None
        self.is_enabled = True
        self.actions = HelpAgent.init_actions()

    @property
    def enabled(self):
        return self.is_enabled

    @property
    def has_toggle(self):
        return True
