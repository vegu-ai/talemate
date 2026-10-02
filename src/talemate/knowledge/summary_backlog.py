"""The character summary entries a knowledge step rebuilds, counted without a request."""

from typing import TYPE_CHECKING, Iterable, Literal

from pydantic import BaseModel, ConfigDict

from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    StaleCheck,
    has_stored_views,
    source_reference,
    view_staleness,
)
from talemate.knowledge.perspective_models import SourcePerspectives
from talemate.knowledge.summaries import summary_entry, summary_inputs, summary_layer

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["SummaryBacklog", "SummaryBacklogEntry", "summary_backlog"]


class SummaryBacklogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    layer: int
    identity: str
    names: tuple[str, ...]
    # every character has a stored ready or omitted view that an analysis
    # does not rewrite
    keepable: bool
    requests: int
    check: StaleCheck | Literal["queued", "passage_analysis"]
    character: str | None = None
    cited: str | int | None = None

    @property
    def key(self) -> tuple[int, str]:
        return self.layer, self.identity


class SummaryBacklog(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: tuple[SummaryBacklogEntry, ...]
    # layered entries a rebuild of `entries` can make out of date
    at_risk: tuple[SummaryBacklogEntry, ...]
    # what a rebuild of the entries without stored views alone can make out of date
    empty_at_risk: tuple[SummaryBacklogEntry, ...]

    @property
    def keepable(self) -> tuple[SummaryBacklogEntry, ...]:
        return tuple(entry for entry in self.entries if entry.keepable)

    @property
    def empty(self) -> tuple[SummaryBacklogEntry, ...]:
        return tuple(entry for entry in self.entries if not entry.keepable)

    @property
    def total(self) -> int:
        return len(self.entries) + len(self.at_risk)

    def keys(self) -> set[tuple[int, str]]:
        return {entry.key for entry in (*self.entries, *self.at_risk)}

    def keep_keys(self) -> set[tuple[int, str]]:
        return {entry.key for entry in (*self.empty, *self.empty_at_risk)}

    def frame(self) -> dict:
        counted = (*self.entries, *self.at_risk)
        kept = (*self.empty, *self.empty_at_risk)
        return {
            "entries": len(self.entries),
            "keepable": len(self.keepable),
            "empty": len(self.empty),
            "at_risk": len(self.at_risk),
            "total": self.total,
            "characters": sorted({name for entry in counted for name in entry.names}),
            "layers": sorted({entry.layer for entry in counted}),
            "requests": sum(entry.requests for entry in counted),
            "keep_total": len(kept),
            "keep_requests": sum(entry.requests for entry in kept),
        }


def _requests(entry: dict, layer: int, names: Iterable[str]) -> int:
    """At most one request per character; a layer splits its children into parts."""
    count = len(tuple(names))
    if layer == 0:
        return count
    return count * max(1, entry["end"] - entry["start"] + 1)


def _backlog_entry(scene, entry, layer, names, *, read, check=None, cited=None):
    knowledge = entry.get("knowledge")
    keepable = check != "passage_analysis" and has_stored_views(
        SourcePerspectives.model_validate(knowledge) if knowledge else None, names
    )
    character = None
    if check is None:
        reference = source_reference(
            scene, "summary", entry["id"], layer=layer, read=read
        )
        stale = None
        for name in names:
            stale = (
                view_staleness(scene, reference, name, read=read) if reference else None
            )
            if stale is not None:
                break
        check = stale.check if stale else "queued"
        character = stale.character if stale else None
        cited = stale.cited if stale else None
    return SummaryBacklogEntry(
        layer=layer,
        identity=entry["id"],
        names=tuple(sorted(names)),
        keepable=keepable,
        requests=_requests(entry, layer, names),
        check=check,
        character=character,
        cited=cited,
    )


def _ancestors(scene, keys, *, read, skip) -> list[SummaryBacklogEntry]:
    """Layered entries built on `keys`, transitively, that are not in `skip`."""
    found = {}
    frontier = set(keys)
    while frontier:
        parents = set()
        for layer, identity in frontier:
            children = summary_layer(scene, layer)
            index = next(
                (i for i, child in enumerate(children) if child["id"] == identity),
                None,
            )
            if index is None:
                continue
            for parent in summary_layer(scene, layer + 1):
                key = (layer + 1, parent["id"])
                if (
                    parent.get("start") is not None
                    and parent["start"] <= index <= parent["end"]
                    and key not in skip
                    and key not in found
                ):
                    names = set(summary_inputs(scene, parent, layer + 1, read=read))
                    found[key] = _backlog_entry(
                        scene,
                        parent,
                        layer + 1,
                        names,
                        read=read,
                        check="dependency",
                        cited=identity,
                    )
                    parents.add(key)
        frontier = parents
    return sorted(found.values(), key=lambda entry: entry.key)


def summary_backlog(
    scene: "Scene",
    dirty: Iterable[tuple[int, str, str]],
    passages: Iterable[int] = (),
    *,
    approved: set[tuple[int, str]] = frozenset(),
) -> SummaryBacklog:
    """
    The entries to rebuild: the queued ones whose views are not current, and
    the base entries whose passages an analysis will rewrite (`passages`).
    """
    read = PerspectiveReadContext(scene)
    queued: dict[tuple[int, str], set[str]] = {}
    for layer, identity, name in dirty:
        if (layer, identity) not in approved:
            queued.setdefault((layer, identity), set()).add(name)
    entries = {}
    for (layer, identity), names in queued.items():
        entry = summary_entry(scene, identity, layer)
        if entry is None:
            continue
        reference = source_reference(scene, "summary", identity, layer=layer, read=read)
        stale = {
            name
            for name in names
            if name in scene.character_data
            and (
                reference is None
                or view_staleness(scene, reference, name, read=read) is not None
            )
        }
        if stale:
            entries[layer, identity] = _backlog_entry(
                scene, entry, layer, stale, read=read
            )
    positions = {message.id: index for index, message in enumerate(scene.history)}
    analyzed = sorted(positions[id] for id in passages if id in positions)
    for entry in scene.archived_history:
        key = (0, entry["id"])
        if key in approved or entry.get("start") is None:
            continue
        cited = next(
            (
                scene.history[index].id
                for index in analyzed
                if entry["start"] <= index <= entry["end"]
            ),
            None,
        )
        if cited is None:
            continue
        # the analysis can rewrite every character's view under it, so a
        # queued entry counts all of them and cannot keep its stored views
        names = set(summary_inputs(scene, entry, 0, read=read))
        if names:
            entries[key] = _backlog_entry(
                scene, entry, 0, names, read=read, check="passage_analysis", cited=cited
            )
    # a parent built on an entry that is rebuilt cannot keep its views either
    rebuilt = [key for key, entry in entries.items() if not entry.keepable]
    for parent in _ancestors(scene, rebuilt, read=read, skip=set(approved)):
        if parent.key in entries:
            entries[parent.key] = entries[parent.key].model_copy(
                update={"keepable": False}
            )
    ordered = sorted(entries.values(), key=lambda entry: entry.key)
    skip = set(entries) | set(approved)
    return SummaryBacklog(
        entries=tuple(ordered),
        at_risk=tuple(_ancestors(scene, entries, read=read, skip=skip)),
        empty_at_risk=tuple(
            _ancestors(
                scene,
                [entry.key for entry in ordered if not entry.keepable],
                read=read,
                skip=skip,
            )
        ),
    )
