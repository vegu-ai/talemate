from typing import TYPE_CHECKING, ClassVar

import structlog

from talemate.context import active_scene
from talemate.game.engine.nodes.focal import Metadata
from talemate.game.engine.nodes.string import AdvancedFormat
from talemate.instance import get_agent
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import source_reference
from talemate.knowledge.entry import (
    VISIBILITY_KINDS,
    character_knowledge_report,
    entry_knowledge,
    known_by_line,
    set_edge,
    sheet_visibility_key,
)
from talemate.knowledge.graph import (
    current_state,
    facts_about,
    relationship_timeline,
)
from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge

from .core import GraphState, InputValueError, Node, PropertyField, TYPE_CHOICES
from .registry import register

if TYPE_CHECKING:
    from talemate.character import Character

log = structlog.get_logger("talemate.game.engine.nodes.knowledge")

TYPE_CHOICES.extend(["knowledge/fact"])


def _fact_dicts(facts) -> list[dict]:
    return [fact.model_dump() for fact in facts]


@register("knowledge/FactsAbout")
class FactsAbout(Node):
    """
    Facts recorded about an entity (character, item or place), oldest first.

    Inputs:
    - entity: name of the entity
    - character: optional, only the facts this character knows

    Outputs:
    - facts: list of fact dicts
    - text: the facts as one line per fact
    """

    def __init__(self, title="Facts About", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("entity", socket_type="str")
        self.add_input("character", socket_type="str", optional=True)
        self.add_output("facts", socket_type="list")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        entity = self.require_input("entity")
        character = self.normalized_input_value("character")
        facts = facts_about(scene, entity, character=character or None)
        self.set_output_values(
            {
                "facts": _fact_dicts(facts),
                "text": "\n".join(f"[{f.id}] {f.text}" for f in facts),
            }
        )


@register("knowledge/CurrentState")
class CurrentState(Node):
    """
    The newest fact about an entity that no later accessible fact supersedes.

    Inputs:
    - entity: name of the entity
    - character: perspective; omitted queries global author state

    Outputs:
    - fact: the fact dict, or None
    - text: the fact text, or an empty string
    """

    def __init__(self, title="Current State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("entity", socket_type="str")
        self.add_input("character", socket_type="str", optional=True)
        self.add_output("fact", socket_type="knowledge/fact")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        fact = current_state(
            scene,
            self.require_input("entity"),
            character=self.normalized_input_value("character") or None,
        )
        self.set_output_values(
            {
                "fact": fact.model_dump() if fact else None,
                "text": fact.text if fact else "",
            }
        )


@register("knowledge/RelationshipTimeline")
class RelationshipTimeline(Node):
    """
    Facts that mention both entities, oldest first.

    Inputs:
    - a: first entity
    - b: second entity
    - character: perspective; omitted queries global author state

    Outputs:
    - facts: list of fact dicts
    - text: one line per fact
    """

    def __init__(self, title="Relationship Timeline", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("a", socket_type="str")
        self.add_input("b", socket_type="str")
        self.add_input("character", socket_type="str", optional=True)
        self.add_output("facts", socket_type="list")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        facts = relationship_timeline(
            scene,
            self.require_input("a"),
            self.require_input("b"),
            character=self.normalized_input_value("character") or None,
        )
        self.set_output_values(
            {
                "facts": _fact_dicts(facts),
                "text": "\n".join(f"[{f.id}] {f.text}" for f in facts),
            }
        )


def _character_name(value: "str | Character") -> str:
    return value if isinstance(value, str) else value.name


class _EdgeNode(Node):
    kind: ClassVar[str] = "grant"

    class Fields:
        note = PropertyField(
            name="note",
            description="Optional note stored on the edge",
            type="str",
            default="",
        )
        source = PropertyField(
            name="source",
            description="Where the edge comes from",
            type="str",
            default="granted",
            choices=["told", "granted", "inferred", "manual", "director"],
        )
        replace = PropertyField(
            name="replace",
            description="Keep one edge per character and entry: the new edge replaces an existing grant or revoke for the pair",
            type="bool",
            default=False,
        )

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="str,character")
        self.add_input("target", socket_type="str", optional=True, group="target")
        self.add_input(
            "context_id_item",
            socket_type="context_id_item",
            optional=True,
            group="target",
        )
        self.add_input("note", socket_type="str", optional=True)
        self.set_property("note", "")
        self.set_property("source", "granted")
        self.set_property("replace", False)
        self.add_output("state")
        self.add_output("edge", socket_type="dict")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        character = _character_name(self.require_input("character"))
        target = self.normalized_input_value("target")
        item = self.normalized_input_value("context_id_item")
        if item is not None:
            target = item.knowledge_id
            if not target:
                raise InputValueError(
                    self,
                    "context_id_item",
                    f"`{item.context_id}` is not an entry a character can know or not know.",
                )
        if not target:
            raise InputValueError(
                self, "target", "Either target or context_id_item must be set"
            )
        note = self.normalized_input_value("note") or None
        edge = KnowledgeEdge(
            character=character,
            target=target,
            kind=self.kind,
            source=self.get_property("source"),
            note=note,
        )
        set_edge(scene, edge, replace=self.get_property("replace"), item=item)
        self.set_output_values(
            {
                "state": self.normalized_input_value("state"),
                "edge": edge.model_dump(),
                "text": known_by_line(scene, item if item is not None else edge.target),
            }
        )


@register("knowledge/GrantKnowledge")
class GrantKnowledge(_EdgeNode):
    """
    Establish selected information in perception mode, or a whole-entry edge in legacy mode.
    Disclosures are acquired now without inventing dialogue; whole_entry explicitly copies all source text.

    Inputs:
    - state: graph state (passthrough)
    - character: character name or character
    - target: existing entry id (or give context_id_item)
    - context_id_item: resolved source entry (or give target)
    - note: optional note on legacy edges
    - information: selected text; required for partial disclosures
    - whole_entry: false by default; true copies all current source content

    Outputs:
    - state: graph state
    - edge: legacy edge, or None in perception mode
    - text: disclosure result or the legacy Known by line
    - disclosure: saved disclosure in perception mode
    """

    class Fields(_EdgeNode.Fields):
        whole_entry = PropertyField(
            name="whole_entry",
            type="bool",
            default=False,
            description="True copies all source content, including private details; False discloses only the supplied information.",
        )

    kind: ClassVar[str] = "grant"

    def __init__(self, title="Grant Knowledge", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.add_input("information", socket_type="str", optional=True)
        self.add_input("whole_entry", socket_type="bool", optional=True)
        self.set_property("whole_entry", False)
        self.add_output("disclosure", socket_type="dict")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        if not character_knowledge_enabled(scene):
            return await super().run(state)
        item = self.normalized_input_value("context_id_item")
        target = (
            item.knowledge_id
            if item is not None
            else self.normalized_input_value("target")
        )
        try:
            disclosure = scene.world_state_manager.grant_character_disclosure(
                _character_name(self.require_input("character")),
                target,
                text=self.normalized_input_value("information"),
                whole_entry=self.normalized_input_value("whole_entry") or False,
            )
        except ValueError as exc:
            raise InputValueError(self, "target", str(exc)) from exc
        status = await get_agent("summarizer").rebuild_supported_facts(
            scene, [source_reference(scene, "disclosure", disclosure.id)]
        )
        self.set_output_values(
            {
                "state": self.normalized_input_value("state"),
                "edge": None,
                "disclosure": disclosure.model_dump(),
                "text": f"Established for {', '.join(disclosure.audience)}: {disclosure.text}"
                + (
                    " (Fact extraction failed; the disclosure is saved.)"
                    if status == "failed"
                    else ""
                ),
            }
        )


@register("knowledge/RevokeKnowledge")
class RevokeKnowledge(_EdgeNode):
    """
    Revoke a character's knowledge of an entry.

    Inputs:
    - state: graph state (passthrough)
    - character: character name or character
    - target: entry id (or give context_id_item)
    - context_id_item: the entry as a Context ID item (or give target)
    - note: optional note stored on the edge

    Outputs:
    - state: graph state
    - edge: the stored edge
    - text: the entry's Known by line after the change
    """

    kind: ClassVar[str] = "revoke"

    def __init__(self, title="Revoke Knowledge", **kwargs):
        super().__init__(title=title, **kwargs)


@register("knowledge/EntryKnowledge")
class EntryKnowledgeNode(Node):
    """
    Who knows a context entry: its Known by setting (or the presence of a
    history entry) and the grant and revoke edges pointing at it.

    Inputs:

    - context_id_item: the entry as a Context ID item

    Outputs:

    - context_id_item: the input, passed through
    - entry_id: the id knowledge edges use for the entry, or None
    - text: the Known by line, empty when the entry cannot be known or unknown
    - visibility: the Known by setting as a dict, or None
    - grants: list of grant edge dicts
    - revokes: list of revoke edge dicts
    """

    def __init__(self, title="Entry Knowledge", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("context_id_item", socket_type="context_id_item")
        self.add_output("context_id_item", socket_type="context_id_item")
        self.add_output("entry_id", socket_type="str")
        self.add_output("text", socket_type="str")
        self.add_output("visibility", socket_type="dict")
        self.add_output("grants", socket_type="list")
        self.add_output("revokes", socket_type="list")

    async def run(self, state: GraphState):
        item = self.require_input("context_id_item")
        entry_id = item.knowledge_id
        outputs = {
            "context_id_item": item,
            "entry_id": entry_id,
            "text": "",
            "visibility": None,
            "grants": [],
            "revokes": [],
        }
        if entry_id:
            entry = entry_knowledge(active_scene.get(), item)
            outputs.update(
                {
                    "text": entry.line,
                    "visibility": entry.visibility.model_dump()
                    if entry.visibility
                    else None,
                    "grants": [e.model_dump() for e in entry.grants],
                    "revokes": [e.model_dump() for e in entry.revokes],
                }
            )
        self.set_output_values(outputs)


@register("knowledge/SetEntryVisibility")
class SetEntryVisibility(Node):
    """
    Set the Known by setting of a character sheet entry (description,
    attribute, detail) or a world entry.

    Inputs:

    - state: graph state (passthrough)
    - context_id_item: the entry as a Context ID item
    - mode: everyone, owner or list (required)
    - characters: the character names for the list mode

    Outputs:

    - state: graph state
    - entry_id: the id knowledge edges use for the entry
    - text: the entry's Known by line after the change
    """

    class Fields:
        mode = PropertyField(
            name="mode",
            description="Who knows the entry",
            type="str",
            default="everyone",
            choices=["everyone", "owner", "list"],
        )

    def __init__(self, title="Set Entry Visibility", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("context_id_item", socket_type="context_id_item")
        self.add_input("mode", socket_type="str")
        self.add_input("characters", socket_type="list", optional=True)
        self.set_property("mode", "everyone")
        self.add_output("state")
        self.add_output("entry_id", socket_type="str")
        self.add_output("text", socket_type="str")

    def _resolve_names(self, scene, names) -> list[str]:
        by_lower = {name.lower(): name for name in scene.character_data}
        resolved = []

        def add(name: str):
            canonical = by_lower.get(name.strip().lower())
            if not canonical:
                raise InputValueError(
                    self, "characters", f"Character `{name}` does not exist."
                )
            if canonical not in resolved:
                resolved.append(canonical)

        for name in names or []:
            name = str(name)
            if not name.strip():
                continue
            # a list argument arrives split on newlines, so "Alice, Carol" is
            # one item; a name that carries a comma still resolves whole
            if name.strip().lower() in by_lower or "," not in name:
                add(name)
                continue
            for part in name.split(","):
                if part.strip():
                    add(part)
        return resolved

    async def run(self, state: GraphState):
        scene = active_scene.get()
        item = self.require_input("context_id_item")
        mode = self.require_input("mode")
        mode = mode.strip().lower() if isinstance(mode, str) else ""
        if mode not in ("everyone", "owner", "list"):
            raise InputValueError(
                self, "mode", f"`{mode}` is not one of everyone, owner, list."
            )
        entry = entry_knowledge(scene, item)
        if entry.kind not in VISIBILITY_KINDS:
            raise InputValueError(
                self,
                "context_id_item",
                f"Known by applies to character sheet entries and world entries; `{item.context_id}` is neither.",
            )
        characters = self._resolve_names(
            scene, self.normalized_input_value("characters")
        )
        if mode == "list" and not characters:
            raise InputValueError(
                self, "characters", "The list mode needs at least one character."
            )
        visibility = EntryVisibility(
            mode=mode, characters=characters if mode == "list" else []
        )
        manager = scene.world_state_manager
        if entry.kind == "world_entry":
            await manager.set_world_entry_visibility(entry.id, visibility)
        else:
            await manager.set_character_entry_visibility(
                entry.owner, sheet_visibility_key(entry), visibility
            )
        self.set_output_values(
            {
                "state": self.normalized_input_value("state"),
                "entry_id": entry.id,
                "text": known_by_line(scene, entry.id),
            }
        )


@register("knowledge/CharacterKnowledge")
class CharacterKnowledge(Node):
    """
    What one character knows, as prompt text and without an LLM request:
    their grants and revokes with entry labels, the restricted entries they
    can see, the topic coverage and the awareness line.

    Inputs:

    - character: character name or character

    Outputs:

    - character: the character name
    - text: the report
    """

    def __init__(self, title="Character Knowledge", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="str,character")
        self.add_output("character", socket_type="str")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        name = _character_name(self.require_input("character"))
        self.set_output_values(
            {
                "character": name,
                "text": character_knowledge_report(active_scene.get(), name),
            }
        )


@register("knowledge/GrantKnowledgeMetadata")
class GrantKnowledgeMetadata(Metadata):
    """Director grant metadata selected by the shared character-knowledge gate.

    Properties:
    - instructions: legacy entry-grant instructions
    - examples: legacy entry-grant examples
    - perception_instructions: instructions for explicit disclosures
    - perception_examples: selected-text and whole-entry disclosure examples
    """

    class Fields(Metadata.Fields):
        perception_instructions = PropertyField(
            name="perception_instructions",
            type="text",
            default="",
            description="Instructions used only when character perceptions are internally enabled.",
        )
        perception_examples = PropertyField(
            name="perception_examples",
            type="list",
            default=[],
            description="Disclosure examples used only when character perceptions are internally enabled.",
        )

    def __init__(self, title="Grant Knowledge Metadata", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.set_property("perception_instructions", "")
        self.set_property("perception_examples", [])

    def normalized_input_value(self, input_name, none_is_set=False):
        if input_name in ("instructions", "examples") and character_knowledge_enabled(
            active_scene.get()
        ):
            input_name = f"perception_{input_name}"
        return super().normalized_input_value(input_name, none_is_set=none_is_set)


@register("knowledge/GrantKnowledgeConfirmation")
class GrantKnowledgeConfirmation(AdvancedFormat):
    """Format the director grant confirmation for the scene's knowledge mode.

    Properties:
    - template: legacy entry-grant confirmation
    - perception_template: confirmation showing selected information or explicit whole-entry copying
    """

    class Fields(AdvancedFormat.Fields):
        perception_template = PropertyField(
            name="perception_template",
            type="text",
            default="",
            description="Disclosure confirmation used only when character perceptions are internally enabled.",
        )

    def __init__(self, title="Grant Knowledge Confirmation", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        super().setup()
        self.set_property("perception_template", "")

    async def format(self, template, variables):
        if character_knowledge_enabled(active_scene.get()):
            template = self.get_property("perception_template")
        return await super().format(template, variables)
