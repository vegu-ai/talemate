import structlog

from talemate.server.websocket_plugin import Plugin

__all__ = [
    "WorldStateWebsocketHandler",
]

log = structlog.get_logger("talemate.server.world_state")


# TODO: Implement the websocket handler for the world state agent
class WorldStateWebsocketHandler(Plugin):
    router = "world_state"