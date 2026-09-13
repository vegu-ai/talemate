"""One previous snapshot for regenerating its source message, not scene history."""

import json
from contextlib import contextmanager

from pydantic import BaseModel, Field

from talemate.emit import emit
from talemate.exceptions import GenerationCancelled, TalemateError
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.snapshot_models import SnapshotPerspectives
from talemate.world_state.schema import CharacterState, ObjectState, PlaceState


def history_digest(scene, history):
    return content_digest(
        json.dumps(
            [scene.get_intro(), [[m.id, m.typ, m.message, m.source] for m in history]],
            ensure_ascii=False,
        )
    )


class SnapshotProvenance(BaseModel):
    source_message_id: int | None = None
    input_message_ids: list[int]
    includes_director: bool = False
    history_digest: str

    @classmethod
    def capture(cls, scene, *, includes_director=False):
        history = cls.input_history(scene.history, includes_director)
        source = next(
            (
                m
                for m in reversed(history)
                if m.typ not in {"reinforcement", "director"}
            ),
            None,
        )
        return cls(
            source_message_id=source.id if source else None,
            input_message_ids=[m.id for m in history],
            includes_director=includes_director,
            history_digest=history_digest(scene, history),
        )

    @staticmethod
    def input_history(history, includes_director):
        # Broad snapshot history excludes Director messages; semantic RAG can
        # use them, so requests with retrieval must retain that dependency.
        return [m for m in history if includes_director or m.typ != "director"]

    def matches(self, scene):
        history = self.input_history(scene.history, self.includes_director)
        prefix = history[: len(self.input_message_ids)]
        ids = [m.id for m in prefix]
        return ids == self.input_message_ids and self.history_digest == history_digest(
            scene, prefix
        )

    def precedes(self, scene, boundary):
        index = next(
            (
                i
                for i, m in enumerate(scene.history)
                if m.id == boundary.source_message_id
            ),
            None,
        )
        return (
            self.source_message_id != boundary.source_message_id
            and index is not None
            and self.valid_before(scene, index)
        )

    def valid_before(self, scene, index):
        history = self.input_history(scene.history[:index], self.includes_director)
        length = len(self.input_message_ids)
        return (
            length <= len(history)
            and self.matches(scene)
            and not any(m.typ == "time" for m in history[length:])
        )


class IncompatibleSnapshotTemplate(TalemateError):
    def __init__(self, template):
        super().__init__(
            f"The world snapshot prompt {template} is incompatible. "
            "Update or reset its override in the Prompt Manager, then try again."
        )


class SnapshotRequest:
    """Verify early inputs and bind publication to the template's history read."""

    def __init__(self, scene, *, template, includes_director=False):
        self.scene = scene
        self.template = template
        self.initial = SnapshotProvenance.capture(
            scene, includes_director=includes_director
        )
        self.provenance: SnapshotProvenance | None = None

    def context_history(self, **kwargs):
        # RAG awaits inside template rendering. Appends may extend its initial
        # inputs, but edits/deletions would mix incompatible message revisions.
        if not self.initial.matches(self.scene):
            raise GenerationCancelled("Snapshot inputs changed during memory lookup")
        self.provenance = SnapshotProvenance.capture(
            self.scene, includes_director=self.initial.includes_director
        )
        return self.scene.context_history(**kwargs)

    def verified_provenance(self):
        if self.provenance is None:
            raise IncompatibleSnapshotTemplate(self.template)
        if not self.provenance.matches(self.scene):
            raise GenerationCancelled("Snapshot inputs changed during generation")
        return self.provenance


class SnapshotRevision(BaseModel):
    characters: dict[str, CharacterState] = Field(default_factory=dict)
    items: dict[str, ObjectState] = Field(default_factory=dict)
    places: dict[str, PlaceState] = Field(default_factory=dict)
    location: str | None = None
    location_perspectives: SnapshotPerspectives | None = None
    anchor_message_ids: list[int] = Field(default_factory=list)
    snapshot_provenance: SnapshotProvenance | None = None

    @classmethod
    def capture(cls, state):
        return cls(**{key: getattr(state, key) for key in cls.model_fields}).model_copy(
            deep=True
        )

    def install(self, state):
        revision = self.model_copy(deep=True)
        for key in type(self).model_fields:
            setattr(state, key, getattr(revision, key))


def retain_previous(state, before, provenance, scene):
    """Repeated passes at M must retain the candidate from before M."""
    if before.snapshot_provenance and before.snapshot_provenance.precedes(
        scene, provenance
    ):
        state.previous_snapshot = before
    elif state.previous_snapshot and (
        not state.previous_snapshot.snapshot_provenance
        or not state.previous_snapshot.snapshot_provenance.precedes(scene, provenance)
    ):
        state.previous_snapshot = None
    state.snapshot_provenance = provenance


def can_publish(state, scene, epoch, provenance):
    return (
        provenance is not None
        and scene.world_state is state
        and state._snapshot_epoch == epoch
        and not state._snapshot_regenerating
        and provenance.matches(scene)
    )


@contextmanager
def regeneration_snapshot(scene, message):
    """Keep snapshot and message rollback on the same canonical commit boundary."""
    state = scene.world_state
    provenance = state.snapshot_provenance
    affected = (
        provenance.source_message_id == message.id
        if provenance
        else message.id in state.anchor_message_ids
    )
    if not affected:
        yield
        return
    if not state.agent.resolve_config("update_world_state", "inject_as_scene_memory"):
        yield
        return

    original = SnapshotRevision.capture(state)
    previous = state.previous_snapshot
    canonical = message.message
    target_index = next(i for i, entry in enumerate(scene.history) if entry is message)
    candidate = (
        previous
        if (
            previous
            and previous.snapshot_provenance
            and previous.snapshot_provenance.valid_before(scene, target_index)
        )
        else None
    )
    state._snapshot_epoch += 1
    epoch = state._snapshot_epoch
    state._snapshot_regenerating = True
    (candidate or SnapshotRevision()).install(state)
    state.previous_snapshot = None
    state.emit()
    emit(
        "status",
        message=(
            "Restored the previous world snapshot for regeneration."
            if candidate
            else "Cleared the world snapshot because no verified earlier snapshot is available."
        )
        + " Pin to context remains enabled. Refresh the snapshot when ready.",
        status="info",
    )
    try:
        yield
    finally:
        state._snapshot_regenerating = False
        if (
            scene.world_state is state
            and state._snapshot_epoch == epoch
            and state.agent.scene is scene
        ):
            if message.message == canonical:
                original.install(state)
                state.previous_snapshot = previous
            state.emit()
