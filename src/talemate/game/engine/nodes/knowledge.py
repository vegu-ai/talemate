from typing import ClassVar

import structlog

from talemate.context import active_scene
from talemate.game.engine.nodes.focal import Metadata
from talemate.game.engine.nodes.data import ListCollector
from talemate.game.engine.nodes.string import AdvancedFormat
from talemate.character import character_name
from talemate.instance import get_agent
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.disclosures import disclose
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.entry import (
    VISIBILITY_KINDS,
    character_knowledge_report,
    entry_knowledge,
    known_by_line,
    set_edge,
    sheet_visibility_key,
    resolve_character_names,
)
from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge

from .core import GraphState, InputValueError, Node, PropertyField
from .registry import register

log = structlog.get_logger("talemate.game.engine.nodes.knowledge")


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
            description="Keep one edge per character and entry: the new edge replaces an existing grant or revoke for the pair. Without it, an earlier Never Learn stays and still wins over a new grant",
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
        if self.kind == "revoke" and character_knowledge_enabled(scene):
            raise InputValueError(
                self, "character", "Revokes are unavailable in perception mode."
            )
        character = character_name(self.require_input("character"))
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
    In legacy mode a grant does not lift an earlier Never Learn for the same entry unless
    `replace` is on; the World Editor's Learn lifts it.

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
                character_name(self.require_input("character")),
                target,
                text=self.normalized_input_value("information"),
                whole_entry=self.normalized_input_value("whole_entry") or False,
            )
        except ValueError as exc:
            raise InputValueError(self, "target", str(exc)) from exc
        await get_agent("memory").ensure_audience_index(scene)
        self.set_output_values(
            {
                "state": self.normalized_input_value("state"),
                "edge": None,
                "disclosure": disclosure.model_dump(),
                "text": f"Established for {', '.join(disclosure.audience)}: {disclosure.text}",
            }
        )


@register("knowledge/RevokeKnowledge")
class RevokeKnowledge(_EdgeNode):
    """
    Revoke a character's knowledge of an entry in legacy scenes.
    Perception scenes reject this operation before mutation; no amnesia is provided.

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
        try:
            return resolve_character_names(scene, names or [])
        except ValueError as exc:
            raise InputValueError(self, "characters", str(exc)) from exc

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


@register("knowledge/SetStaticHistoryKnownBy")
class SetStaticHistoryKnownBy(Node):
    """
    Set who knows a static history entry, in Standard knowledge scenes:
    everyone, nobody, or the listed characters.

    Inputs:

    - state: graph state (passthrough)
    - context_id_item: the static history entry as a Context ID item
    - mode: everyone, nobody or list (required)
    - characters: the character names for the list mode

    Outputs:

    - state: graph state
    - entry_id: the static history entry id
    - present: the characters who know it, or None for everyone
    - text: the entry's Known by line after the change
    """

    class Fields:
        mode = PropertyField(
            name="mode",
            description="Who knows the entry",
            type="str",
            default="everyone",
            choices=["everyone", "nobody", "list"],
        )

    def __init__(self, title="Set Static History Known By", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("context_id_item", socket_type="context_id_item")
        self.add_input("mode", socket_type="str")
        self.add_input("characters", socket_type="list", optional=True)
        self.set_property("mode", "everyone")
        self.add_output("state")
        self.add_output("entry_id", socket_type="str")
        self.add_output("present", socket_type="list")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        item = self.require_input("context_id_item")
        mode = self.require_input("mode")
        mode = mode.strip().lower() if isinstance(mode, str) else ""
        if mode not in ("everyone", "nobody", "list"):
            raise InputValueError(
                self, "mode", f"`{mode}` is not one of everyone, nobody, list."
            )
        entry = entry_knowledge(scene, item)
        if entry.kind != "static":
            raise InputValueError(
                self,
                "context_id_item",
                f"`{item.context_id}` is not a static history entry.",
            )
        try:
            characters = resolve_character_names(
                scene, self.normalized_input_value("characters") or []
            )
        except ValueError as exc:
            raise InputValueError(self, "characters", str(exc)) from exc
        if mode == "list" and not characters:
            raise InputValueError(
                self, "characters", "The list mode needs at least one character."
            )
        visibility = EntryVisibility(
            mode={"everyone": "everyone", "nobody": "owner", "list": "list"}[mode],
            characters=characters if mode == "list" else [],
        )
        try:
            present = await scene.world_state_manager.set_static_history_known_by(
                entry.id, visibility
            )
        except ValueError as exc:
            raise InputValueError(self, "context_id_item", str(exc)) from exc
        self.set_output_values(
            {
                "state": self.normalized_input_value("state"),
                "entry_id": entry.id,
                "present": present,
                "text": known_by_line(scene, entry.id),
            }
        )


@register("knowledge/CharacterKnowledge")
class CharacterKnowledge(Node):
    """
    Report one character's knowledge without an LLM request: grants with entry
    labels and accessible restricted entries. Legacy
    reports also include revokes; perception reports include disclosures.

    Inputs:

    - character: character name or character

    Outputs:

    - character: the character name
    - text: the report
    - grants: the character's Learn edges as dicts
    - revokes: the character's Never Learn edges as dicts (Standard only)
    - disclosures: disclosures shared with the character as dicts (Character Perspectives only)
    """

    def __init__(self, title="Character Knowledge", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="str,character")
        self.add_output("character", socket_type="str")
        self.add_output("text", socket_type="str")
        self.add_output("grants", socket_type="list")
        self.add_output("revokes", socket_type="list")
        self.add_output("disclosures", socket_type="list")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        name = character_name(self.require_input("character"))
        knowledge = await scene.world_state_manager.get_character_knowledge(name)
        self.set_output_values(
            {
                "character": name,
                "text": character_knowledge_report(scene, name),
                "grants": [
                    e.model_dump() for e in knowledge.edges if e.kind == "grant"
                ],
                "revokes": [
                    e.model_dump() for e in knowledge.edges if e.kind == "revoke"
                ],
                "disclosures": [d.model_dump() for d in knowledge.disclosures],
            }
        )


@register("knowledge/CharacterKnowsEntry")
class CharacterKnowsEntry(Node):
    """
    Whether a character knows an entry: a character sheet entry, a world entry
    or a history entry, by the same rule that decides what reaches the
    character's memories. Answers without an LLM request.

    Reasons for not knowing: revoke (a Never Learn rule), visibility (the
    entry's Known by leaves the character out) or presence (the character did
    not witness the history entry).

    Inputs:

    - character: character name or character
    - target: entry id (or give context_id_item)
    - context_id_item: the entry as a Context ID item (or give target)

    Outputs:

    - known: True when the character knows the entry
    - reason: why not, or None
    - entry_id: the id knowledge edges use for the entry
    """

    def __init__(self, title="Character Knows Entry", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="str,character")
        self.add_input("target", socket_type="str", optional=True, group="target")
        self.add_input(
            "context_id_item",
            socket_type="context_id_item",
            optional=True,
            group="target",
        )
        self.add_output("known", socket_type="bool")
        self.add_output("reason", socket_type="str")
        self.add_output("entry_id", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        character = character_name(self.require_input("character"))
        item = self.normalized_input_value("context_id_item")
        target = (
            item.knowledge_id
            if item is not None
            else self.normalized_input_value("target")
        )
        if not target:
            raise InputValueError(
                self, "target", "Either target or context_id_item must be set"
            )
        entry = entry_knowledge(scene, item if item is not None else target)
        if entry.kind == "unknown":
            raise InputValueError(self, "target", f"`{target}` names no entry.")
        index = KnowledgeIndex.from_scene(scene)
        reason = index.rejection(character, index.item_for_entry(scene, entry.id))
        self.set_output_values(
            {"known": reason is None, "reason": reason, "entry_id": entry.id}
        )


@register("knowledge/RemoveKnowledgeEdge")
class RemoveKnowledgeEdge(Node):
    """
    Remove Learn and Never Learn rules: one edge by its id, or every edge
    between a character and an entry. What the character knows then follows
    the entry's Known by setting again.

    Inputs:

    - state: graph state (passthrough)
    - edge_id: the id of one edge (or give character and target)
    - character: character name or character
    - target: entry id

    Outputs:

    - state: graph state
    - removed: the removed edges as dicts
    - text: the entry's Known by line after the change
    """

    def __init__(self, title="Remove Knowledge Edge", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("edge_id", socket_type="str", optional=True)
        self.add_input("character", socket_type="str,character", optional=True)
        self.add_input("target", socket_type="str", optional=True)
        self.add_output("state")
        self.add_output("removed", socket_type="list")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        edge_id = self.normalized_input_value("edge_id")
        character = self.normalized_input_value("character")
        target = self.normalized_input_value("target")
        edges = scene.world_state.knowledge
        if edge_id:
            ids = [e.id for e in edges if e.id == edge_id]
        elif character and target:
            name = character_name(character)
            ids = [e.id for e in edges if e.character == name and e.target == target]
        else:
            raise InputValueError(
                self, "edge_id", "Give edge_id, or character and target."
            )
        removed = []
        for identity in ids:
            edge = await scene.world_state_manager.remove_knowledge_edge(identity)
            if edge is not None:
                removed.append(edge)
        entry = target or (removed[0].target if removed else None)
        self.set_output_values(
            {
                "state": self.normalized_input_value("state"),
                "removed": [e.model_dump() for e in removed],
                "text": known_by_line(scene, entry) if entry else "",
            }
        )


@register("knowledge/AddDisclosure")
class AddDisclosure(Node):
    """
    Share information with one or more characters from now on, as a
    disclosure: they know the text, whether or not it comes from an entry.
    Character Perspectives only; in Standard scenes use Grant Knowledge.

    Inputs:

    - state: graph state (passthrough)
    - text: the information
    - characters: the character names

    Outputs:

    - state: graph state
    - disclosure: the saved disclosure as a dict
    """

    class Fields:
        text = PropertyField(
            name="text",
            description="The information to share",
            type="text",
            default="",
        )

    def __init__(self, title="Add Disclosure", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("state")
        self.add_input("text", socket_type="str", optional=True)
        self.add_input("characters", socket_type="list")
        self.set_property("text", "")
        self.add_output("state")
        self.add_output("disclosure", socket_type="dict")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        if not character_knowledge_enabled(scene):
            raise InputValueError(
                self, "characters", "Disclosures need Character Perspectives."
            )
        text = self.normalized_input_value("text")
        if not text or not str(text).strip():
            raise InputValueError(self, "text", "The information is empty.")
        try:
            characters = resolve_character_names(
                scene, self.require_input("characters") or []
            )
        except ValueError as exc:
            raise InputValueError(self, "characters", str(exc)) from exc
        if not characters:
            raise InputValueError(self, "characters", "Name at least one character.")
        try:
            disclosure = disclose(scene, str(text).strip(), characters)
        except ValueError as exc:
            raise InputValueError(self, "characters", str(exc)) from exc
        await get_agent("memory").ensure_audience_index(scene)
        self.set_output_values(
            {
                "state": self.normalized_input_value("state"),
                "disclosure": disclosure.model_dump(),
            }
        )


@register("knowledge/ListDisclosures")
class ListDisclosures(Node):
    """
    The disclosures of a Character Perspectives scene, optionally only those
    shared with one character. Empty in Standard scenes.

    Inputs:

    - character: character name or character (optional)

    Outputs:

    - disclosures: list of disclosure dicts (id, text, audience, origin ...)
    """

    def __init__(self, title="List Disclosures", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("character", socket_type="str,character", optional=True)
        self.add_output("disclosures", socket_type="list")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        character = self.normalized_input_value("character")
        name = character_name(character) if character else None
        disclosures = (
            scene.knowledge.disclosures
            if scene.knowledge and character_knowledge_enabled(scene)
            else ()
        )
        self.set_output_values(
            {
                "disclosures": [
                    d.model_dump()
                    for d in disclosures
                    if name is None or name in d.audience
                ]
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
            description="Instructions used only when character perspectives are enabled.",
        )
        perception_examples = PropertyField(
            name="perception_examples",
            type="list",
            default=[],
            description="Disclosure examples used only when character perspectives are enabled.",
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
            description="Disclosure confirmation used only when character perspectives are enabled.",
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


@register("knowledge/KnowledgeCallbacks")
class KnowledgeCallbacks(ListCollector):
    """Collect director knowledge callbacks, omitting revocation in perception scenes.

    Legacy scenes retain all callbacks. Uses List Collector's dynamic inputs.

    Inputs:
    - list: optional base list
    - item{i}: callback to collect

    Outputs:
    - list: available knowledge callbacks
    """

    def __init__(self, title="Knowledge Callbacks", **kwargs):
        super().__init__(title=title, **kwargs)

    async def run(self, state: GraphState):
        await super().run(state)
        if character_knowledge_enabled(active_scene.get()):
            callbacks = self.get_output_socket("list").value
            self.set_output_values(
                {
                    "list": [
                        callback
                        for callback in callbacks
                        if callback.name != "revoke_knowledge"
                    ]
                }
            )
