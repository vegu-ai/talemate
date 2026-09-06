"""
Pydantic schemas for world-state snapshot entities.

Lives in its own module so peers like ``talemate.world_state.merge`` can
import the state classes without cycling back through
``talemate.world_state.__init__`` (which itself depends on ``merge``).
"""

from typing import Union

from pydantic import BaseModel, Field, model_serializer

from talemate.knowledge.snapshot_models import SnapshotPerspectives

# ``misses`` tracks how many consecutive durable-snapshot update passes an
# entity has gone without being touched by the agent's patch. It is internal
# bookkeeping for auto-eviction (see ``talemate.world_state.merge``) — it is
# never shown to the model and the model is never asked to manage it.


class SnapshotEntity(BaseModel):
    perspectives: SnapshotPerspectives | None = None

    @model_serializer(mode="wrap")
    def serialize_perspectives(self, handler):
        data = handler(self)
        if self.perspectives is None:
            data.pop("perspectives", None)
        return data


class CharacterState(SnapshotEntity):
    snapshot: Union[str, None] = None
    emotion: Union[str, None] = None
    mentions: list[str] = Field(default_factory=list)
    misses: int = 0


class ObjectState(SnapshotEntity):
    snapshot: Union[str, None] = None
    mentions: list[str] = Field(default_factory=list)
    misses: int = 0


class PlaceState(SnapshotEntity):
    snapshot: Union[str, None] = None
    mentions: list[str] = Field(default_factory=list)
    misses: int = 0
