"""
Facts follow their message: removal on delete, unbinding for independent
facts, the load-time drop of records from before message binding, and the
timeline recompute after a time-passage edit.
"""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from talemate.instance import get_agent
from talemate.knowledge.facts import prune_serialized_facts
from talemate.knowledge.message_facts import (
    invalidate_message_facts,
    prune_legacy_facts,
    prune_missing_message_facts,
    rebind_message_facts,
    remove_message_facts,
)
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.revision_browsing import current_facts
from talemate.knowledge.schema import Fact, FactRestatement, KnowledgeEdge
from talemate.knowledge.timeline import message_times, refresh_fact_times
from talemate.scene_message import CharacterMessage, TimePassageMessage


def bound(scene, identity, text, message, **kw):
    fact = Fact(
        id=identity,
        text=text,
        message_id=message.id,
        message_digest=content_digest(message.perception_text),
        present=list(message.present or []),
        archive_id=kw.pop("archive_id", "e1"),
        **kw,
    )
    scene.world_state.facts[identity] = fact
    return fact


@pytest.fixture
def history(scene):
    both = ["Mara", "Edwin"]
    scene.history = [
        CharacterMessage(message="Mara: one", present=both),
        CharacterMessage(message="Edwin: two", present=both),
        TimePassageMessage(ts=3600, message="An hour passes", present=both),
        CharacterMessage(message="Mara: three", present=["Mara"]),
    ]
    scene.ts = 3600
    return scene.history


class TestRemoval:
    def test_deleting_the_origin_removes_the_fact_and_its_edges(self, scene, history):
        bound(scene, "F1", "one", history[0])
        bound(scene, "F2", "two", history[1])
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Carol", target="F1", source="told")
        ]
        assert remove_message_facts(scene.world_state, history[0].id) == {"F1"}
        assert list(scene.world_state.facts) == ["F2"]
        assert scene.world_state.knowledge == []

    def test_a_restatement_promotes_to_origin(self, scene, history):
        fact = bound(
            scene,
            "F1",
            "one",
            history[0],
            restatements=1,
            restated_by=(
                FactRestatement(
                    message_id=history[3].id,
                    message_digest=content_digest(history[3].perception_text),
                    archive_id="e2",
                ),
            ),
        )
        assert remove_message_facts(scene.world_state, history[0].id) == set()
        assert (fact.message_id, fact.archive_id, fact.restatements) == (
            history[3].id,
            "e2",
            0,
        )
        assert fact.restated_by == ()

    def test_an_edited_fact_is_unbound_instead(self, scene, history):
        fact = bound(scene, "F1", "edited", history[0], text_edited=True)
        assert remove_message_facts(scene.world_state, history[0].id) == set()
        assert fact.message_id is None and fact.source == "manual"

    def test_the_earliest_restatement_becomes_the_origin(self, scene, history):
        first, second, _, fourth = history
        fact = bound(scene, "F1", "one", first, ts=0, restatements=2)
        fact.restated_by = (
            FactRestatement(
                message_id=fourth.id,
                message_digest=content_digest(fourth.perception_text),
                archive_id="e2",
                present=["Mara"],
                ts=3600,
            ),
            FactRestatement(
                message_id=second.id,
                message_digest=content_digest(second.perception_text),
                archive_id="e1",
                present=["Mara", "Edwin"],
                ts=0,
            ),
        )
        assert remove_message_facts(scene.world_state, first.id) == set()
        # the origin is the earliest bound message, with its audience and time
        assert (fact.message_id, fact.archive_id, fact.present, fact.ts) == (
            second.id,
            "e1",
            ["Mara", "Edwin"],
            0,
        )
        assert [item.message_id for item in fact.restated_by] == [fourth.id]
        assert remove_message_facts(scene.world_state, second.id) == set()
        assert (fact.message_id, fact.archive_id, fact.present, fact.ts) == (
            fourth.id,
            "e2",
            ["Mara"],
            3600,
        )
        assert fact.restated_by == () and fact.restatements == 0

    def test_a_hand_granted_fact_outlives_its_message(self, scene, history):
        first, second, _, _ = history
        fact = bound(scene, "F1", "one", first)
        bound(scene, "F2", "two", second)
        grant = KnowledgeEdge(character="Edwin", target="F1", source="manual")
        scene.world_state.knowledge = [
            grant,
            KnowledgeEdge(character="Edwin", target="F2", source="told"),
        ]
        scene.history.remove(first)
        scene.history.remove(second)
        # the same rule on both paths: the delete keeps it, and so does the
        # missing-source prune
        assert prune_missing_message_facts(scene) == {"F2"}
        assert list(scene.world_state.facts) == ["F1"]
        assert scene.world_state.knowledge == [grant]
        assert (
            fact.message_id,
            fact.message_digest,
            fact.archive_id,
            fact.source,
        ) == (None, None, None, "manual")
        # the unbound fact is a shape the load-time prune keeps
        data = {
            "facts": {"F1": fact.model_dump(mode="json")},
            "knowledge": [grant.model_dump(mode="json")],
        }
        assert prune_legacy_facts(data, [{"id": "e1", "end": 3}]) == set()
        assert list(data["facts"]) == ["F1"]
        reloaded = Fact.model_validate(data["facts"]["F1"])
        assert reloaded.source == "manual" and reloaded.message_id is None

    def test_rebind_follows_an_edit_that_nothing_re_extracts(self, scene, history):
        first, second, _, _ = history
        fact = bound(scene, "F1", "one", first)
        other = bound(scene, "F2", "two", second, restatements=1)
        other.restated_by = (
            FactRestatement(
                message_id=first.id, message_digest=fact.message_digest, archive_id="e1"
            ),
        )
        first.message = "Mara: one, edited"
        digest = content_digest(first.perception_text)
        assert rebind_message_facts(scene.world_state, first.id, digest) == {
            "F1",
            "F2",
        }
        assert fact.message_digest == digest
        assert other.restated_by[0].message_digest == digest
        assert rebind_message_facts(scene.world_state, first.id, digest) == set()
        assert prune_missing_message_facts(scene) == set()
        assert fact in current_facts(scene)

    def test_invalidate_queues_the_promoted_fact(self, scene, history, monkeypatch):
        first, second, _, _ = history
        fact = bound(scene, "F1", "one", first, restatements=1)
        fact.restated_by = (
            FactRestatement(
                message_id=second.id,
                message_digest=content_digest(second.perception_text),
                archive_id="e1",
                present=["Mara", "Edwin"],
                ts=0,
            ),
        )
        queue = Mock()
        monkeypatch.setattr(get_agent("summarizer"), "queue_fact_memory", queue)
        monkeypatch.setattr(scene, "emit_status", Mock())
        scene.history.remove(first)
        assert invalidate_message_facts(scene) == set()
        # the promoted fact's document follows its new origin
        queue.assert_called_once_with(scene, {"F1"})
        assert fact.message_id == second.id

    def test_deleting_the_newest_restating_line_lowers_last_seen(self, scene, history):
        first, _, _, fourth = history
        fact = bound(scene, "F1", "one", first, ts=0, last_seen_ts=3600, restatements=1)
        fact.restated_by = (
            FactRestatement(
                message_id=fourth.id,
                message_digest=content_digest(fourth.perception_text),
                archive_id="e2",
                present=["Mara"],
                ts=3600,
            ),
        )
        assert remove_message_facts(scene.world_state, fourth.id) == set()
        # last seen is the latest remaining source, not a deleted line
        assert (fact.restatements, fact.restated_by, fact.last_seen_ts) == (0, (), 0)

    def test_a_static_entry_restatement_takes_the_origin_first(self, scene, history):
        first, _, _, fourth = history
        fact = bound(scene, "F1", "one", first, ts=0, restatements=2)
        fact.restated_by = (
            FactRestatement(
                message_id=fourth.id,
                message_digest=content_digest(fourth.perception_text),
                archive_id="e2",
                present=["Mara"],
                ts=3600,
            ),
            FactRestatement(archive_id="backstory", present=["Edwin"], ts=0),
        )
        assert remove_message_facts(scene.world_state, first.id) == set()
        # a static entry comes before every message
        assert (
            fact.message_id,
            fact.message_digest,
            fact.archive_id,
            fact.present,
            fact.ts,
            fact.last_seen_ts,
        ) == (None, None, "backstory", ["Edwin"], 0, 3600)
        assert [item.message_id for item in fact.restated_by] == [fourth.id]
        data = {"facts": {"F1": fact.model_dump(mode="json")}}
        assert prune_legacy_facts(data, [{"id": "backstory"}]) == set()

    def test_a_reset_drops_hand_granted_facts(self, scene, history):
        first, _, _, _ = history
        bound(scene, "F1", "one", first)
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F1", source="manual")
        ]
        scene.history = []
        # the story the fact came from is gone: the grant keeps nothing
        assert prune_missing_message_facts(scene, edges=False) == {"F1"}
        assert scene.world_state.facts == {} and scene.world_state.knowledge == []

    def test_a_restating_message_only_drops_its_restatement(self, scene, history):
        fact = bound(
            scene,
            "F1",
            "one",
            history[0],
            restatements=2,
            restated_by=(
                FactRestatement(message_id=history[1].id, message_digest="x"),
                FactRestatement(message_id=history[3].id, message_digest="y"),
            ),
        )
        assert remove_message_facts(scene.world_state, history[1].id) == set()
        assert fact.restatements == 1
        assert [item.message_id for item in fact.restated_by] == [history[3].id]


class TestMissingSources:
    def test_missing_and_changed_messages_drop_their_facts(self, scene, history):
        first, second, _, fourth = history
        bound(scene, "F1", "one", first)
        bound(scene, "F2", "two", second)
        keeper = bound(scene, "F3", "three", fourth)
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F3", message_id=999)
        ]
        # an unbound write commits at once: the change is final, not pending
        second.message = "Edwin: something else"
        assert second.revision_matches_baseline
        scene.history.remove(first)
        assert prune_missing_message_facts(scene) == {"F1", "F2"}
        assert list(scene.world_state.facts) == ["F3"]
        assert keeper.message_id == fourth.id
        assert scene.world_state.knowledge[0].message_id is None

    def test_a_pending_revision_keeps_the_fact(self, scene, history, monkeypatch):
        from talemate.knowledge.perspectives import bind_message_source

        fact = bound(scene, "F1", "one", history[0])
        monkeypatch.setattr(scene, "emit_status", Mock())
        bind_message_source(scene, history[0])
        history[0].message = "Mara: revised"
        assert not history[0].revision_matches_baseline
        assert prune_missing_message_facts(scene) == set()
        assert fact.message_id == history[0].id
        # stale until the refresh re-extracts it
        assert fact not in current_facts(scene)

    def test_scene_delete_message_removes_the_fact(self, scene, history, monkeypatch):
        bound(scene, "F1", "one", history[0])
        monkeypatch.setattr(scene, "emit_status", Mock())
        monkeypatch.setattr("talemate.tale_mate.emit", Mock())
        from talemate.instance import get_agent

        monkeypatch.setattr(get_agent("summarizer"), "queue_fact_memory", Mock())
        scene.delete_message(history[0].id)
        assert scene.world_state.facts == {}


class TestLegacyRecords:
    def _world_state(self):
        return {
            "facts": {
                "F1": {
                    "id": "F1",
                    "text": "dialogue",
                    "source": "dialogue",
                    "message_id": 3,
                },
                "F2": {
                    "id": "F2",
                    "text": "summary without a line",
                    "archive_id": "e1",
                    "dialogue_sources": [],
                    "archive_sources": [{"archive_id": "e1", "count": 1}],
                },
                "F3": {
                    "id": "F3",
                    "text": "bound",
                    "archive_id": "e1",
                    "message_id": 4,
                    "message_digest": "d",
                    "supersedes": "F2",
                },
                "F4": {"id": "F4", "text": "static", "archive_id": "s0"},
                "F5": {"id": "F5", "text": "manual", "source": "manual"},
                "F6": {"id": "F6", "text": "offscreen", "source": "offscreen"},
                "F7": {
                    "id": "F7",
                    "text": "perception from a passage",
                    "source": "perspective",
                    "contributions": [
                        {
                            "source": {
                                "kind": "message",
                                "id": 4,
                                "revision": 1,
                                "view_id": "v",
                                "view_revision": 1,
                            },
                            "acquired": {"order": 1, "ts": 0},
                            "audience": ["Mara"],
                            "text": "perception from a passage",
                        }
                    ],
                },
                "F8": {
                    "id": "F8",
                    "text": "disclosed",
                    "source": "disclosure",
                    "contributions": [
                        {
                            "source": {"kind": "disclosure", "id": "d1", "revision": 1},
                            "acquired": {"order": 1, "ts": 0},
                            "audience": ["Mara"],
                            "text": "disclosed",
                        }
                    ],
                },
            },
            "knowledge": [
                {"id": "k1", "character": "Mara", "target": "F1"},
                {"id": "k2", "character": "Mara", "target": "F3"},
            ],
            "topics": {"T1": {"id": "T1", "name": "t", "fact_ids": ["F1", "F2", "F3"]}},
        }

    def test_records_without_a_message_are_dropped(self):
        world_state = self._world_state()
        archived = [
            {"id": "s0", "text": "static", "ts": 0},
            {"id": "e1", "start": 0, "end": 1},
        ]
        assert prune_legacy_facts(world_state, archived) == {"F1", "F2", "F7"}
        assert set(world_state["facts"]) == {"F3", "F4", "F5", "F6", "F8"}
        assert world_state["facts"]["F3"]["supersedes"] is None
        assert "archive_sources" not in world_state["facts"]["F3"]
        assert [edge["id"] for edge in world_state["knowledge"]] == ["k2"]
        assert world_state["topics"]["T1"]["fact_ids"] == ["F3"]
        # the surviving records validate under the current model
        for values in world_state["facts"].values():
            Fact.model_validate(values)

    def test_nothing_to_drop_leaves_the_data_alone(self):
        world_state = {
            "facts": {"F5": {"id": "F5", "text": "manual", "source": "manual"}}
        }
        before = deepcopy(world_state)
        assert prune_legacy_facts(world_state, []) == set()
        assert world_state == before


class TestExportReset:
    def test_reset_history_keeps_only_independent_facts(self):
        world_state = {
            "facts": {
                "F1": Fact(
                    id="F1", text="bound", archive_id="e1", message_id=4
                ).model_dump(),
                "F2": Fact(
                    id="F2",
                    text="edited",
                    archive_id="e1",
                    message_id=5,
                    text_edited=True,
                ).model_dump(),
                "F3": Fact(
                    id="F3", text="manual", source="manual", supersedes="F1"
                ).model_dump(),
            },
            "knowledge": [
                KnowledgeEdge(character="Mara", target="F1", source="told").model_dump()
            ],
        }
        removed = prune_serialized_facts(world_state, {"e1"}, reset_history=True)
        assert removed == {"F1"}
        assert set(world_state["facts"]) == {"F2", "F3"}
        assert world_state["facts"]["F2"]["source"] == "manual"
        assert "message_id" not in world_state["facts"]["F2"]
        assert world_state["facts"]["F3"]["supersedes"] is None
        assert world_state["knowledge"] == []


class TestTimeline:
    def test_message_times_follow_the_passages(self, scene, history):
        times = message_times(scene)
        assert [times[m.id] for m in history] == [0, 0, 3600, 3600]

    def test_times_start_at_the_scene_start(self, scene, history):
        scene.start_ts = 1400
        times = message_times(scene)
        assert [times[m.id] for m in history] == [1400, 1400, 5000, 5000]

    def test_a_static_entry_does_not_set_the_scene_start(self, scene, history):
        scene.archived_history = [{"id": "s0", "text": "Long ago.", "ts": 1400}]
        times = message_times(scene)
        assert [times[m.id] for m in history] == [0, 0, 3600, 3600]

    def test_refresh_moves_the_facts_after_an_edited_passage(self, scene, history):
        early = bound(scene, "F1", "one", history[0], ts=0, last_seen_ts=0)
        late = bound(scene, "F2", "three", history[3], ts=3600, last_seen_ts=3600)
        restated = bound(
            scene,
            "F3",
            "two",
            history[1],
            ts=0,
            last_seen_ts=3600,
            restatements=1,
            restated_by=(
                FactRestatement(message_id=history[3].id, message_digest="y"),
            ),
        )
        unbound = Fact(id="F4", text="static", archive_id="s0", ts=7)
        scene.world_state.facts["F4"] = unbound
        history[2].ts = 86400
        scene.ts = 86400
        assert refresh_fact_times(scene) == {"F2", "F3"}
        assert (early.ts, early.last_seen_ts) == (0, 0)
        assert (late.ts, late.last_seen_ts) == (86400, 86400)
        assert (restated.ts, restated.last_seen_ts) == (0, 86400)
        assert unbound.ts == 7

    def test_restatement_times_follow_an_unbound_origin(self, scene, history):
        _, second, passage, fourth = history
        manual = Fact(
            id="F1",
            text="hand written",
            source="manual",
            ts=0,
            last_seen_ts=100,
            restatements=1,
            restated_by=(
                FactRestatement(
                    message_id=fourth.id,
                    message_digest=content_digest(fourth.perception_text),
                    archive_id="e2",
                    present=["Mara"],
                    ts=100,
                ),
            ),
        )
        scene.world_state.facts["F1"] = manual
        bound_fact = bound(scene, "F2", "two", second, ts=0, restatements=1)
        bound_fact.restated_by = (
            FactRestatement(
                message_id=fourth.id,
                message_digest=content_digest(fourth.perception_text),
                archive_id="e2",
                present=["Mara"],
                ts=100,
            ),
        )
        assert refresh_fact_times(scene) == {"F1", "F2"}
        # the manual origin keeps its time; its restatement moved
        assert (manual.ts, manual.restated_by[0].ts, manual.last_seen_ts) == (
            0,
            3600,
            3600,
        )
        assert (bound_fact.restated_by[0].ts, bound_fact.last_seen_ts) == (3600, 3600)
        passage.ts = 7200
        assert refresh_fact_times(scene) == {"F1", "F2"}
        assert manual.last_seen_ts == 7200 and bound_fact.last_seen_ts == 7200

    def test_fix_time_recomputes_and_queues_memory(self, scene, history, monkeypatch):
        from talemate.instance import get_agent

        queued = Mock()
        monkeypatch.setattr(get_agent("summarizer"), "queue_fact_memory", queued)
        late = bound(scene, "F2", "three", history[3], ts=3600, last_seen_ts=3600)
        scene.archived_history = []
        history[2].ts = 7200
        scene.fix_time()
        assert scene.ts == 7200 and late.ts == 7200
        queued.assert_called_once_with(scene, {"F2"})

    def test_deleting_and_inserting_a_passage_move_the_facts(
        self, scene, history, monkeypatch
    ):
        from talemate.history import (
            delete_time_passage,
            insert_time_passage_after_message,
        )
        from talemate.instance import get_agent

        monkeypatch.setattr(get_agent("summarizer"), "queue_fact_memory", Mock())
        scene.archived_history = []
        late = bound(scene, "F2", "three", history[3], ts=3600, last_seen_ts=3600)
        delete_time_passage(scene, 2)
        assert late.ts == 0
        insert_time_passage_after_message(scene, history[1].id, 2, "days")
        assert late.ts == 2 * 86400
