import structlog

from talemate.instance import get_agent
from talemate.server.websocket_plugin import Plugin

__all__ = [
    "SummarizeWebsocketHandler",
]

log = structlog.get_logger("talemate.server.summarize")


class SummarizeWebsocketHandler(Plugin):
    """
    Handles summarize actions
    """

    router = "summarizer"

    @property
    def summarizer(self):
        return get_agent("summarizer")
