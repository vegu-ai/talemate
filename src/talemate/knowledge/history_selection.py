from __future__ import annotations

from talemate.knowledge.transitions import (
    protected_transition,
    render_transition,
    transition_index,
)

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from talemate.knowledge.context import (
    ContextHistoryMessage,
    _project_character_message,
    history_prefix,
)
from talemate.knowledge.disclosures import disclosure_positions, disclosure_text
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import SourceReference
from talemate.knowledge.perspectives import (
    PerspectiveReadContext,
    select_character_view,
    source_reference,
)
from talemate.knowledge.summaries import summary_coverage, summary_spans
from talemate.scene_message import CharacterMessage, DirectorMessage
from talemate.util import count_tokens

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


@dataclass(frozen=True)
class HistorySelectionPolicy:
    best_fit: bool
    min_dialogue: int
    max_dialogue: int
    dialogue_ratio: int
    summary_detail_ratio: int
    enforce_boundary: bool
    layered_history_available: bool
    assured_dialogue_num: int = 5
    summary_boundary: int = 0

    @property
    def effective_max_dialogue(self) -> int:
        return max(0, self.min_dialogue, self.max_dialogue)


@dataclass(frozen=True)
class HistorySelectionEntry:
    text: str
    type: Literal["intro", "dialogue", "archived", "layer", "disclosure"]
    id: str | int
    layer: int
    token_count: int
    source_references: tuple[SourceReference, ...] = ()
    covered_message_ids: frozenset[int] = frozenset()
    covered_disclosure_ids: frozenset[str] = frozenset()
    message_id: int | None = None
    start: int = -1
    end: int = -1

    def rendered(self) -> str:
        if self.message_id is not None:
            return ContextHistoryMessage(self.text, self.message_id)
        return self.text


@dataclass(frozen=True)
class HistorySelectionResult:
    entries: tuple[HistorySelectionEntry, ...]
    policy: HistorySelectionPolicy
    budget: int
    allocations: dict[str, int]
    raw_message_count: int
    total_tokens: int
    overflow_tokens: int

    def rendered(self) -> list[str]:
        return [entry.rendered() for entry in self.entries if entry.text]


@dataclass
class _Node:
    entry: HistorySelectionEntry
    summary_entry: dict | None = None
    children: list[_Node] | None = None


@dataclass
class _RawSelection:
    nodes: list[_Node] = field(default_factory=list)
    scanned_to: int = -1
    exhausted: bool = False
    raw_ids: set[int] = field(default_factory=set)
    character_messages: int = 0

    @property
    def tokens(self) -> int:
        return sum(node.entry.token_count for node in self.nodes)


class _PerspectiveHistorySelector:
    def __init__(
        self,
        scene: Scene,
        character: str,
        budget: int,
        policy: HistorySelectionPolicy,
        *,
        before_message_id: int | None,
        keep_director: bool | str,
        show_hidden: bool,
        direction_mode: Literal["direction", "internal_monologue"],
        read: PerspectiveReadContext | None,
        diagnostics,
    ):
        if not character_knowledge_enabled(scene):
            raise ValueError("Character history projection requires perception mode")
        if character not in scene.character_data:
            raise ValueError(f"Unknown history perspective: {character}")
        self.scene = scene
        self.character = character
        self.budget = max(0, budget)
        self.policy = policy
        self.keep_director = keep_director
        self.show_hidden = show_hidden
        self.direction_mode = direction_mode
        self.diagnostics = diagnostics
        self.prefix = history_prefix(scene, before_message_id)
        self.read = read or PerspectiveReadContext(scene)
        self.views = {}
        self.coverage_cache = {}
        self.disclosures = {
            position: [item for item in items if character in item.audience]
            for position, items in disclosure_positions(scene).items()
            if position <= len(self.prefix)
        }
        self.disclosure_sequence = {
            item.id: index
            for index, item in enumerate(
                item for items in self.disclosures.values() for item in items
            )
        }
        if self.diagnostics is not None:
            for kind, identity, layer in self.read.sources:
                if kind not in ("summary", "intro"):
                    continue
                reference = source_reference(
                    self.scene, kind, identity, layer=layer, read=self.read
                )
                if reference is not None:
                    self._select(reference)
        self.summary_candidates = self._summary_candidates()

    def _select(self, reference: SourceReference):
        if reference not in self.views:
            view = select_character_view(
                self.scene, reference, self.character, read=self.read
            )
            self.views[reference] = view
            if self.diagnostics is not None and view.status != "ready":
                owners = self.read.sources.get(reference.key, [])
                text = owners[0].text if owners else ""
                kind = (
                    "layer"
                    if reference.kind == "summary" and reference.layer
                    else "archived"
                    if reference.kind == "summary"
                    else reference.kind
                )
                reason = (
                    "not_in_audience" if view.status == "unavailable" else view.status
                )
                if (
                    reference.kind == "intro"
                    and self.scene.intro_present is not None
                    and self.character not in self.scene.intro_present
                ):
                    reason = "absent"
                self.diagnostics.exclude(
                    kind,
                    reference.id,
                    text,
                    reason,
                    layer=(reference.layer - 1 if kind == "layer" else reference.layer),
                )
        return self.views[reference]

    def _summary_candidates(self) -> dict[int, list[tuple[int, SourceReference]]]:
        candidates: dict[int, list[tuple[int, SourceReference]]] = {}
        for end, values in summary_spans(self.scene, read=self.read).items():
            if end >= len(self.prefix):
                continue
            for start, reference in values:
                if reference.layer and not self.policy.layered_history_available:
                    continue
                candidates.setdefault(end, []).append((start, reference))
        for values in candidates.values():
            values.sort(key=lambda value: value[1].layer, reverse=True)
        return candidates

    def _disclosure_node(self, item, position: int) -> _Node:
        text = disclosure_text(item)
        reference = source_reference(self.scene, "disclosure", item.id, read=self.read)
        references = (reference,) if reference is not None else ()
        return _Node(
            HistorySelectionEntry(
                text=text,
                type="disclosure",
                id=item.id,
                layer=0,
                token_count=count_tokens(text),
                source_references=references,
                covered_disclosure_ids=frozenset((item.id,)),
                start=position,
                end=position,
            )
        )

    def _message_node(self, index: int) -> _Node | None:
        message = self.prefix[index]
        text = _project_character_message(
            self.scene,
            self.character,
            message,
            read=self.read,
            select=self._select,
            keep_director=self.keep_director,
            show_hidden=self.show_hidden,
            direction_mode=self.direction_mode,
            diagnostics=self.diagnostics,
        )
        if not text:
            return None
        reference = (
            source_reference(self.scene, "message", message.id, read=self.read)
            if message.supports_perceptions
            else None
        )
        selected = self._select(reference) if reference is not None else None
        selected_reference = selected.source if selected is not None else None
        return _Node(
            HistorySelectionEntry(
                text=text,
                type="dialogue",
                id=message.id,
                layer=0,
                token_count=count_tokens(text),
                source_references=(
                    (selected_reference,) if selected_reference is not None else ()
                ),
                covered_message_ids=(
                    frozenset((message.id,))
                    if selected_reference is not None
                    else frozenset()
                ),
                message_id=message.id,
                start=index,
                end=index,
            )
        )

    def _nodes_at(self, index: int) -> list[_Node]:
        nodes = []
        message = self._message_node(index)
        if message is not None:
            nodes.append(message)
        nodes.extend(
            self._disclosure_node(item, index + 1)
            for item in self.disclosures.get(index + 1, ())
        )
        return nodes

    @staticmethod
    def _represented_disclosures(nodes: list[_Node]) -> set[str]:
        return {
            identity for node in nodes for identity in node.entry.covered_disclosure_ids
        }

    def _disclosure_nodes_at(
        self,
        position: int,
        selected: list[_Node],
        represented: set[str] | None = None,
    ) -> list[_Node]:
        represented = (represented or set()) | self._represented_disclosures(selected)
        return [
            self._disclosure_node(item, position)
            for item in self.disclosures.get(position, ())
            if item.id not in represented
        ]

    def _raw_order(self, node: _Node):
        entry = node.entry
        return (
            entry.start,
            0 if entry.type == "disclosure" else 1,
            self.disclosure_sequence.get(str(entry.id), 0),
        )

    def _normalize_disclosures(self, nodes: list[_Node]) -> list[_Node]:
        covered = {
            identity
            for node in nodes
            if node.entry.type != "disclosure"
            for identity in node.entry.covered_disclosure_ids
        }
        explicit = set()
        normalized = []
        for node in nodes:
            if node.entry.type == "disclosure":
                identity = str(node.entry.id)
                if identity in covered or identity in explicit:
                    continue
                explicit.add(identity)
            normalized.append(node)
        return normalized

    @staticmethod
    def _raw_ids(nodes: list[_Node]) -> set[int]:
        return {
            node.entry.message_id
            for node in nodes
            if node.entry.type == "dialogue" and node.entry.source_references
        }

    def _raw_suffix(
        self,
        budget: int,
        *,
        minimum: int,
        maximum: int | None,
        boundary: int | None = None,
        assured_count: int = 0,
        boundary_raw_count: int | None = None,
    ) -> _RawSelection:
        result = _RawSelection(scanned_to=len(self.prefix) - 1)
        if budget <= 0 and minimum <= 0:
            return result
        deferred_optional = []

        def add_raw(node: _Node, index: int):
            result.nodes.append(node)
            result.raw_ids.update(self._raw_ids([node]))
            if isinstance(self.prefix[index], CharacterMessage):
                result.character_messages += 1

        def add_optional(nodes: list[_Node]):
            for node in nodes:
                if result.tokens + node.entry.token_count <= budget:
                    result.nodes.append(node)

        for index in range(len(self.prefix) - 1, -1, -1):
            if (
                boundary is not None
                and index < boundary
                and (
                    len(result.raw_ids) >= boundary_raw_count
                    if boundary_raw_count is not None
                    else result.character_messages >= assured_count
                )
            ):
                result.scanned_to = index
                break
            if len(result.raw_ids) >= minimum and result.tokens >= budget:
                result.scanned_to = index
                break
            if maximum is not None and len(result.raw_ids) >= maximum:
                result.scanned_to = index
                break
            group = self._nodes_at(index)
            group_ids = self._raw_ids(group)
            if maximum is not None and len(result.raw_ids | group_ids) > maximum:
                result.scanned_to = index
                break
            raw_nodes = [
                node
                for node in group
                if node.entry.type == "dialogue" and node.entry.source_references
            ]
            optional_nodes = [node for node in group if node not in raw_nodes]
            if len(result.raw_ids) < minimum:
                for node in raw_nodes:
                    add_raw(node, index)
                deferred_optional.extend(reversed(optional_nodes))
                if len(result.raw_ids) >= minimum:
                    add_optional(deferred_optional)
                    deferred_optional.clear()
                result.scanned_to = index - 1
                continue
            stop = False
            for node in reversed(group):
                if node in raw_nodes:
                    if result.tokens + node.entry.token_count > budget:
                        stop = True
                        break
                    add_raw(node, index)
                elif result.tokens + node.entry.token_count <= budget:
                    result.nodes.append(node)
            result.scanned_to = index - 1
            if stop:
                result.scanned_to = index
                break
        else:
            start_disclosures = [
                self._disclosure_node(item, 0) for item in self.disclosures.get(0, ())
            ]
            if len(result.raw_ids) < minimum:
                deferred_optional.extend(reversed(start_disclosures))
            else:
                add_optional(list(reversed(start_disclosures)))
            result.exhausted = True
            result.scanned_to = -1
        if deferred_optional:
            add_optional(deferred_optional)
        result.nodes.sort(key=self._raw_order)
        return result

    def _static_nodes(self, budget: int) -> list[_Node]:
        nodes = []
        used = 0
        for entry in self.scene.archived_history:
            if entry.get("start") is not None or entry.get("end") is not None:
                continue
            identity = entry.get("id")
            if not identity:
                continue
            reference = source_reference(
                self.scene, "summary", identity, read=self.read
            )
            if reference is None:
                continue
            view = self._select(reference)
            if view.status not in ("ready", "omitted"):
                continue
            text = view.text or ""
            cost = count_tokens(text) if text else 0
            if used + cost > budget:
                break
            nodes.append(
                _Node(
                    HistorySelectionEntry(
                        text=text,
                        type="archived",
                        id=identity,
                        layer=0,
                        token_count=cost,
                        source_references=(view.source,),
                    ),
                    summary_entry=entry,
                )
            )
            used += cost
        return nodes

    def _required_message_ids(self, start: int, end: int) -> set[int] | None:
        required = set()
        protected = protected_transition(self.scene, self.character)
        for message in self.prefix[start : end + 1]:
            if message is protected:
                return None
            if message.hidden and not self.show_hidden:
                return None
            if (
                isinstance(message, DirectorMessage)
                and self.keep_director
                and message.character_name == self.character
            ):
                return None
            if not message.supports_perceptions:
                continue
            reference = source_reference(
                self.scene, "message", message.id, read=self.read
            )
            if reference is None:
                continue
            if self._select(reference).status in ("ready", "pending", "failed"):
                required.add(message.id)
        return required

    def _summary_node(self, start: int, reference: SourceReference) -> _Node | None:
        end = next(
            (
                candidate_end
                for candidate_end, candidates in self.summary_candidates.items()
                if (start, reference) in candidates
            ),
            None,
        )
        if end is None:
            return None
        required = self._required_message_ids(start, end)
        if required is None:
            return None
        view = self._select(reference)
        if view.status not in ("ready", "omitted"):
            return None
        covered_messages = summary_coverage(
            view.source,
            self.character,
            read=self.read,
            cache=self.coverage_cache,
        )
        if not required <= covered_messages:
            return None
        covered_disclosures = summary_coverage(
            view.source,
            self.character,
            read=self.read,
            cache=self.coverage_cache,
            kind="disclosure",
        )
        required_disclosures = {
            item.id
            for position, items in self.disclosures.items()
            if start <= position <= end
            for item in items
        }
        if not required_disclosures <= covered_disclosures:
            return None
        owners = self.read.sources.get(reference.key, ())
        summary_entry = owners[0].owner if len(owners) == 1 else None
        text = view.text or ""
        return _Node(
            HistorySelectionEntry(
                text=text,
                type="layer" if reference.layer else "archived",
                id=reference.id,
                layer=reference.layer,
                token_count=count_tokens(text) if text else 0,
                source_references=(view.source,),
                covered_message_ids=frozenset(covered_messages),
                covered_disclosure_ids=frozenset(covered_disclosures),
                start=start,
                end=end,
            ),
            summary_entry=summary_entry,
        )

    def _compressed(
        self,
        start: int,
        end: int,
        budget: int,
        *,
        max_layer: int,
        raw_slots: int,
        include_end_boundary: bool = True,
        represented_disclosures: set[str] | None = None,
    ) -> tuple[list[_Node], int]:
        if budget <= 0:
            return [], end
        nodes: list[_Node] = []
        used = 0
        cursor = end
        raw_count = 0
        while cursor >= start:
            if used >= budget:
                break
            chosen = None
            for candidate_start, reference in self.summary_candidates.get(cursor, ()):
                if candidate_start < start or reference.layer > max_layer:
                    continue
                candidate = self._summary_node(candidate_start, reference)
                if candidate is None:
                    continue
                if used + candidate.entry.token_count <= budget:
                    chosen = candidate
                    break
            if chosen is not None:
                used += chosen.entry.token_count
                boundary = (
                    self._disclosure_nodes_at(
                        cursor + 1,
                        [chosen, *nodes],
                        represented_disclosures,
                    )
                    if include_end_boundary or cursor < end
                    else []
                )
                admitted = []
                for disclosure in reversed(boundary):
                    if used + disclosure.entry.token_count <= budget:
                        admitted.append(disclosure)
                        used += disclosure.entry.token_count
                nodes[0:0] = [chosen, *reversed(admitted)]
                cursor = chosen.entry.start - 1
                continue
            if raw_count >= raw_slots:
                disclosures = (
                    self._disclosure_nodes_at(
                        cursor + 1, nodes, represented_disclosures
                    )
                    if include_end_boundary or cursor < end
                    else []
                )
                for disclosure in reversed(disclosures):
                    if used + disclosure.entry.token_count <= budget:
                        nodes.insert(0, disclosure)
                        used += disclosure.entry.token_count
                cursor -= 1
                continue
            represented = (represented_disclosures or set()) | (
                self._represented_disclosures(nodes)
            )
            group = [
                node
                for node in self._nodes_at(cursor)
                if node.entry.type != "disclosure"
                or (
                    (include_end_boundary or cursor < end)
                    and str(node.entry.id) not in represented
                )
            ]
            group_raw = len(self._raw_ids(group))
            if raw_count + group_raw > raw_slots:
                cursor -= 1
                continue
            group_cost = sum(node.entry.token_count for node in group)
            if used + group_cost > budget:
                break
            nodes[0:0] = group
            used += group_cost
            raw_count += group_raw
            cursor -= 1
        if cursor < start:
            leading = self._disclosure_nodes_at(start, nodes, represented_disclosures)
            admitted = []
            for disclosure in reversed(leading):
                if used + disclosure.entry.token_count <= budget:
                    admitted.append(disclosure)
                    used += disclosure.entry.token_count
            nodes[0:0] = reversed(admitted)
        return nodes, cursor

    def _children(self, node: _Node) -> list[_Node] | None:
        if node.entry.type not in ("archived", "layer"):
            return None
        if node.children is not None:
            return node.children
        children, cursor = self._compressed(
            node.entry.start,
            node.entry.end,
            2**63 - 1,
            max_layer=node.entry.layer - 1,
            raw_slots=2**31 - 1,
            include_end_boundary=False,
        )
        covered_messages = frozenset(
            message_id
            for child in children
            for message_id in child.entry.covered_message_ids
        )
        covered_disclosures = frozenset(
            disclosure_id
            for child in children
            for disclosure_id in child.entry.covered_disclosure_ids
        )
        if (
            cursor >= node.entry.start
            or covered_messages != node.entry.covered_message_ids
            or covered_disclosures != node.entry.covered_disclosure_ids
        ):
            node.children = []
        else:
            node.children = children
        return node.children or None

    def _intro_node(self) -> _Node | None:
        reference = source_reference(self.scene, "intro", "intro", read=self.read)
        if reference is None:
            return None
        view = self._select(reference)
        if view.status != "ready":
            return None
        text = self.scene.get_intro(view.text, perspective=self.character)
        if not text:
            return None
        return _Node(
            HistorySelectionEntry(
                text=text,
                type="intro",
                id="intro",
                layer=0,
                token_count=count_tokens(text),
                source_references=(view.source,),
            )
        )

    def _carries_intro(self, nodes: list[_Node]) -> bool:
        return any(
            "intro"
            in summary_coverage(
                reference,
                self.character,
                read=self.read,
                cache=self.coverage_cache,
                kind="intro",
            )
            for node in nodes
            if node.entry.type in ("archived", "layer")
            for reference in node.entry.source_references
        )

    def _with_intro(self, collect):
        nodes, allocations = collect(self.budget)
        if self._carries_intro(nodes):
            return nodes, allocations
        intro = self._intro_node()
        if intro is None:
            return nodes, allocations
        floor_cost = self._minimum_cost(nodes)
        if floor_cost > self.budget - intro.entry.token_count:
            return nodes, allocations
        reduced, reduced_allocations = collect(
            max(0, self.budget - intro.entry.token_count)
        )
        if self._carries_intro(reduced):
            return reduced, reduced_allocations
        return [intro, *reduced], reduced_allocations

    def _minimum_cost(self, nodes: list[_Node]) -> int:
        if not self.policy.best_fit or self.policy.min_dialogue <= 0:
            return 0
        ids = set()
        cost = 0
        for index in range(len(nodes) - 1, -1, -1):
            node = nodes[index]
            entry = node.entry
            if entry.type != "dialogue" or not entry.source_references:
                continue
            ids.add(entry.message_id)
            cost += entry.token_count
            if len(ids) >= self.policy.min_dialogue:
                break
        return cost

    def _best_fit(self, budget: int):
        maximum = self.policy.effective_max_dialogue
        boundary = (
            self.policy.summary_boundary + 1
            if self.policy.summary_boundary > 0
            else None
        )
        raw = self._raw_suffix(
            budget,
            minimum=max(0, self.policy.min_dialogue),
            maximum=maximum,
            boundary=boundary,
            boundary_raw_count=max(0, self.policy.min_dialogue),
        )
        if raw.exhausted and raw.tokens <= budget:
            static = self._static_nodes(max(0, budget - raw.tokens))
            return [*static, *raw.nodes], {
                "dialogue": sum(node.entry.token_count for node in raw.nodes),
                "summaries": sum(node.entry.token_count for node in static),
            }
        remaining = max(0, budget - raw.tokens)
        max_layer = (
            len(self.scene.layered_history)
            if self.policy.layered_history_available
            else 0
        )
        compressed, _ = self._compressed(
            0,
            raw.scanned_to,
            remaining,
            max_layer=max_layer,
            raw_slots=max(0, maximum - len(raw.raw_ids)),
            represented_disclosures=self._represented_disclosures(raw.nodes),
        )
        static = self._static_nodes(
            max(0, remaining - sum(node.entry.token_count for node in compressed))
        )
        compressed = [*static, *compressed]
        selected = compressed
        used = sum(node.entry.token_count for node in compressed)
        raw_ids = self._raw_ids([*compressed, *raw.nodes])
        expansion_boundary = 0
        for layer in range(max_layer, -1, -1):
            candidates = [
                node
                for node in reversed(selected)
                if node.entry.type in ("archived", "layer")
                and node.entry.layer == layer
                and node.entry.start >= expansion_boundary
            ]
            for node in candidates:
                children = self._children(node)
                if not children:
                    expansion_boundary = max(expansion_boundary, node.entry.start)
                    break
                child_ids = self._raw_ids(children)
                if len(raw_ids | child_ids) > maximum:
                    expansion_boundary = max(expansion_boundary, node.entry.start)
                    break
                child_cost = sum(child.entry.token_count for child in children)
                delta = child_cost - node.entry.token_count
                if delta > remaining - used:
                    expansion_boundary = max(expansion_boundary, node.entry.start)
                    break
                index = selected.index(node)
                selected[index : index + 1] = children
                used += delta
                raw_ids.update(child_ids)
        return [*selected, *raw.nodes], {
            "dialogue": sum(node.entry.token_count for node in raw.nodes),
            "summaries": sum(node.entry.token_count for node in selected),
        }

    def _ratio_level(
        self,
        layer: int,
        cursor: int,
        budget: int,
        represented_disclosures: set[str],
    ) -> tuple[list[_Node], int]:
        nodes = []
        used = 0
        while cursor >= 0:
            matches = [
                (start, reference)
                for end in range(cursor, -1, -1)
                for start, reference in self.summary_candidates.get(end, ())
                if reference.layer == layer and start <= end
            ]
            if not matches:
                break
            start, reference = matches[0]
            end = next(
                value
                for value, candidates in self.summary_candidates.items()
                if (start, reference) in candidates
            )
            candidate = self._summary_node(start, reference)
            if candidate is None:
                fallback, remainder = self._compressed(
                    start,
                    end,
                    budget - used,
                    max_layer=layer - 1,
                    raw_slots=2**31 - 1,
                    include_end_boundary=False,
                    represented_disclosures=represented_disclosures,
                )
                if remainder >= start:
                    cursor = start - 1
                    continue
                cost = sum(node.entry.token_count for node in fallback)
                if used + cost > budget:
                    break
                used += cost
                represented_disclosures.update(self._represented_disclosures(fallback))
                boundary = self._disclosure_nodes_at(
                    end + 1,
                    [*fallback, *nodes],
                    represented_disclosures,
                )
                admitted = []
                for disclosure in reversed(boundary):
                    if used + disclosure.entry.token_count <= budget:
                        admitted.append(disclosure)
                        used += disclosure.entry.token_count
                        represented_disclosures.update(
                            disclosure.entry.covered_disclosure_ids
                        )
                nodes[0:0] = [*fallback, *reversed(admitted)]
                cursor = start - 1
                continue
            if used + candidate.entry.token_count > budget:
                break
            used += candidate.entry.token_count
            represented_disclosures.update(candidate.entry.covered_disclosure_ids)
            boundary = self._disclosure_nodes_at(
                end + 1,
                [candidate, *nodes],
                represented_disclosures,
            )
            admitted = []
            for disclosure in reversed(boundary):
                if used + disclosure.entry.token_count <= budget:
                    admitted.append(disclosure)
                    used += disclosure.entry.token_count
                    represented_disclosures.update(
                        disclosure.entry.covered_disclosure_ids
                    )
            nodes[0:0] = [candidate, *reversed(admitted)]
            cursor = start - 1
        return nodes, cursor

    def _ratio(self, budget: int):
        dialogue_budget = budget * self.policy.dialogue_ratio // 100
        raw = self._raw_suffix(
            dialogue_budget,
            minimum=0,
            maximum=None,
            boundary=(
                self.policy.summary_boundary if self.policy.enforce_boundary else None
            ),
            assured_count=self.policy.assured_dialogue_num,
        )
        summary_budget = max(0, budget - dialogue_budget)
        max_layer = (
            len(self.scene.layered_history)
            if self.policy.layered_history_available
            else 0
        )
        level_budgets = []
        remaining = summary_budget
        for layer in range(max_layer + 1):
            if layer == max_layer:
                level_budgets.append(remaining)
            else:
                allocation = remaining * self.policy.summary_detail_ratio // 100
                level_budgets.append(allocation)
                remaining -= allocation
        cursor = raw.scanned_to
        summary_nodes = []
        static_nodes = []
        represented_disclosures = self._represented_disclosures(raw.nodes)
        for layer, allocation in enumerate(level_budgets):
            selected, cursor = self._ratio_level(
                layer,
                cursor,
                allocation,
                represented_disclosures,
            )
            if layer == 0:
                static_nodes = self._static_nodes(
                    max(
                        0,
                        allocation - sum(node.entry.token_count for node in selected),
                    )
                )
            summary_nodes[0:0] = selected
        allocations = {
            "dialogue": dialogue_budget,
            "archived": level_budgets[0] if level_budgets else 0,
            **{
                f"layer_{index}": allocation
                for index, allocation in enumerate(level_budgets[1:])
            },
        }
        return [*static_nodes, *summary_nodes, *raw.nodes], allocations

    def select(self) -> HistorySelectionResult:
        collect = self._best_fit if self.policy.best_fit else self._ratio
        nodes, allocations = self._with_intro(collect)
        nodes = self._normalize_disclosures(nodes)
        protected = protected_transition(self.scene, self.character)
        if (
            protected is not None
            and protected in self.prefix
            and not any(node.entry.message_id == protected.id for node in nodes)
        ):
            index = transition_index(self.scene, protected)
            node = self._message_node(index)
            if node is not None:
                position = next(
                    (i for i, item in enumerate(nodes) if item.entry.start > index),
                    len(nodes),
                )
                nodes.insert(position, node)
        if protected is not None:
            for node in nodes:
                if node.entry.message_id == protected.id:
                    available = max(
                        0,
                        self.budget
                        - sum(
                            other.entry.token_count
                            for other in nodes
                            if other is not node
                        ),
                    )
                    text = render_transition(self.scene, protected, budget=available)
                    node.entry = replace(
                        node.entry, text=text, token_count=count_tokens(text)
                    )
        entries = tuple(node.entry for node in nodes if node.entry.text)
        total = sum(entry.token_count for entry in entries)
        raw_count = len(
            {
                entry.message_id
                for entry in entries
                if entry.type == "dialogue" and entry.source_references
            }
        )
        return HistorySelectionResult(
            entries=entries,
            policy=self.policy,
            budget=self.budget,
            allocations=allocations,
            raw_message_count=raw_count,
            total_tokens=total,
            overflow_tokens=max(0, total - self.budget),
        )


def select_character_history(
    scene: Scene,
    character: str,
    *,
    budget: int,
    policy: HistorySelectionPolicy,
    before_message_id: int | None = None,
    keep_director: bool | str = False,
    show_hidden: bool = False,
    direction_mode: Literal["direction", "internal_monologue"] = "direction",
    read: PerspectiveReadContext | None = None,
    diagnostics=None,
) -> HistorySelectionResult:
    return _PerspectiveHistorySelector(
        scene,
        character,
        budget,
        policy,
        before_message_id=before_message_id,
        keep_director=keep_director,
        show_hidden=show_hidden,
        direction_mode=direction_mode,
        read=read,
        diagnostics=diagnostics,
    ).select()
