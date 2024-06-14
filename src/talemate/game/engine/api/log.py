from typing import TYPE_CHECKING
import structlog
from talemate.game.engine.api.base import ScopedAPI

__all__ = [
    "create"
]

def create(log: structlog.BoundLogger) -> "ScopedAPI":
    class LogAPI(ScopedAPI):
        
        def info(self, event, *args, **kwargs):
            log.info(event, *args, **kwargs)
            
        def debug(self, event, *args, **kwargs):
            log.debug(event, *args, **kwargs)
            
        def error(self, event, *args, **kwargs):
            log.error(event, *args, **kwargs)
            
        def warning(self, event, *args, **kwargs):
            log.warning(event, *args, **kwargs)
            
    return LogAPI()