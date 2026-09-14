"""The fact-centric listing behind the World Editor's Facts tab."""

from typing import TYPE_CHECKING, Literal

import pydantic

from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.chronology import (
    fact_display,
    fact_timestamp,
    superseded_fact_ids,
)
from talemate.knowledge.graph import bucket, perception_kind, standard_kind
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.names import aliases_for, numeric_id
from talemate.knowledge.perspectives import PerspectiveReadContext
from talemate.knowledge.schema import (
    FACT_SOURCE_LABELS,
    Fact,
    FactImportance,
    FactSource,
    KnownKind,
)
from talemate.knowledge.supported_facts import character_fact
from talemate.util.time import duration_to_human

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["FactQuery", "FactsPage", "list_facts", "latest_chapter"]

CharacterFilter = Literal["knows", "unknown", "subject"]
FactSort = Literal["time", "importance", "id"]


class FactQuery(pydantic.BaseModel):
    text: str | None = None
    character: str | None = None
    character_filter: CharacterFilter = "knows"
    topic_id: str | None = None
    importance: list[FactImportance] = pydantic.Field(default_factory=list)
    source: list[FactSource] = pydantic.Field(default_factory=list)
    superseded: bool | None = None
    false: bool | None = None
    latest_chapter: bool = False
    sort: FactSort = "time"
    descending: bool = True
    page: pydantic.PositiveInt = 1
    page_size: int = pydantic.Field(default=50, ge=1, le=200)


class TopicOption(pydantic.BaseModel):
    id: str
    name: str


class SourceOption(pydantic.BaseModel):
    value: FactSource
    label: str


class ChapterInfo(pydantic.BaseModel):
    id: str
    time: str
    start: int | None = None
    end: int | None = None


class FactOptions(pydantic.BaseModel):
    characters: list[str] = pydantic.Field(default_factory=list)
    topics: list[TopicOption] = pydantic.Field(default_factory=list)
    sources: list[SourceOption] = pydantic.Field(default_factory=list)


class FactsPage(pydantic.BaseModel):
    facts: list[dict]
    total: int
    page: int
    page_size: int
    options: FactOptions
    latest_chapter: ChapterInfo | None = None
    perception_mode: bool = False


def latest_chapter(scene: "Scene") -> ChapterInfo | None:
    """The newest summarized layer-0 entry; manual notes have no end."""
    entries = [
        entry for entry in scene.archived_history if entry.get("end") is not None
    ]
    if not entries:
        return None
    entry = entries[-1]
    return ChapterInfo(
        id=entry["id"],
        time=duration_to_human(max(0, scene.ts - (entry.get("ts") or 0))),
        start=entry.get("start"),
        end=entry.get("end"),
    )


class _Catalog:
    """One request's lookups, built once and shared across the facts."""

    def __init__(self, scene: "Scene", query: FactQuery):
        self.scene = scene
        self.query = query
        self.facts = scene.world_state.facts
        self.perception = character_knowledge_enabled(scene)
        self.chapter = latest_chapter(scene)
        # an entry's start and end are history indexes, not message ids
        self.message_index = {
            message.id: index for index, message in enumerate(scene.history)
        }
        self.topic_of = {
            fact_id: TopicOption(id=topic.id, name=topic.name)
            for topic in scene.world_state.topics.values()
            for fact_id in topic.fact_ids
        }
        self.topic_members = (
            set(scene.world_state.topics[query.topic_id].fact_ids)
            if query.topic_id in scene.world_state.topics
            else set()
        )
        self.aliases = aliases_for(scene, query.character) if query.character else set()
        # a name the cast no longer holds knows nothing, in either mode
        self.cast_member = query.character in scene.character_data
        self.known = (
            {fact.id for fact, _ in bucket(scene, query.character)}
            if query.character
            and self.cast_member
            and query.character_filter != "subject"
            else set()
        )
        self.superseded = superseded_fact_ids(scene)
        self.superseded_by = superseders(self.facts)
        self.needle = query.text.lower() if query.text else None
        self._index = None
        self._read = None
        self._cache = {}

    def in_latest_chapter(self, fact: Fact) -> bool:
        chapter = self.chapter
        if chapter is None:
            return False
        if fact.archive_id == chapter.id or any(
            item.source.kind == "summary" and item.source.id == chapter.id
            for item in fact.contributions
        ):
            return True
        if fact.message_id is None or chapter.start is None or chapter.end is None:
            return False
        index = self.message_index.get(fact.message_id, -1)
        return index >= 0 and chapter.start <= index <= chapter.end

    def matches(self, fact: Fact) -> bool:
        query = self.query
        if self.needle and not (
            self.needle in fact.text.lower()
            or self.needle == fact.id.lower()
            or any(self.needle in subject.lower() for subject in fact.subjects)
        ):
            return False
        if query.character:
            if query.character_filter != "subject" and not self.cast_member:
                return False
            if query.character_filter == "knows" and fact.id not in self.known:
                return False
            if query.character_filter == "unknown" and fact.id in self.known:
                return False
            if query.character_filter == "subject" and not (
                {subject.strip().casefold() for subject in fact.subjects} & self.aliases
            ):
                return False
        if query.topic_id and fact.id not in self.topic_members:
            return False
        if query.importance and fact.importance not in query.importance:
            return False
        if query.source and fact.source not in query.source:
            return False
        if (
            query.superseded is not None
            and (fact.id in self.superseded) != query.superseded
        ):
            return False
        if query.false is not None and fact.false != query.false:
            return False
        if query.latest_chapter and not self.in_latest_chapter(fact):
            return False
        return True

    def audience(self, fact: Fact) -> dict[str, KnownKind]:
        """Who knows this fact and how, computed for the page rows only."""
        result: dict[str, KnownKind] = {}
        if self.perception:
            if self._read is None:
                self._read = PerspectiveReadContext(self.scene)
            names = {name for item in fact.contributions for name in item.audience}
            for name in sorted(names & self.scene.character_data.keys()):
                view = character_fact(
                    self.scene, fact, name, read=self._read, cache=self._cache
                )
                if view is not None:
                    result[name] = perception_kind(view)
            return result
        if self._index is None:
            self._index = KnowledgeIndex.from_scene(self.scene)
        for name in self.scene.character_data:
            kind = standard_kind(self._index, name, fact)
            if kind is not None:
                result[name] = kind
        return result

    def row(self, fact: Fact) -> dict:
        topic = self.topic_of.get(fact.id)
        return {
            **fact_display(self.scene, fact),
            "topic": topic.model_dump() if topic is not None else None,
            "source_label": FACT_SOURCE_LABELS[fact.source],
            "source_id": source_id(fact),
            "audience": self.audience(fact),
            "superseded_by": self.superseded_by.get(fact.id, []),
        }


def superseders(facts: dict[str, Fact]) -> dict[str, list[str]]:
    """Author-level links only; every superseder, false ones included."""
    result: dict[str, list[str]] = {}
    for fact in facts.values():
        if fact.supersedes is not None and fact.supersedes in facts:
            result.setdefault(fact.supersedes, []).append(fact.id)
    return {key: sorted(value, key=numeric_id) for key, value in result.items()}


def source_id(fact: Fact) -> str | None:
    if fact.archive_id:
        return fact.archive_id
    if fact.message_id is not None:
        return str(fact.message_id)
    for item in fact.contributions:
        if item.source.kind == "disclosure":
            return str(item.source.id)
    return None


def _sort_key(fact: Fact, sort: FactSort, descending: bool):
    number = numeric_id(fact.id)
    ts = fact_timestamp(fact)
    # facts without a time sort last in both directions
    time_key = (ts is None, (-ts if descending else ts) if ts is not None else 0)
    if sort == "importance":
        return (-fact.importance if descending else fact.importance, *time_key, number)
    if sort == "id":
        return (-number if descending else number,)
    return (*time_key, -number if descending else number)


def list_facts(scene: "Scene", query: FactQuery) -> FactsPage:
    catalog = _Catalog(scene, query)
    matching = [fact for fact in catalog.facts.values() if catalog.matches(fact)]
    matching.sort(key=lambda fact: _sort_key(fact, query.sort, query.descending))
    start = (query.page - 1) * query.page_size
    return FactsPage(
        facts=[catalog.row(fact) for fact in matching[start : start + query.page_size]],
        total=len(matching),
        page=query.page,
        page_size=query.page_size,
        options=FactOptions(
            characters=sorted(scene.character_data),
            topics=[
                TopicOption(id=topic.id, name=topic.name)
                for topic in scene.world_state.topics.values()
            ],
            sources=[
                SourceOption(value=value, label=FACT_SOURCE_LABELS[value])
                for value in sorted({fact.source for fact in catalog.facts.values()})
            ],
        ),
        latest_chapter=catalog.chapter,
        perception_mode=catalog.perception,
    )
