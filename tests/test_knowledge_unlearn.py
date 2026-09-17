"""#662: Unlearn, a third knowledge rule kind that a later learning lifts."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem, RetrievalFilter
from talemate.knowledge.changes import edge_changes_knowledge, lifted_unlearns
from talemate.knowledge.entry import (
    character_knowledge_report,
    known_by_line,
    set_edge,
)
from talemate.knowledge.facts import (
    SpanLine,
    drop_facts_for_entries,
    fact_is_independent,
    parse_facts,
    prune_serialized_facts,
    store_facts,
)
from talemate.knowledge.message_facts import prune_missing_message_facts
from talemate.knowledge.revision_browsing import fact_current
from talemate.knowledge.revision_refresh import _remove_message_evidence
from talemate.knowledge.schema import Fact, KnowledgeEdge
from talemate.knowledge.topics import topic_facts
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage, get_message_id
from talemate.world_state.manager import WorldStateManager
import test_fact_catalog
import test_knowledge_facts
import test_knowledge_retrieval
from test_fact_single_source import frames, handler_for
from test_knowledge_retrieval import enable

catalog_scene = test_fact_catalog.catalog_scene
fake_memory = test_knowledge_facts.fake_memory
opt_ins = test_knowledge_retrieval.opt_ins


def knows(scene, name, fact_id):
    fact = scene.world_state.facts[fact_id]
    return KnowledgeIndex.from_scene(scene).in_bucket(
        name, KnowledgeItem(id=fact_id, kind="fact", present=fact.present)
    )


def pair_edges(scene, name, fact_id):
    return [
        (edge.kind, edge.source)
        for edge in scene.world_state.knowledge
        if edge.character == name and edge.target == fact_id
    ]


def unlearn(scene, name, *fact_ids):
    with (
        ActiveScene(scene),
        patch("talemate.world_state.manager.emit_knowledge_changes"),
    ):
        return WorldStateManager(scene).unlearn_facts(name, list(fact_ids))


class TestBucket:
    def test_unlearn_sits_between_never_learn_and_learn(self):
        item = KnowledgeItem(id="F1", kind="fact", present=["Edwin"])
        index = KnowledgeIndex(
            grants={("Edwin", "F1")}, revokes=set(), unlearns={("Edwin", "F1")}
        )
        assert index.rejection("Edwin", item) == "unlearn"
        index.revokes.add(("Edwin", "F1"))
        assert index.rejection("Edwin", item) == "revoke"
        assert KnowledgeIndex(set(), set(), set()).rejection("Edwin", item) is None

    def test_character_perspectives_ignore_unlearn_edges(self, catalog_scene):
        catalog_scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F1", kind="unlearn")
        )
        catalog_scene.knowledge_eligibility = "perception"
        assert KnowledgeIndex.from_scene(catalog_scene).unlearns == set()

    def test_the_change_state_orders_never_learn_unlearn_learn(self):
        grant = KnowledgeEdge(character="Edwin", target="F1")
        rule = KnowledgeEdge(character="Edwin", target="F1", kind="unlearn")
        block = KnowledgeEdge(character="Edwin", target="F1", kind="revoke")
        assert edge_changes_knowledge(rule, [grant], [grant, rule])
        assert not edge_changes_knowledge(rule, [block], [block, rule])

    def test_a_grant_from_a_later_line_lifts_the_rule_while_it_exists(
        self, catalog_scene
    ):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        (rule,) = [e for e in scene.world_state.knowledge if e.kind == "unlearn"]
        scene.history.append(NarratorMessage(message="Line 14.", id=114))
        older = KnowledgeEdge(
            character="Edwin", target="F1", source="told", message_id=105
        )
        newer = KnowledgeEdge(
            character="Edwin", target="F1", source="told", message_id=114
        )
        scene.world_state.knowledge.append(older)
        assert not knows(scene, "Edwin", "F1")
        assert lifted_unlearns(scene.world_state.knowledge) == set()
        scene.world_state.knowledge.append(newer)
        assert knows(scene, "Edwin", "F1")
        assert lifted_unlearns(scene.world_state.knowledge) == {rule.id}
        assert not edge_changes_knowledge(
            newer, [rule, older, newer], [rule, older, newer]
        )
        assert edge_changes_knowledge(rule, [rule, older], [rule, older, newer])
        scene.world_state.knowledge.remove(newer)
        assert not knows(scene, "Edwin", "F1")


class TestUnlearnFacts:
    def test_a_present_character_unlearns_and_the_fact_stays(self, catalog_scene):
        scene = catalog_scene
        with (
            ActiveScene(scene),
            patch("talemate.world_state.manager.emit_knowledge_changes") as emitted,
        ):
            changes = WorldStateManager(scene).unlearn_facts("Edwin", ["F1"])
        assert "F1" in scene.world_state.facts
        assert not knows(scene, "Edwin", "F1")
        assert knows(scene, "Mara", "F1")
        (edge,) = [e for e in scene.world_state.knowledge if e.kind == "unlearn"]
        assert (
            edge.character,
            edge.target,
            edge.source,
            edge.message_id_boundary,
            edge.ts,
        ) == ("Edwin", "F1", "manual", 113, 1000)
        assert [(c.character, c.target, c.kind) for c in changes] == [
            ("Edwin", "F1", "unlearn")
        ]
        emitted.assert_called_once()

    def test_unlearn_replaces_the_learn_rules_and_masks_the_story_grants(
        self, catalog_scene
    ):
        scene = catalog_scene
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F3", source="manual")
        )
        assert knows(scene, "Edwin", "F3")
        unlearn(scene, "Edwin", "F3")
        assert pair_edges(scene, "Edwin", "F3") == [
            ("grant", "told"),
            ("unlearn", "manual"),
        ]
        assert scene.world_state.facts["F3"].known_by == {"Edwin": "told"}
        assert not knows(scene, "Edwin", "F3")

    def test_unlearn_drops_how_a_learn_rule_taught_the_fact(self, catalog_scene):
        scene = catalog_scene
        scene.world_state.facts["F1"].known_by["Edwin"] = "granted"
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F1", source="director")
        )
        unlearn(scene, "Edwin", "F1")
        assert pair_edges(scene, "Edwin", "F1") == [("unlearn", "manual")]
        assert "Edwin" not in scene.world_state.facts["F1"].known_by

    def test_unlearning_a_lifted_fact_replaces_the_old_rule(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        scene.history.append(NarratorMessage(message="Line 14.", id=114))
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F1", source="told", message_id=114)
        )
        assert knows(scene, "Edwin", "F1")

        changes = unlearn(scene, "Edwin", "F1")

        assert pair_edges(scene, "Edwin", "F1") == [
            ("grant", "told"),
            ("unlearn", "manual"),
        ]
        (rule,) = [e for e in scene.world_state.knowledge if e.kind == "unlearn"]
        assert rule.message_id_boundary == 114
        assert [(c.character, c.kind) for c in changes] == [("Edwin", "unlearn")]
        assert not knows(scene, "Edwin", "F1")

    def test_a_fact_the_character_does_not_know_is_left_alone(self, catalog_scene):
        scene = catalog_scene
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F1", kind="revoke")
        )
        before = list(scene.world_state.knowledge)
        assert unlearn(scene, "Edwin", "F1", "F2", "F404") == []
        assert scene.world_state.knowledge == before

    def test_refused_in_character_perspectives(self, catalog_scene):
        catalog_scene.knowledge_eligibility = "perception"
        with pytest.raises(ValueError, match="Unlearn is unavailable"):
            WorldStateManager(catalog_scene).unlearn_facts("Edwin", ["F1"])


class TestExplicitRules:
    async def test_learn_lifts_the_unlearn_rule(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        with (
            ActiveScene(scene),
            patch("talemate.world_state.manager.emit_knowledge_changes"),
        ):
            WorldStateManager(scene).grant_facts("Edwin", ["F1"])
        assert pair_edges(scene, "Edwin", "F1") == [("grant", "manual")]
        assert knows(scene, "Edwin", "F1")

    async def test_never_learn_replaces_the_unlearn_rule(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        manager = WorldStateManager(scene)
        with ActiveScene(scene):
            block = await manager.set_knowledge_edge(
                KnowledgeEdge(character="Edwin", target="F1", kind="revoke")
            )
        assert pair_edges(scene, "Edwin", "F1") == [("revoke", "manual")]
        await manager.remove_knowledge_edge(block.id)
        assert knows(scene, "Edwin", "F1")

    async def test_removing_the_unlearn_rule_returns_the_fact(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        (rule,) = [e for e in scene.world_state.knowledge if e.kind == "unlearn"]
        await WorldStateManager(scene).remove_knowledge_edge(rule.id)
        assert knows(scene, "Edwin", "F1")

    async def test_removing_the_unlearn_rule_returns_a_fact_told_in_the_story(
        self, catalog_scene
    ):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F3")
        (rule,) = [e for e in scene.world_state.knowledge if e.kind == "unlearn"]
        await WorldStateManager(scene).remove_knowledge_edge(rule.id)
        assert knows(scene, "Edwin", "F3")
        assert pair_edges(scene, "Edwin", "F3") == [("grant", "told")]

    async def test_learn_for_character_replaces_a_lifted_unlearn(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        scene.history.append(NarratorMessage(message="Line 14.", id=114))
        told = KnowledgeEdge(
            character="Edwin", target="F1", source="told", message_id=114
        )
        scene.world_state.knowledge.append(told)
        assert knows(scene, "Edwin", "F1")
        with (
            ActiveScene(scene),
            patch("talemate.world_state.manager.emit_knowledge_changes"),
        ):
            WorldStateManager(scene).grant_facts("Edwin", ["F1"])
        assert pair_edges(scene, "Edwin", "F1") == [
            ("grant", "told"),
            ("grant", "manual"),
        ]
        scene.world_state.knowledge.remove(told)
        assert knows(scene, "Edwin", "F1")

    async def test_the_rule_form_does_not_write_unlearn(self, catalog_scene):
        with pytest.raises(ValueError, match="Unlearn a fact"):
            await WorldStateManager(catalog_scene).set_knowledge_edge(
                KnowledgeEdge(character="Edwin", target="F1", kind="unlearn")
            )

    def test_a_node_or_director_grant_lifts_the_unlearn_rule(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        with ActiveScene(scene):
            set_edge(
                scene,
                KnowledgeEdge(
                    character="Edwin", target="F1", kind="grant", source="director"
                ),
            )
        assert pair_edges(scene, "Edwin", "F1") == [("grant", "director")]
        assert knows(scene, "Edwin", "F1")


class TestDialogueLearning:
    @pytest.fixture
    def unlearned(self, scene, opt_ins):
        conversation, alice = opt_ins
        enable(conversation, "ledger")
        scene.world_state.facts = {
            "F1": Fact(
                id="F1", text="Alice found the key.", ts=10, present=["Alice", "Edwin"]
            ),
        }
        scene.world_state.knowledge = [
            KnowledgeEdge(
                character="Edwin",
                target="F1",
                kind="unlearn",
                message_id_boundary=10,
            )
        ]
        return conversation, alice

    async def learn(self, scene, conversation, alice, message_id):
        # a lift counts only for a line that is in the story
        scene.history.append(
            CharacterMessage(message="Alice: I found the key.", id=message_id)
        )
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as request,
        ):
            request.return_value = ("", {"ledger": '{"Edwin": ["F1"]}'})
            return await conversation.record_learned_facts(
                alice,
                "Alice: I found the key.",
                message=CharacterMessage(
                    message="Alice: I found the key.", id=message_id
                ),
            )

    async def test_a_newer_line_lifts_the_rule(self, scene, unlearned):
        conversation, alice = unlearned
        assert await self.learn(scene, conversation, alice, 11) == {"Edwin": ["F1"]}
        assert pair_edges(scene, "Edwin", "F1") == [
            ("unlearn", "manual"),
            ("grant", "inferred"),
        ]
        assert knows(scene, "Edwin", "F1")

    async def test_removing_the_newer_line_puts_the_rule_back(self, scene, unlearned):
        conversation, alice = unlearned
        await self.learn(scene, conversation, alice, 11)
        line = CharacterMessage(message="Alice: I found the key.", id=11)

        _remove_message_evidence(scene, line, facts=False)

        assert pair_edges(scene, "Edwin", "F1") == [("unlearn", "manual")]
        assert scene.world_state.facts["F1"].known_by == {}
        assert not knows(scene, "Edwin", "F1")

    async def test_a_refresh_of_an_older_line_leaves_the_rule(self, scene, unlearned):
        conversation, alice = unlearned
        await self.learn(scene, conversation, alice, 7)
        assert pair_edges(scene, "Edwin", "F1") == [
            ("unlearn", "manual"),
            ("grant", "inferred"),
        ]
        assert not knows(scene, "Edwin", "F1")

    async def test_removing_the_older_line_drops_how_it_taught_the_fact(
        self, scene, unlearned
    ):
        conversation, alice = unlearned
        await self.learn(scene, conversation, alice, 7)
        line = CharacterMessage(message="Alice: I found the key.", id=7)

        _remove_message_evidence(scene, line, facts=False)

        assert pair_edges(scene, "Edwin", "F1") == [("unlearn", "manual")]
        assert scene.world_state.facts["F1"].known_by == {}


class TestRestatement:
    @pytest.fixture
    def unlearned(self, scene):
        scene.world_state.facts["F1"] = Fact(
            id="F1",
            text="The Sorena sank in 1973.",
            archive_id="e1",
            message_id=3,
            ts=1,
            present=["Mara", "Edwin"],
        )
        scene.world_state.fact_counter = 1
        scene.world_state.knowledge = [
            KnowledgeEdge(
                character="Edwin",
                target="F1",
                kind="unlearn",
                message_id_boundary=10,
            )
        ]
        return scene.world_state.facts["F1"]

    async def restate(self, scene, message_id, present, still_current=None):
        if scene.get_message(message_id) is None:
            scene.history.append(CharacterMessage(message="Mara: x", id=message_id))
        parsed = parse_facts(
            '[{"text": "The Sorena went down in 1973.", "restates": "F1",'
            f' "message_id": {message_id}}}]'
        )
        lines = {
            message_id: SpanLine(
                message_id=message_id,
                message_digest=f"d{message_id}",
                present=present,
                ts=50,
            )
        }
        return await store_facts(
            scene, "e5", parsed, 0.15, lines=lines, still_current=still_current
        )

    async def test_a_later_chapter_teaches_the_fact_again(
        self, scene, fake_memory, unlearned
    ):
        await self.restate(scene, 12, ["Mara", "Edwin"])
        assert pair_edges(scene, "Edwin", "F1") == [
            ("unlearn", "manual"),
            ("grant", "told"),
        ]
        assert unlearned.known_by == {"Edwin": "told"}
        assert knows(scene, "Edwin", "F1")

    async def test_removing_the_later_chapter_line_puts_the_rule_back(
        self, scene, fake_memory, unlearned
    ):
        await self.restate(scene, 12, ["Mara", "Edwin"])

        _remove_message_evidence(
            scene, CharacterMessage(message="x", id=12), facts=True
        )

        assert "F1" in scene.world_state.facts
        assert pair_edges(scene, "Edwin", "F1") == [("unlearn", "manual")]
        assert not knows(scene, "Edwin", "F1")

    @pytest.mark.parametrize("staged", [False, True])
    async def test_a_later_chapter_lifts_the_rule_beside_an_earlier_grant(
        self, scene, fake_memory, unlearned, staged
    ):
        unlearned.present = ["Mara"]
        still_current = (lambda: True) if staged else None
        await self.restate(scene, 8, ["Mara", "Edwin"], still_current)
        assert pair_edges(scene, "Edwin", "F1") == [
            ("unlearn", "manual"),
            ("grant", "told"),
        ]
        assert not knows(scene, "Edwin", "F1")

        await self.restate(scene, 12, ["Mara", "Edwin"], still_current)
        await self.restate(scene, 12, ["Mara", "Edwin"], still_current)

        assert [
            edge.message_id
            for edge in scene.world_state.knowledge
            if edge.character == "Edwin" and edge.kind == "grant"
        ] == [8, 12]
        assert knows(scene, "Edwin", "F1")

    async def test_a_regenerated_earlier_chapter_leaves_the_rule(
        self, scene, fake_memory, unlearned
    ):
        await self.restate(scene, 8, ["Mara", "Edwin"])
        assert pair_edges(scene, "Edwin", "F1") == [("unlearn", "manual")]
        assert not knows(scene, "Edwin", "F1")

    async def test_unknown_origin_presence_teaches_only_the_unlearned_character(
        self, scene, fake_memory, unlearned
    ):
        unlearned.present = None
        await self.restate(scene, 12, ["Mara", "Edwin"])
        assert pair_edges(scene, "Edwin", "F1") == [
            ("unlearn", "manual"),
            ("grant", "told"),
        ]
        assert pair_edges(scene, "Mara", "F1") == []

    async def test_a_static_entry_leaves_the_rule(self, scene, fake_memory, unlearned):
        parsed = parse_facts('[{"text": "The Sorena sank.", "restates": "F1"}]')
        await store_facts(
            scene, "static", parsed, 0.15, present=["Mara", "Edwin"], ts=0
        )
        assert pair_edges(scene, "Edwin", "F1") == [("unlearn", "manual")]


class TestRulesOutliveARegeneration:
    """An author rule survives a regeneration of the entry that recorded its fact."""

    @pytest.fixture
    def recorded(self, scene):
        scene.history.append(
            CharacterMessage(message="Mara: The Sorena sank in 1973.", id=12)
        )
        scene.world_state.facts["F1"] = Fact(
            id="F1",
            text="The Sorena sank in 1973.",
            archive_id="A1",
            message_id=12,
            ts=1,
            present=["Mara", "Edwin"],
        )
        scene.world_state.fact_counter = 1
        scene.world_state.knowledge = [
            KnowledgeEdge(
                character="Edwin",
                target="F1",
                kind="unlearn",
                message_id_boundary=12,
            ),
            KnowledgeEdge(character="Mara", target="F1", kind="revoke"),
            KnowledgeEdge(character="Carol", target="F1", source="told", message_id=12),
        ]
        return scene

    async def regenerate(self, scene, text, **item):
        await drop_facts_for_entries(scene, {"A1"})
        parsed = parse_facts(json.dumps([{"text": text, "message_id": 12, **item}]))
        lines = {
            12: SpanLine(
                message_id=12, message_digest="d12", present=["Mara", "Edwin"], ts=1
            )
        }
        return await store_facts(scene, "A1", parsed, 0.15, lines=lines)

    def rules(self, scene):
        return sorted(
            (edge.character, edge.target, edge.kind, edge.anchor is not None)
            for edge in scene.world_state.knowledge
        )

    async def test_the_same_statement_takes_the_rules_over(
        self, scene, fake_memory, recorded
    ):
        (fact,) = await self.regenerate(scene, "The Sorena sank in 1973.")
        assert fact.id == "F2"
        assert self.rules(scene) == [
            ("Edwin", "F2", "unlearn", False),
            ("Mara", "F2", "revoke", False),
        ]
        assert not knows(scene, "Edwin", "F2")
        assert not knows(scene, "Mara", "F2")

    async def test_other_wording_within_the_tolerance_takes_them_over(
        self, scene, fake_memory, recorded
    ):
        fake_memory.distance = 0.1
        await self.regenerate(scene, "The Sorena went down in 1973.")
        assert self.rules(scene) == [
            ("Edwin", "F2", "unlearn", False),
            ("Mara", "F2", "revoke", False),
        ]

    async def test_a_rule_waits_while_its_statement_is_missing(
        self, scene, fake_memory, recorded
    ):
        await self.regenerate(scene, "Mara cleaned the lens.")
        assert self.rules(scene) == [
            ("Edwin", "F1", "unlearn", True),
            ("Mara", "F1", "revoke", True),
        ]
        assert knows(scene, "Edwin", "F2")
        with ActiveScene(scene):
            knowledge = await WorldStateManager(scene).get_character_knowledge("Edwin")
        assert knowledge.edges == []

        await self.regenerate(scene, "The Sorena sank in 1973.")

        assert self.rules(scene) == [
            ("Edwin", "F3", "unlearn", False),
            ("Mara", "F3", "revoke", False),
        ]

    async def test_a_waiting_rule_goes_with_its_line(
        self, scene, fake_memory, recorded
    ):
        await self.regenerate(scene, "Mara cleaned the lens.")
        scene.history = []
        await store_facts(scene, "A9", parse_facts('[{"text": "x"}]'), 0.15, ts=0)
        assert self.rules(scene) == []

    async def test_a_fact_with_its_own_rule_keeps_it(
        self, scene, fake_memory, recorded
    ):
        scene.world_state.facts["F9"] = Fact(
            id="F9", text="The Sorena sank in 1973.", source="manual"
        )
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F9", source="manual")
        )
        await self.regenerate(scene, "The Sorena sank in 1973.", restates="F9")
        assert self.rules(scene) == [
            ("Edwin", "F9", "grant", False),
            ("Mara", "F9", "revoke", False),
        ]

    async def test_a_never_learn_beside_a_learn_moves_with_it(
        self, scene, fake_memory, recorded
    ):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F1", source="manual"),
            KnowledgeEdge(character="Edwin", target="F1", kind="revoke"),
        ]
        await self.regenerate(scene, "The Sorena sank in 1973.")
        assert self.rules(scene) == [
            ("Edwin", "F2", "grant", False),
            ("Edwin", "F2", "revoke", False),
        ]
        assert not knows(scene, "Edwin", "F2")

    async def test_a_newer_learn_replaces_an_older_unlearn_on_the_fact(
        self, scene, fake_memory, recorded
    ):
        scene.world_state.facts["F9"] = Fact(
            id="F9", text="The Sorena sank in 1973.", source="manual"
        )
        scene.world_state.knowledge = [
            KnowledgeEdge(
                character="Edwin",
                target="F9",
                kind="unlearn",
                message_id_boundary=12,
            ),
            KnowledgeEdge(character="Edwin", target="F1", source="manual"),
        ]
        await self.regenerate(scene, "The Sorena sank in 1973.", restates="F9")
        assert self.rules(scene) == [("Edwin", "F9", "grant", False)]

    async def test_a_learning_from_dialogue_moves_and_keeps_its_lift(
        self, scene, fake_memory, recorded
    ):
        scene.history.append(CharacterMessage(message="Mara: The Sorena sank.", id=30))
        scene.world_state.knowledge.append(
            KnowledgeEdge(
                character="Edwin", target="F1", source="inferred", message_id=30
            )
        )
        scene.world_state.facts["F1"].known_by["Edwin"] = "inferred"
        assert knows(scene, "Edwin", "F1")

        await self.regenerate(scene, "The Sorena sank in 1973.")

        assert ("Edwin", "F2", "grant", False) in self.rules(scene)
        assert scene.world_state.facts["F2"].known_by == {"Edwin": "inferred"}
        assert knows(scene, "Edwin", "F2")

    async def test_a_later_line_of_the_same_span_lifts_the_moved_unlearn(
        self, scene, fake_memory, recorded
    ):
        fake_memory.distance = 0.0
        scene.history.append(CharacterMessage(message="Mara: The Sorena sank.", id=40))
        await drop_facts_for_entries(scene, {"A1"})
        parsed = parse_facts(
            json.dumps(
                [
                    {"text": "The Sorena sank in 1973.", "message_id": 12},
                    {"text": "The Sorena sank in 1973.", "message_id": 40},
                ]
            )
        )
        both = ["Mara", "Edwin"]
        lines = {
            12: SpanLine(message_id=12, message_digest="d12", present=both, ts=1),
            40: SpanLine(message_id=40, message_digest="d40", present=both, ts=5),
        }
        await store_facts(scene, "A1", parsed, 0.15, lines=lines)

        (fact,) = scene.world_state.facts.values()
        assert pair_edges(scene, "Edwin", fact.id) == [
            ("unlearn", "manual"),
            ("grant", "told"),
        ]
        assert knows(scene, "Edwin", fact.id)

    async def test_a_later_origin_line_lifts_the_moved_unlearn(
        self, scene, fake_memory, recorded
    ):
        (rule,) = [e for e in scene.world_state.knowledge if e.kind == "unlearn"]
        rule.message_id_boundary = 30
        scene.history.append(CharacterMessage(message="Mara: The Sorena sank.", id=40))
        await drop_facts_for_entries(scene, {"A1"})
        parsed = parse_facts(
            json.dumps([{"text": "The Sorena sank in 1973.", "message_id": 40}])
        )
        both = ["Mara", "Edwin"]
        lines = {
            12: SpanLine(message_id=12, message_digest="d12", present=both, ts=1),
            40: SpanLine(message_id=40, message_digest="d40", present=both, ts=5),
        }
        (fact,) = await store_facts(scene, "A1", parsed, 0.15, lines=lines)

        assert fact.message_id == 40
        assert pair_edges(scene, "Edwin", fact.id) == [
            ("unlearn", "manual"),
            ("grant", "told"),
        ]
        assert knows(scene, "Edwin", fact.id)
        # Mara has no Unlearn: her presence covers her, and she gets no grant
        assert pair_edges(scene, "Mara", fact.id) == [("revoke", "manual")]

    async def test_an_older_never_learn_gives_way_to_a_newer_learn(
        self, scene, fake_memory, recorded
    ):
        scene.world_state.facts["F9"] = Fact(
            id="F9", text="The Sorena sank in 1973.", source="manual"
        )
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F1", kind="revoke"),
            KnowledgeEdge(character="Edwin", target="F9", source="manual"),
        ]
        await self.regenerate(scene, "The Sorena sank in 1973.", restates="F9")
        assert self.rules(scene) == [("Edwin", "F9", "grant", False)]
        assert knows(scene, "Edwin", "F9")

    async def test_a_never_learn_replaces_an_unlearn_that_meets_it(
        self, scene, fake_memory, recorded
    ):
        scene.world_state.facts["F9"] = Fact(
            id="F9", text="The Sorena sank in 1973.", source="manual"
        )
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F9", kind="revoke"),
            KnowledgeEdge(
                character="Edwin",
                target="F1",
                kind="unlearn",
                message_id_boundary=12,
            ),
        ]
        await self.regenerate(scene, "The Sorena sank in 1973.", restates="F9")
        assert self.rules(scene) == [("Edwin", "F9", "revoke", False)]

    async def test_a_waiting_rule_goes_when_its_line_is_deleted(
        self, scene, fake_memory, recorded
    ):
        await self.regenerate(scene, "Mara cleaned the lens.")
        scene.history = [message for message in scene.history if message.id != 12]
        prune_missing_message_facts(scene)
        assert [edge for edge in scene.world_state.knowledge if edge.anchor] == []

    async def test_a_reset_drops_the_waiting_rules(self, scene, fake_memory, recorded):
        await self.regenerate(scene, "Mara cleaned the lens.")
        scene.history = []
        await drop_facts_for_entries(scene, set(), keep_rules=False)
        assert [edge for edge in scene.world_state.knowledge if edge.anchor] == []

    async def test_an_export_without_history_keeps_no_waiting_rule(
        self, scene, fake_memory, recorded
    ):
        await self.regenerate(scene, "Mara cleaned the lens.")
        exported = scene.world_state.model_dump(mode="json")
        prune_serialized_facts(exported, set(), reset_history=True)
        assert [edge for edge in exported["knowledge"] if edge.get("anchor")] == []

    async def test_a_refresh_of_the_line_keeps_the_rule_waiting(
        self, scene, fake_memory, recorded
    ):
        # a Never Learn by hand keeps its fact out of the line anyway
        scene.world_state.knowledge = [
            edge for edge in scene.world_state.knowledge if edge.kind != "revoke"
        ]
        _remove_message_evidence(scene, scene.history[-1], facts=True)
        assert "F1" not in scene.world_state.facts
        assert self.rules(scene) == [("Edwin", "F1", "unlearn", True)]


class TestRetrievalAndIndependence:
    def test_the_similarity_gate_does_not_rescue_an_unlearned_fact(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")

        def doc(fact_id, present):
            meta = {
                "typ": "fact",
                "presence_known": True,
                "present": '["' + '", "'.join(present) + '"]',
            }
            return MemoryDocument("x", meta, fact_id, "x")

        gate = RetrievalFilter(KnowledgeIndex.from_scene(scene), scene, "Edwin")
        assert gate.rejection(doc("F1", ["Edwin", "Mara"])) == "unlearn"
        assert not gate.gateable(doc("F1", ["Edwin", "Mara"]))
        assert gate.gateable(doc("F4", ["Mara"]))

    def test_an_unlearn_rule_does_not_keep_a_stale_fact_current(self, catalog_scene):
        scene = catalog_scene
        fact = scene.world_state.facts["F10"]
        fact.message_id = 999
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Mara", target="F10", kind="unlearn")
        )
        assert not fact_current(scene, fact)
        assert not fact_is_independent(scene.world_state, fact)
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F10", kind="grant")
        )
        assert fact_current(scene, fact)
        assert fact_is_independent(scene.world_state, fact)


class TestReasonsAndReports:
    def test_topic_rows_say_why_a_fact_is_unknown(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F3", kind="revoke")
        )
        rows = {
            row.id: row
            for topic in ("T1", "T2")
            for row in topic_facts(scene, "Edwin", topic)
        }
        assert (rows["F1"].known, rows["F1"].reason) == (False, "Unlearned")
        assert (rows["F3"].known, rows["F3"].reason) == (False, "Never Learn rule")
        assert (rows["F4"].known, rows["F4"].reason) == (False, "Not present")
        unlearn(scene, "Mara", "F4")
        assert [row.reason for row in topic_facts(scene, "Mara", "T1")] == [
            None,
            "Unlearned",
        ]

    def test_the_known_by_line_and_the_director_report_list_the_rule(
        self, catalog_scene
    ):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        assert "unlearned: Edwin (manual)" in known_by_line(scene, "F1")
        report = character_knowledge_report(scene, "Edwin").splitlines()
        heading = report.index("Unlearned (known again after any later learning):")
        assert "Edwin keeps the light." in report[heading + 1]
        assert report[heading + 1].endswith(": manual")

    async def test_a_lifted_rule_is_named_in_the_rule_list_only(self, catalog_scene):
        scene = catalog_scene
        unlearn(scene, "Edwin", "F1")
        (rule,) = [e for e in scene.world_state.knowledge if e.kind == "unlearn"]
        scene.history.append(NarratorMessage(message="Line 14.", id=114))
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Edwin", target="F1", source="told", message_id=114)
        )

        knowledge = await WorldStateManager(scene).get_character_knowledge("Edwin")

        assert rule.id in [edge.id for edge in knowledge.edges]
        assert knowledge.lifted_edge_ids == [rule.id]
        assert "unlearned:" not in known_by_line(scene, "F1")
        assert "Unlearned (known again after any later learning):" not in (
            character_knowledge_report(scene, "Edwin")
        )


class TestHandler:
    async def test_unlearn_facts_answers_with_the_character_knowledge(
        self, catalog_scene
    ):
        handler = handler_for(catalog_scene)
        with ActiveScene(catalog_scene):
            await handler.handle_unlearn_facts({"name": "Edwin", "fact_ids": ["F1"]})
        assert frames(handler, "character_knowledge")[-1]["data"]["name"] == "Edwin"
        assert not knows(catalog_scene, "Edwin", "F1")

    async def test_unlearn_facts_is_refused_in_character_perspectives(
        self, catalog_scene
    ):
        handler = handler_for(catalog_scene)
        catalog_scene.knowledge_eligibility = "perception"
        with ActiveScene(catalog_scene):
            await handler.handle_unlearn_facts({"name": "Edwin", "fact_ids": ["F1"]})
        failed = [f for f in handler.sent if f.get("failed_action") == "unlearn_facts"]
        assert len(failed) == 1


async def test_loading_moves_the_message_counter_past_an_unlearn_boundary(
    persistence_scene_factory,
):
    from talemate.load import load_scene_from_data

    scene = persistence_scene_factory()
    scene.character_data = {"Alice": Character(name="Alice")}
    scene.world_state.facts = {
        "F1": Fact(id="F1", text="A fact.", present=None, source="manual")
    }
    scene.world_state.knowledge = [
        KnowledgeEdge(
            character="Alice",
            target="F1",
            kind="unlearn",
            message_id_boundary=4000,
        )
    ]
    saved = deepcopy(scene.serialize)
    restored = persistence_scene_factory()
    await load_scene_from_data(restored, saved)
    assert restored.world_state.knowledge[0].message_id_boundary == 4000
    assert get_message_id() > 4000


async def test_loading_moves_the_message_counter_past_a_waiting_rule_line(
    persistence_scene_factory,
):
    from talemate.load import load_scene_from_data
    from talemate.knowledge.schema import FactAnchor

    scene = persistence_scene_factory()
    scene.character_data = {"Alice": Character(name="Alice")}
    scene.world_state.knowledge = [
        KnowledgeEdge(
            character="Alice",
            target="F7",
            kind="revoke",
            anchor=FactAnchor(text="A fact.", message_id=7000),
        )
    ]
    saved = deepcopy(scene.serialize)
    restored = persistence_scene_factory()
    await load_scene_from_data(restored, saved)
    assert get_message_id() > 7000
