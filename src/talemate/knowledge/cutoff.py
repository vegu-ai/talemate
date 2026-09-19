"""Which recorded facts an extraction may offer as known before its source."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Mapping

from talemate.knowledge.timeline import message_times

if TYPE_CHECKING:
    from talemate.knowledge.perspective_models import Disclosure
    from talemate.knowledge.schema import Fact
    from talemate.tale_mate import Scene

__all__ = ["FactCutoff", "span_cutoff", "disclosure_cutoff"]


@dataclass(frozen=True)
class FactCutoff:
    """
    The start of a source, as a position among the messages: `message_id` is
    the first message of the source (message ids grow with the history), or,
    for a disclosure, the first message that did not exist when it was given;
    `order` then breaks a tie between two disclosures given between the same
    messages.

    A fact is known before the source when its first source is earlier:
    - a line: its message id is lower;
    - a disclosure: it was given before `message_id` existed;
    - a summarized entry without a line: the entry starts earlier;
    - static history: always.
    A fact with none of these (a manual fact) is ordered by time only. Scene
    time moves only at a time passage, so it is known only when its time is
    strictly earlier than `ts`.
    """

    message_id: int
    ts: int | None = None
    order: int | None = None
    disclosure_boundaries: Mapping[str, int] = field(
        default_factory=dict, compare=False
    )
    entry_starts: Mapping[str, int] = field(default_factory=dict, compare=False)
    static_entries: frozenset[str] = field(default_factory=frozenset, compare=False)

    def admits(self, fact: "Fact") -> bool:
        if fact.contributions:
            return self._admits_contribution(
                min(fact.contributions, key=lambda item: item.acquired.order)
            )
        if fact.message_id is not None:
            return fact.message_id < self.message_id
        entry = self._entry_before(fact.archive_id)
        if entry is not None:
            return entry
        return self._earlier_time(fact.ts)

    def _admits_contribution(self, contribution) -> bool:
        if contribution.message_id is not None:
            return contribution.message_id < self.message_id
        source = contribution.source
        if source.kind == "disclosure":
            boundary = self.disclosure_boundaries.get(source.id)
            if boundary is None:
                return False
            if boundary + 1 == self.message_id and self.order is not None:
                return contribution.acquired.order < self.order
            return boundary < self.message_id
        if source.kind == "summary":
            return bool(self._entry_before(source.id))
        return source.kind == "message" and source.id < self.message_id

    def _entry_before(self, archive_id: str | None) -> bool | None:
        """None when the entry gives no position."""
        if archive_id in self.static_entries:
            return True
        start = self.entry_starts.get(archive_id)
        return None if start is None else start < self.message_id

    def _earlier_time(self, ts: int | None) -> bool:
        return ts is not None and self.ts is not None and ts < self.ts


def _positions(scene: "Scene") -> dict:
    history = scene.history
    entry_starts = {}
    static_entries = set()
    for entry in scene.archived_history:
        identity = entry.get("id")
        start = entry.get("start")
        if identity is None:
            continue
        if start is None and entry.get("end") is None:
            static_entries.add(identity)
        elif start is not None and start < len(history):
            entry_starts[identity] = history[start].id
    knowledge = getattr(scene, "knowledge", None)
    return {
        "disclosure_boundaries": {
            disclosure.id: disclosure.message_id_boundary
            for disclosure in (knowledge.disclosures if knowledge else ())
        },
        "entry_starts": entry_starts,
        "static_entries": frozenset(static_entries),
    }


def span_cutoff(
    scene: "Scene", message_ids: Iterable[int | None], *, start: int | None = None
) -> FactCutoff:
    """
    The cutoff at the first message of a span. An input without a message
    line (only a disclosure, or a view read from its own text) falls back to
    the message at the entry's `start` index; without one, only static
    history and strictly earlier times are known.
    """
    ids = [identity for identity in message_ids if identity is not None]
    if not ids and start is not None and start < len(scene.history):
        ids = [scene.history[start].id]
    times = message_times(scene)
    first = min(ids) if ids else 0
    return FactCutoff(message_id=first, ts=times.get(first), **_positions(scene))


def disclosure_cutoff(scene: "Scene", disclosure: "Disclosure") -> FactCutoff:
    return FactCutoff(
        message_id=disclosure.message_id_boundary + 1,
        ts=disclosure.acquired.ts,
        order=disclosure.acquired.order,
        **_positions(scene),
    )
