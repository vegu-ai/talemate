from typing import ClassVar

import structlog

from talemate.context import active_scene
from talemate.knowledge.graph import (
    current_state,
    facts_about,
    relationship_timeline,
)
from talemate.knowledge.schema import KnowledgeEdge

from .core import GraphState, Node, PropertyField, TYPE_CHOICES
from .registry import register

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
    The newest fact about an entity that no later fact supersedes.

    Inputs:
    - entity: name of the entity

    Outputs:
    - fact: the fact dict, or None
    - text: the fact text, or an empty string
    """

    def __init__(self, title="Current State", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("entity", socket_type="str")
        self.add_output("fact", socket_type="knowledge/fact")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        fact = current_state(scene, self.require_input("entity"))
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

    Outputs:
    - facts: list of fact dicts
    - text: one line per fact
    """

    def __init__(self, title="Relationship Timeline", **kwargs):
        super().__init__(title=title, **kwargs)

    def setup(self):
        self.add_input("a", socket_type="str")
        self.add_input("b", socket_type="str")
        self.add_output("facts", socket_type="list")
        self.add_output("text", socket_type="str")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        facts = relationship_timeline(
            scene, self.require_input("a"), self.require_input("b")
        )
        self.set_output_values(
            {
                "facts": _fact_dicts(facts),
                "text": "\n".join(f"[{f.id}] {f.text}" for f in facts),
            }
        )


class _EdgeNode(Node):
    kind: ClassVar[str] = "grant"

    class Fields:
        note = PropertyField(
            name="note",
            description="Optional note stored on the edge",
            type="str",
            default="",
        )

    def setup(self):
        self.add_input("state")
        self.add_input("character", socket_type="str")
        self.add_input("target", socket_type="str")
        self.set_property("note", "")
        self.add_output("state")
        self.add_output("edge", socket_type="dict")

    async def run(self, state: GraphState):
        scene = active_scene.get()
        character = self.require_input("character")
        target = self.require_input("target")
        note = self.get_property("note") or None
        edge = KnowledgeEdge(
            character=character,
            target=target,
            kind=self.kind,
            source="granted",
            ts=scene.ts,
            note=note,
        )
        scene.world_state.knowledge.append(edge)
        self.set_output_values(
            {"state": self.normalized_input_value("state"), "edge": edge.model_dump()}
        )


@register("knowledge/GrantKnowledge")
class GrantKnowledge(_EdgeNode):
    """
    Grant a character knowledge of an entry (a fact id, a sheet entry id,
    a world entry id or a summarized history entry id).

    Inputs:
    - state: graph state (passthrough)
    - character: character name
    - target: entry id

    Outputs:
    - state: graph state
    - edge: the stored edge
    """

    kind: ClassVar[str] = "grant"

    def __init__(self, title="Grant Knowledge", **kwargs):
        super().__init__(title=title, **kwargs)


@register("knowledge/RevokeKnowledge")
class RevokeKnowledge(_EdgeNode):
    """
    Revoke a character's knowledge of an entry.

    Inputs:
    - state: graph state (passthrough)
    - character: character name
    - target: entry id

    Outputs:
    - state: graph state
    - edge: the stored edge
    """

    kind: ClassVar[str] = "revoke"

    def __init__(self, title="Revoke Knowledge", **kwargs):
        super().__init__(title=title, **kwargs)
