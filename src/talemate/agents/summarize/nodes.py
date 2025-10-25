import structlog
from typing import ClassVar
from talemate.game.engine.nodes.registry import register
from talemate.game.engine.nodes.agent import AgentSettingsNode

log = structlog.get_logger("talemate.game.engine.nodes.agents.summarizer")


@register("agents/summarizer/Settings")
class SummarizerSettings(AgentSettingsNode):
    """
    Base node to render summarizer agent settings.
    """

    _agent_name: ClassVar[str] = "summarizer"

    def __init__(self, title="Summarizer Settings", **kwargs):
        super().__init__(title=title, **kwargs)
