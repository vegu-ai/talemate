import pytest

from conftest import MockScene, bootstrap_scene
from talemate.knowledge.schema import Fact, KnowledgeEdge, Topic
from talemate.knowledge.topics import topic_facts, topics_facts
from test_supported_facts import passage, store, supported_scene  # noqa: F401


def fact(id, text, ts, present, subjects=(), **kw):
    return Fact(
        id=id,
        text=text,
        ts=ts,
        present=list(present) if present is not None else None,
        subjects=list(subjects),
        **kw,
    )


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    ws = s.world_state
    ws.facts = {
        "F1": fact(
            "F1", "Edwin keeps the light.", 1, ["Edwin", "Mara"], archive_id="A1"
        ),
        "F2": fact("F2", "Mara found a sextant.", 2, ["Mara"], source="manual"),
        "F3": fact("F3", "The boat leaks.", 3, ["Mara"], known_by={"Edwin": "told"}),
        "F4": fact("F4", "Unknown presence.", 4, None, source="summary"),
    }
    ws.topics = {
        "T1": Topic(id="T1", name="lighthouse", fact_ids=["F1", "F2", "F3", "F99"]),
        "T2": Topic(id="T2", name="sea", fact_ids=["F4"]),
    }
    # a told fact is in the bucket through its edge; known_by records the kind
    ws.knowledge = [KnowledgeEdge(character="Edwin", target="F3", source="told")]
    return s


class TestTopicFacts:
    def test_known_and_unknown_rows_in_topic_order(self, scene):
        rows = topic_facts(scene, "Edwin", "T1")
        assert [(r.id, r.known, r.how) for r in rows] == [
            ("F1", True, "witnessed"),
            ("F2", False, None),
            ("F3", True, "told"),
        ]
        assert rows[0].source == "history entry" and rows[0].source_id == "A1"
        assert rows[1].source == "manual entry"

    def test_unknown_presence_counts_as_witnessed_and_summary_is_labelled(self, scene):
        (row,) = topic_facts(scene, "Edwin", "T2")
        assert row.known and row.how == "witnessed" and row.source == "history entry"

    def test_grant_and_revoke_change_how(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Edwin", target="F2"),
            KnowledgeEdge(character="Edwin", target="F1", kind="revoke"),
        ]
        rows = {r.id: r for r in topic_facts(scene, "Edwin", "T1")}
        assert rows["F2"].known and rows["F2"].how == "granted"
        assert not rows["F1"].known and rows["F1"].how is None

    def test_missing_topic_is_empty(self, scene):
        assert topic_facts(scene, "Edwin", "T9") == []

    def test_a_batch_walks_one_bucket_and_answers_every_topic(self, scene, monkeypatch):
        import talemate.knowledge.topics as topics_module

        calls = []
        original = topics_module._known

        def counting(scene_, character):
            calls.append(character)
            return original(scene_, character)

        monkeypatch.setattr(topics_module, "_known", counting)
        rows = topics_facts(scene, "Edwin", ["T1", "T2", "T9"])
        assert calls == ["Edwin"]
        assert [r.id for r in rows["T1"]] == ["F1", "F2", "F3"]
        assert [r.id for r in rows["T2"]] == ["F4"]
        assert rows["T9"] == []


@pytest.mark.asyncio
async def test_perception_rows_show_the_one_record_with_the_character_evidence(
    supported_scene,  # noqa: F811
):
    scene, _, _ = supported_scene
    _, source = passage(scene, "The ledger is under the bed.", ("Bob",), 10)
    fact = (
        await store(
            scene, source, ("Bob",), "The ledger is under the bed.", subjects=["ledger"]
        )
    )[0]
    canonical = scene.world_state.facts[fact.id]
    canonical.text = "AUTHOR CORRECTION: the ledger is in the cabinet."
    canonical.text_edited = True
    canonical.importance = 3
    canonical.archive_id = "A-author"
    scene.world_state.topics = {"T1": Topic(id="T1", name="ledger", fact_ids=[fact.id])}

    (bob_row,) = topic_facts(scene, "Bob", "T1")
    assert bob_row.known and bob_row.how == "inferred"
    assert bob_row.text == "AUTHOR CORRECTION: the ledger is in the cabinet."
    assert bob_row.importance == 3 and bob_row.subjects == ["ledger"]
    assert bob_row.ts == 10
    assert bob_row.source_id != "A-author"

    (alice_row,) = topic_facts(scene, "Alice", "T1")
    assert not alice_row.known and alice_row.how is None
    assert alice_row.text == "AUTHOR CORRECTION: the ledger is in the cabinet."
    assert alice_row.source_id == "A-author"
