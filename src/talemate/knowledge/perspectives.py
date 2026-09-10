from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, Iterable
import weakref

from blinker import signal

from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import (
    Acquisition,
    CharacterView,
    Disclosure,
    PerspectiveInvalidation,
    PerspectiveOutput,
    PerspectiveView,
    SceneKnowledge,
    SourcePerspectives,
    SourceReference,
    content_digest,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene
    from talemate.scene_message import SceneMessage
    from talemate.character import Character


perspectives_changed = signal("perspectives_changed")
MAX_DEPENDENCY_DEPTH = 32


@dataclass
class _Source:
    kind: Literal["message", "summary", "intro"]
    id: str | int
    layer: int
    owner: object

    @property
    def key(self):
        return self.kind, self.id, self.layer

    @property
    def text(self):
        if self.kind == "intro":
            return self.owner.intro
        if isinstance(self.owner, dict):
            if self.kind == "message":
                from talemate.scene_message import MESSAGES

                return MESSAGES.get(self.owner.get("typ"), MESSAGES["scene"])(
                    **self.owner
                ).perception_text
            return self.owner["message" if self.kind == "message" else "text"]
        return self.owner.perception_text

    @property
    def knowledge(self) -> SourcePerspectives | None:
        if self.kind == "intro":
            value = self.owner.intro_knowledge
            return (
                SourcePerspectives.model_validate(value) if value is not None else None
            )
        value = (
            self.owner.get("knowledge")
            if isinstance(self.owner, dict)
            else self.owner.knowledge
        )
        return SourcePerspectives.model_validate(value) if value is not None else None

    @knowledge.setter
    def knowledge(self, value: SourcePerspectives):
        if self.kind == "intro":
            self.owner.intro_knowledge = value
        elif isinstance(self.owner, dict):
            self.owner["knowledge"] = value.model_dump(mode="json")
        else:
            self.owner.knowledge = value

    def reference(self, view_id=None):
        return SourceReference(
            kind=self.kind,
            id=self.id,
            layer=self.layer,
            revision=self.knowledge.revision,
            view_id=view_id,
            view_revision=next(
                (view.revision for view in self.knowledge.views if view.id == view_id),
                None,
            ),
        )


def message_sources(scene):
    """History plus persisted reinforcement passages that are inserted directly."""
    yield from scene.history
    yield from direct_message_sources(scene)


def direct_message_sources(scene):
    world_state = getattr(scene, "world_state", None)
    reinforcements = (
        world_state.get("reinforce", ())
        if isinstance(world_state, dict)
        else getattr(world_state, "reinforce", ())
    )
    for reinforcement in reinforcements:
        value = (
            reinforcement.get
            if isinstance(reinforcement, dict)
            else lambda key: getattr(reinforcement, key, None)
        )
        source = value("perspective_source")
        if source is not None and value("insert") != "sequential":
            yield source


def _sources(scene):
    if (
        getattr(scene, "intro_present", None) is not None
        or getattr(scene, "intro_knowledge", None) is not None
    ):
        yield _Source("intro", "intro", 0, scene)
    for message in message_sources(scene):
        identity = (
            message.get("id")
            if isinstance(message, dict)
            else getattr(message, "id", None)
        )
        if identity is not None:
            yield _Source("message", identity, 0, message)
    for layer, entries in enumerate([scene.archived_history, *scene.layered_history]):
        for entry in entries:
            if entry.get("id") is not None:
                yield _Source("summary", entry["id"], layer, entry)


def _validate_key(key):
    SourceReference(kind=key[0], id=key[1], layer=key[2], revision=1)


class PerspectiveReadContext:
    """Indexes and successful freshness depths for one synchronous, mutation-free read."""

    def __init__(self, scene: "Scene"):
        self.scene = scene
        self.sources = {}
        for source in _sources(scene):
            self.sources.setdefault(source.key, []).append(source)
        self.disclosures = {
            item.id: item for item in (scene.knowledge or SceneKnowledge()).disclosures
        }
        self.depths = {}


def _read_context(scene, read):
    if read is None:
        return PerspectiveReadContext(scene)
    if read.scene is not scene:
        raise ValueError("Perspective read context belongs to another scene")
    return read


def _find(scene, key, read=None):
    _validate_key(key)
    matches = (
        _read_context(scene, read).sources.get(key, [])
        if read is not None
        else [source for source in _sources(scene) if source.key == key]
    )
    if len(matches) > 1:
        raise ValueError(f"Ambiguous knowledge source: {key}")
    return matches[0] if matches else None


def _names(scene):
    names = [character.name for character in scene.character_data.values()]
    if any(not name.strip() or name != name.strip() for name in names):
        raise ValueError("Character knowledge requires nonempty canonical names")
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Character knowledge requires unambiguous character names")
    return set(names)


def _validate_audience(scene, audience):
    unknown = set(audience) - _names(scene)
    if unknown:
        raise ValueError(f"Unresolved perspective audience: {sorted(unknown)}")


def _require_enabled(scene):
    if not character_knowledge_enabled(scene):
        raise ValueError("Perspective operations require perception mode")


def _acquire(scene):
    state = scene.knowledge or SceneKnowledge()
    return Acquisition(order=state.last_order + 1, ts=scene.ts)


def _commit_order(scene, acquired):
    state = scene.knowledge or SceneKnowledge()
    scene.knowledge = state.model_copy(
        update={"last_order": max(state.last_order, acquired.order)}
    )


def source_reference(
    scene: "Scene",
    kind: Literal["message", "summary", "disclosure", "intro"],
    source_id: str | int,
    *,
    layer: int = 0,
    read: PerspectiveReadContext | None = None,
) -> SourceReference | None:
    if scene.knowledge is None:
        return None
    if kind == "disclosure":
        if layer:
            raise ValueError("Disclosures do not have summary layers")
        disclosure = (
            _read_context(scene, read).disclosures.get(source_id)
            if read is not None
            else next(
                (item for item in scene.knowledge.disclosures if item.id == source_id),
                None,
            )
        )
        if disclosure is None:
            return None
        return SourceReference(kind=kind, id=source_id, revision=disclosure.revision)
    source = _find(scene, (kind, source_id, layer), read)
    return source.reference() if source and source.knowledge else None


def _passages_fresh(scene, provenance, read=None):
    for item in provenance:
        source = _find(scene, ("message", item.message_id, 0), read)
        if source is None or content_digest(source.text) != item.content_digest:
            return False
        if item.revision is not None and (
            source.knowledge is None or source.knowledge.revision != item.revision
        ):
            return False
    return True


def _fresh(
    scene,
    reference,
    character,
    visited,
    *,
    readable: bool | Literal["summary"] = True,
    read=None,
    remaining=MAX_DEPENDENCY_DEPTH - 1,
):
    read = _read_context(scene, read)
    return (
        _fresh_depth(
            scene,
            reference,
            character,
            visited,
            readable=readable,
            read=read,
            remaining=remaining,
        )
        is not None
    )


def _fresh_depth(scene, reference, character, visited, *, readable, read, remaining):
    if reference in visited or remaining < 0:
        return None
    key = (reference, character, readable)
    if key in read.depths:
        depth = read.depths[key]
        return depth if depth <= remaining else None
    visited = visited | {reference}
    if reference.kind == "disclosure":
        item = read.disclosures.get(reference.id)
        if item and item.revision == reference.revision and character in item.audience:
            read.depths[key] = 0
            return 0
        return None
    source = _find(scene, reference.key, read)
    if not source or not source.knowledge:
        return None
    knowledge = source.knowledge
    if (
        knowledge.revision != reference.revision
        or knowledge.content_digest != content_digest(source.text)
    ):
        return None
    views = [view for view in knowledge.views if character in view.audience]
    # A summary may cite an analyzed source's absent audience as an omission.
    if not views and reference.view_id is None and readable in (False, "summary"):
        read.depths[key] = 0
        return 0
    if reference.view_id is not None:
        views = [view for view in views if view.id == reference.view_id]
    if (
        len(views) != 1
        or (
            reference.view_revision is not None
            and reference.view_revision != views[0].revision
        )
        or (readable == "summary" and views[0].status not in ("ready", "omitted"))
        or (readable is True and views[0].status != "ready")
        or not _passages_fresh(scene, views[0].passage_provenance, read)
    ):
        return None
    depth = 0
    for dependency in views[0].sources:
        child_depth = _fresh_depth(
            scene,
            dependency,
            character,
            visited,
            readable=(
                "summary" if readable and reference.kind == "summary" else readable
            ),
            read=read,
            remaining=remaining - 1,
        )
        if child_depth is None:
            return None
        depth = max(depth, child_depth + 1)
    read.depths[key] = depth
    return depth


def can_cite_view(
    scene: "Scene",
    reference: SourceReference,
    character: str,
    *,
    read: PerspectiveReadContext | None = None,
) -> bool:
    """Whether a ready view can support another view within the dependency limit."""
    return character_knowledge_enabled(scene) and _fresh(
        scene, reference, character, set(), read=read
    )


def select_character_view(
    scene: "Scene",
    source: SourceReference,
    character: str,
    *,
    read: PerspectiveReadContext | None = None,
) -> CharacterView:
    source = SourceReference.model_validate(source)
    if not character_knowledge_enabled(scene):
        return CharacterView(status="unavailable")
    _validate_audience(scene, (character,))
    read = _read_context(scene, read)
    if source.kind == "disclosure":
        item = read.disclosures.get(source.id)
        if item is not None and character in item.audience:
            if item.revision != source.revision:
                return CharacterView(status="pending", source=source)
            return CharacterView(
                status="ready",
                text=item.text,
                source=source,
                acquired=item.acquired,
            )
        return CharacterView(status="unavailable", source=source)
    owner = _find(scene, source.key, read)
    if not owner or not owner.knowledge:
        return CharacterView(status="unavailable", source=source)
    knowledge = owner.knowledge
    if (
        knowledge.revision != source.revision
        or knowledge.content_digest != content_digest(owner.text)
    ):
        return CharacterView(
            status="pending", source=source, acquired=knowledge.acquired
        )
    views = [view for view in knowledge.views if character in view.audience]
    if source.view_id is not None:
        views = [view for view in views if view.id == source.view_id]
    if not views:
        return CharacterView(
            status="unavailable", source=source, acquired=knowledge.acquired
        )
    view = views[0]
    status = view.status
    if source.view_revision is not None and source.view_revision != view.revision:
        status = "pending"
    if status in ("ready", "omitted") and not (
        _passages_fresh(scene, view.passage_provenance, read)
        and all(
            _fresh(
                scene,
                dependency,
                character,
                {source},
                readable="summary" if source.kind == "summary" else status == "ready",
                read=read,
            )
            for dependency in view.sources
        )
    ):
        status = "pending"
    return CharacterView(
        status=status,
        text=view.text if status == "ready" else None,
        source=owner.reference(view.id),
        acquired=knowledge.acquired,
    )


def _notify(scene, old, replacement, reason, *, changes=None):
    changed = list(changes if changes is not None else [(old, None)])
    if not changed:
        return None
    affected = [reference for reference, _ in changed]
    invalidated = {(reference.key, reference.view_id) for reference in affected}
    while True:
        additions = []
        for source in _sources(scene):
            knowledge = source.knowledge
            if knowledge is None:
                continue
            views = []
            for view in knowledge.views:
                identity = (source.key, view.id)
                depends = any(
                    dependency.key == reference.key
                    and (
                        dependency.view_id is None
                        or reference.view_id is None
                        or dependency.view_id == reference.view_id
                    )
                    and (audience is None or set(view.audience).intersection(audience))
                    for dependency in view.sources
                    for reference, audience in changed
                )
                depends = depends or (
                    reason in ("content", "deleted")
                    and old.kind == "message"
                    and any(
                        item.message_id == old.id for item in view.passage_provenance
                    )
                )
                if (
                    identity not in invalidated
                    and (source.key, None) not in invalidated
                    and depends
                ):
                    reference = source.reference(view.id)
                    additions.append((reference, view.audience))
                    affected.append(reference)
                    invalidated.add(identity)
                    view = view.invalidated()
                views.append(view)
            if tuple(views) != knowledge.views:
                source.knowledge = knowledge.model_copy(update={"views": tuple(views)})
        if not additions:
            break
        changed.extend(additions)
    event = PerspectiveInvalidation(
        source=old, replacement=replacement, affected=tuple(affected), reason=reason
    )
    perspectives_changed.send(scene, event=event)
    return event


def set_source_perspectives(
    scene: "Scene",
    kind: Literal["message", "summary", "intro"],
    source_id: str | int,
    outputs: Iterable[PerspectiveOutput | dict],
    *,
    layer: int = 0,
) -> SourceReference:
    _require_enabled(scene)
    if kind not in ("message", "summary", "intro"):
        raise ValueError(
            "Only introductions, messages and summaries have perspective views"
        )
    source = _find(scene, (kind, source_id, layer))
    if source is None:
        raise ValueError("Perspective source does not exist")
    parsed = tuple(PerspectiveOutput.model_validate(output) for output in outputs)
    read = PerspectiveReadContext(scene)
    for output in parsed:
        _validate_audience(scene, output.audience)
        if output.evidence_spans:
            from talemate.knowledge.evidence import passage_spans

            if kind != "message" or max(output.evidence_spans) >= len(
                passage_spans(source.text)
            ):
                raise ValueError(
                    "Evidence must reference an offered span of this message"
                )
        if not _passages_fresh(scene, output.passage_provenance, read):
            raise ValueError("Analytical passage provenance is stale or unresolved")
        for dependency in output.sources:
            if dependency.key == source.key or not all(
                _fresh(
                    scene,
                    dependency,
                    character,
                    set(),
                    readable=(
                        ("summary" if kind == "summary" else output.status == "ready")
                        if output.status in ("ready", "omitted")
                        else False
                    ),
                    read=read,
                )
                for character in output.audience
            ):
                raise ValueError(
                    "Perspective dependency is stale, unresolved, or outside its audience"
                )
    previous = source.knowledge
    old = source.reference() if previous else None
    acquired = previous.acquired if previous else _acquire(scene)
    views = []
    for output in parsed:
        existing = (
            next(
                (
                    view
                    for view in previous.views
                    if (
                        view.id == output.id
                        if output.id is not None
                        else set(view.audience) == set(output.audience)
                    )
                ),
                None,
            )
            if previous
            else None
        )
        values = output.model_dump(exclude={"id", "revision"})
        if existing:
            if set(output.audience) == set(existing.audience):
                values["audience"] = existing.audience
            candidate = PerspectiveView(
                id=existing.id, revision=existing.revision, **values
            )
            if candidate != existing:
                candidate = candidate.model_copy(
                    update={"revision": existing.revision + 1}
                )
        else:
            if output.id is not None:
                raise ValueError("Explicit view IDs must identify an existing view")
            candidate = PerspectiveView(**values)
        views.append(candidate)
    digest = content_digest(source.text)
    content_changed = previous is not None and previous.content_digest != digest
    knowledge = SourcePerspectives(
        revision=previous.revision + int(content_changed) if previous else 1,
        content_digest=digest,
        acquired=acquired,
        views=tuple(views),
    )
    changes = []
    if previous:
        if content_changed:
            changes = [(old, None)]
        else:
            by_id = {view.id: view for view in knowledge.views}
            changes = [
                (source.reference(view.id), view.audience)
                for view in previous.views
                if by_id.get(view.id) != view
            ]
    source.knowledge = knowledge
    if previous and not content_changed:
        old_ids = {view.id for view in previous.views}
        changes.extend(
            (source.reference(view.id), view.audience)
            for view in knowledge.views
            if view.id not in old_ids
        )
    _commit_order(scene, acquired)
    bind_perspective_sources(scene)
    _notify(
        scene,
        old or source.reference(),
        source.reference(),
        "views",
        changes=changes if previous else None,
    )
    return source.reference()


def add_disclosure(
    scene: "Scene",
    text: str,
    audience: Iterable[str],
    *,
    provenance: Iterable[SourceReference] = (),
    origin: str | None = None,
    message_id_boundary: int | None = None,
    origin_scene_ts: int | None = None,
    away_scene_ts: int | None = None,
) -> Disclosure:
    _require_enabled(scene)
    disclosure = Disclosure(
        text=text,
        audience=audience,
        acquired=_acquire(scene),
        provenance=provenance,
        origin=origin,
        message_id_boundary=(
            max((item.id for item in message_sources(scene)), default=0)
            if message_id_boundary is None
            else message_id_boundary
        ),
        origin_scene_ts=origin_scene_ts,
        away_scene_ts=away_scene_ts,
    )
    _validate_audience(scene, disclosure.audience)
    for reference in disclosure.provenance:
        current = source_reference(
            scene, reference.kind, reference.id, layer=reference.layer
        )
        if current is None or current.revision != reference.revision:
            raise ValueError(
                "Disclosure provenance must identify an existing source revision"
            )
        if reference.view_id is not None:
            source = _find(scene, reference.key)
            if not any(
                view.id == reference.view_id
                and (
                    reference.view_revision is None
                    or view.revision == reference.view_revision
                )
                for view in source.knowledge.views
            ):
                raise ValueError(
                    "Disclosure provenance view does not exist at this revision"
                )
    _commit_order(scene, disclosure.acquired)
    scene.knowledge = scene.knowledge.model_copy(
        update={
            "disclosures": (*scene.knowledge.disclosures, disclosure),
        }
    )
    reference = source_reference(scene, "disclosure", disclosure.id)
    _notify(scene, reference, reference, "views")
    return disclosure


def replace_disclosure(
    scene: "Scene",
    disclosure_id: str,
    text: str,
    *,
    preserve_boundary: bool = False,
    message_id_boundary: int | None = None,
    origin_scene_ts: int | None = None,
    away_scene_ts: int | None = None,
) -> Disclosure:
    """Replace one disclosure in place and invalidate its derived knowledge."""

    _require_enabled(scene)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Disclosure replacement text must be nonempty")
    state = scene.knowledge or SceneKnowledge()
    previous = next(
        (item for item in state.disclosures if item.id == disclosure_id), None
    )
    if previous is None:
        raise ValueError("Disclosure does not exist")
    old = SourceReference(kind="disclosure", id=previous.id, revision=previous.revision)
    acquired = _acquire(scene)
    replacement = previous.model_copy(
        update={
            "text": text.strip(),
            "revision": previous.revision + 1,
            "acquired": acquired,
            "message_id_boundary": (
                message_id_boundary
                if message_id_boundary is not None
                else previous.message_id_boundary
                if preserve_boundary
                else max((item.id for item in message_sources(scene)), default=0)
            ),
            "origin_scene_ts": (
                previous.origin_scene_ts if origin_scene_ts is None else origin_scene_ts
            ),
            "away_scene_ts": (
                previous.away_scene_ts if preserve_boundary else away_scene_ts
            ),
        }
    )
    scene.knowledge = state.model_copy(
        update={
            "disclosures": tuple(
                replacement if item.id == disclosure_id else item
                for item in state.disclosures
            )
        }
    )
    _commit_order(scene, acquired)
    new = SourceReference(
        kind="disclosure", id=replacement.id, revision=replacement.revision
    )
    _notify(scene, old, new, "content")
    return replacement


def remove_disclosure(scene: "Scene", disclosure_id: str) -> Disclosure:
    """Remove one disclosure and invalidate knowledge derived from it."""

    _require_enabled(scene)
    state = scene.knowledge or SceneKnowledge()
    disclosure = next(
        (item for item in state.disclosures if item.id == disclosure_id), None
    )
    if disclosure is None:
        raise ValueError("Disclosure does not exist")
    scene.knowledge = state.model_copy(
        update={
            "disclosures": tuple(
                item for item in state.disclosures if item.id != disclosure_id
            )
        }
    )
    reference = SourceReference(
        kind="disclosure", id=disclosure.id, revision=disclosure.revision
    )
    _notify(scene, reference, None, "deleted")
    return disclosure


def source_content_changed(
    scene: "Scene",
    kind: Literal["message", "summary"],
    source_id: str | int,
    *,
    layer: int = 0,
) -> PerspectiveInvalidation | None:
    if kind == "message":
        # dialogue_facts imports supported_facts, which imports this module.
        from talemate.knowledge.dialogue_facts import invalidate_dialogue_facts

        invalidate_dialogue_facts(scene)
    if scene.knowledge is None:
        return
    source = _find(scene, (kind, source_id, layer))
    if source is None:
        return
    if source.knowledge is None:
        if kind != "message" or not any(
            item.message_id == source_id
            and item.content_digest != content_digest(source.text)
            for candidate in _sources(scene)
            if candidate.knowledge is not None
            for view in candidate.knowledge.views
            for item in view.passage_provenance
        ):
            return
        return _notify(
            scene,
            SourceReference(kind="message", id=source_id, revision=1),
            None,
            "content",
        )
    if source.knowledge.content_digest == content_digest(source.text):
        return
    old = source.reference()
    source.knowledge = source.knowledge.invalidated(source.text)
    return _notify(scene, old, source.reference(), "content")


def source_deleted(
    scene: "Scene", reference: SourceReference | None, *, message_id: int | None = None
) -> PerspectiveInvalidation | None:
    # dialogue_facts imports supported_facts, which imports this module.
    from talemate.knowledge.dialogue_facts import invalidate_dialogue_facts

    invalidate_dialogue_facts(scene)
    if reference is None and message_id is not None and scene.knowledge is not None:
        reference = SourceReference(kind="message", id=message_id, revision=1)
    if reference is not None:
        return _notify(scene, reference, None, "deleted")


def message_content_changed(message: "SceneMessage") -> None:
    scene = message._knowledge_scene() if message._knowledge_scene else None
    if scene is not None and any(item is message for item in message_sources(scene)):
        source_content_changed(scene, "message", message.id)
    elif (
        message.knowledge is not None
        and message.knowledge.content_digest != content_digest(message.perception_text)
    ):
        message.knowledge = message.knowledge.invalidated(message.perception_text)


def bind_perspective_sources(scene: "Scene") -> None:
    from talemate.scene_message import advance_message_id

    for message in message_sources(scene):
        message._knowledge_scene = weakref.ref(scene)
        advance_message_id(message.id)


def validate_saved_knowledge(data: dict) -> SceneKnowledge | None:
    if character_knowledge_enabled(
        SimpleNamespace(knowledge_eligibility=data.get("knowledge_eligibility"))
    ):
        _names(
            SimpleNamespace(
                character_data={
                    key: SimpleNamespace(name=value["name"])
                    for key, value in data.get("character_data", {}).items()
                }
            )
        )
    state_data = data.get("knowledge")
    records = [*data.get("history", []), *data.get("archived_history", [])]
    if data.get("intro_knowledge") is not None:
        records.append({"id": "intro", "knowledge": data["intro_knowledge"]})
    records.extend(
        item["perspective_source"]
        for item in data.get("world_state", {}).get("reinforce", ())
        if item.get("perspective_source") is not None
        and item.get("insert") != "sequential"
    )
    records.extend(
        entry for layer in data.get("layered_history", []) for entry in layer
    )
    has_records = any(
        isinstance(entry, dict) and entry.get("knowledge") is not None
        for entry in records
    )
    if state_data is None and not has_records:
        return None
    if data.get("knowledge_eligibility") != "perception":
        raise ValueError("Perspective records require perception scene eligibility")
    if state_data is None:
        raise ValueError(
            "Perspective records require the scene knowledge acquisition counter"
        )
    if any(
        isinstance(entry, dict)
        and entry.get("knowledge") is not None
        and entry.get("id") is None
        for entry in records
    ):
        raise ValueError("Perspective records require a persisted source identity")
    state = SceneKnowledge.model_validate(state_data)
    scene = SimpleNamespace(
        intro=data.get("intro", ""),
        intro_present=data.get("intro_present"),
        intro_knowledge=data.get("intro_knowledge"),
        history=data.get("history", []),
        archived_history=data.get("archived_history", []),
        layered_history=data.get("layered_history", []),
        world_state=data.get("world_state", {}),
        character_data={
            key: SimpleNamespace(name=value["name"])
            for key, value in data.get("character_data", {}).items()
        },
    )
    orders = [item.acquired.order for item in state.disclosures]
    seen = set()
    for source in _sources(scene):
        if source.key in seen:
            raise ValueError(f"Duplicate knowledge source identity: {source.key}")
        seen.add(source.key)
        if source.knowledge is None:
            continue
        source.reference()
        orders.append(source.knowledge.acquired.order)
        for view in source.knowledge.views:
            _validate_audience(scene, view.audience)
    for item in state.disclosures:
        _validate_audience(scene, item.audience)
    if orders and max(orders) > state.last_order:
        raise ValueError("Scene knowledge acquisition counter precedes saved evidence")
    return state


def validate_character_rename(
    scene: "Scene", character: "Character", new_name: str
) -> None:
    destination = scene.character_data.get(new_name)
    if (destination is not None and destination is not character) or any(
        other is not character and other.name.casefold() == new_name.casefold()
        for other in scene.character_data.values()
    ):
        raise ValueError("Cannot rename a character to another character's name")
    if character_knowledge_enabled(scene) and (
        not new_name.strip() or new_name != new_name.strip()
    ):
        raise ValueError("Character knowledge requires a nonempty canonical name")


def remove_perspective_audiences(scene: "Scene", name: str) -> None:
    if getattr(scene, "intro_present", None) is not None:
        scene.intro_present = [
            member for member in scene.intro_present if member != name
        ]
    scene.world_state.clear_snapshot_perspectives()
    changed = []
    for source in _sources(scene):
        knowledge = source.knowledge
        if knowledge is None:
            continue
        views = []
        for view in knowledge.views:
            if name in view.audience:
                changed.append(source.reference(view.id))
                audience = tuple(member for member in view.audience if member != name)
                if not audience:
                    continue
                view = view.model_copy(update={"audience": audience})
            views.append(view)
        source.knowledge = knowledge.model_copy(update={"views": tuple(views)})
    if scene.knowledge is not None:
        disclosures = []
        for item in scene.knowledge.disclosures:
            if name in item.audience:
                changed.append(
                    SourceReference(
                        kind="disclosure", id=item.id, revision=item.revision
                    )
                )
                audience = tuple(member for member in item.audience if member != name)
                if not audience:
                    continue
                item = item.model_copy(update={"audience": audience})
            disclosures.append(item)
        scene.knowledge = scene.knowledge.model_copy(
            update={"disclosures": tuple(disclosures)}
        )
    if changed:
        perspectives_changed.send(
            scene,
            event=PerspectiveInvalidation(
                source=changed[0],
                replacement=None,
                affected=tuple(changed),
                reason="deleted",
            ),
        )


def clear_perspective_records(scene: "Scene") -> None:
    scene.knowledge = None
    scene.intro_knowledge = None
    for message in message_sources(scene):
        if isinstance(message, dict):
            message.pop("knowledge", None)
        else:
            message.knowledge = None
    for reinforcement in scene.world_state.reinforce:
        if reinforcement.perspective_source is not None:
            reinforcement.perspective_source.knowledge = None
    for entries in [scene.archived_history, *scene.layered_history]:
        for entry in entries:
            entry.pop("knowledge", None)
    scene.world_state.clear_snapshot_perspectives()


def reset_perspectives(scene: "Scene") -> set[str]:
    from talemate.knowledge.memory import invalidate_memory_audiences

    # Facts are disposable; resetting durable sources also removes their index.
    removed = {
        key for key, fact in scene.world_state.facts.items() if fact.contributions
    }
    for key in removed:
        del scene.world_state.facts[key]
    scene.world_state.knowledge = [
        edge for edge in scene.world_state.knowledge if edge.target not in removed
    ]
    if scene.knowledge is not None:
        scene.knowledge = scene.knowledge.model_copy(update={"disclosures": ()})
    for entry in scene.archived_history:
        entry.pop("knowledge", None)
    invalidate_memory_audiences(scene)
    return removed


def rename_perspective_audiences(scene: "Scene", old: str, new: str) -> None:
    if old == new:
        return
    changed = []
    for source in _sources(scene):
        knowledge = source.knowledge
        if knowledge is None or not any(
            old in view.audience for view in knowledge.views
        ):
            continue
        reference = source.reference()
        source.knowledge = knowledge.model_copy(
            update={
                "views": tuple(
                    view.model_copy(
                        update={
                            "audience": tuple(
                                new if name == old else name for name in view.audience
                            )
                        }
                    )
                    for view in knowledge.views
                )
            }
        )
        changed.append(reference)
    state = scene.knowledge
    if state:
        for item in state.disclosures:
            if old in item.audience:
                changed.append(
                    SourceReference(
                        kind="disclosure", id=item.id, revision=item.revision
                    )
                )
        scene.knowledge = state.model_copy(
            update={
                "disclosures": tuple(
                    item.model_copy(
                        update={
                            "audience": tuple(
                                new if name == old else name for name in item.audience
                            )
                        }
                    )
                    for item in state.disclosures
                )
            }
        )
    if changed:
        perspectives_changed.send(
            scene,
            event=PerspectiveInvalidation(
                source=changed[0],
                replacement=changed[0],
                affected=tuple(changed),
                reason="rename",
            ),
        )
