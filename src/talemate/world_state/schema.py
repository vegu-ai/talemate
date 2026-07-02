"""
Pydantic schemas for world-state snapshot entities.

Lives in its own module so peers like ``talemate.world_state.merge`` can
import the state classes without cycling back through
``talemate.world_state.__init__`` (which itself depends on ``merge``).
"""

from typing import Union

from pydantic import BaseModel, Field

# ``misses`` tracks how many consecutive durable-snapshot update passes an
# entity has gone without being touched by the agent's patch. It is internal
# bookkeeping for auto-eviction (see ``talemate.world_state.merge``) — it is
# never shown to the model and the model is never asked to manage it.


class CharacterState(BaseModel):
    snapshot: Union[str, None] = None
    emotion: Union[str, None] = None
    mentions: list[str] = Field(default_factory=list)
    misses: int = 0


class ObjectState(BaseModel):
    snapshot: Union[str, None] = None
    mentions: list[str] = Field(default_factory=list)
    misses: int = 0


class PlaceState(BaseModel):
    snapshot: Union[str, None] = None
    mentions: list[str] = Field(default_factory=list)
    misses: int = 0
