"""#529: a fact is one record wherever it is shown."""

from unittest.mock import AsyncMock, patch

import pydantic
import pytest

from conftest import MockScene, bootstrap_scene
from talemate.context import ActiveScene
from talemate.history import ArchiveEntry
from talemate.instance import get_agent
from talemate.knowledge.facts import facts_for_entry, update_fact
from talemate.knowledge.graph import bucket
from talemate.knowledge.perspectives import (
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.knowledge.schema import Fact, ParsedFact, Topic
from talemate.knowledge.supported_facts import aggregate_fact, character_fact
from talemate.knowledge.topics import known_facts, topic_facts
from test_fact_evidence import passage_embeddings  # noqa: F401
from test_supported_facts import chapter, passage, store, supported_scene  # noqa: F401


def handler_for(scene):
    from talemate.server.world_state_manager.knowledge import KnowledgeMixin

    class Handler(KnowledgeMixin):
        def __init__(self, scene):
            self.scene = scene
            self.sent = []
            self.websocket_handler = type(
                "W", (), {"queue_put": lambda _self, m: self.sent.append(m)}
            )()

        @property
        def world_state_manager(self):
            from talemate.world_state.manager import WorldStateManager

            return WorldStateManager(self.scene)

        async def signal_operation_done(self, *args, **kwargs):
            pass

        async def signal_operation_failed(self, message, *, failed_action=None, **kw):
            self.sent.append(
                {
                    "type": "world_state_manager",
                    "action": "operation_done",
                    "failed_action": failed_action,
                    "error": {"message": message},
                }
            )

    return Handler(scene)


def frames(handler, action):
    return [frame for frame in handler.sent if frame["action"] == action]


async def summary_fact(scene, text, audience=("Alice",), **kwargs):
    entry = ArchiveEntry(id="base", text=text, start=0, end=0)
    scene.archived_history = [entry.model_dump(exclude_none=True)]
    set_source_perspectives(
        scene,
        "summary",
        "base",
        [{"audience": audience, "status": "ready", "text": text}],
    )
    source = select_character_view(
        scene, source_reference(scene, "summary", "base"), audience[0]
    ).source
    return (await store(scene, source, audience, text, **kwargs))[0], source


@pytest.mark.asyncio
async def test_character_view_shows_the_edited_record(supported_scene):  # noqa: F811
    scene, _, _ = supported_scene
    _, source = passage(scene, "Alice has a key.", ("Alice",))
    fact = (
        await store(scene, source, ("Alice",), "Alice has a key.", subjects=["key"])
    )[0]
    stored = scene.world_state.facts[fact.id]
    stored.text = "Alice has a brass key."
    stored.subjects = ["brass key"]
    stored.importance = 3
    stored.text_edited = True

    view = character_fact(scene, stored, "Alice")
    assert (view.text, view.subjects, view.importance) == (
        "Alice has a brass key.",
        ["brass key"],
        3,
    )
    assert view.contributions[0].text == "Alice has a key."
    assert view.contributions[0].subjects == ("key",)
    assert [item.text for item, _ in bucket(scene, "Alice")] == [
        "Alice has a brass key."
    ]
    assert aggregate_fact(stored, stored.contributions).text == stored.text


@pytest.mark.asyncio
async def test_update_fact_patches_only_the_editable_fields(supported_scene):  # noqa: F811
    scene, _, memory = supported_scene
    _, source = passage(scene, "Alice has a key.", ("Alice",))
    fact = (await store(scene, source, ("Alice",), "Alice has a key."))[0]
    before = scene.world_state.facts[fact.id]
    contributions = before.contributions

    updated = await update_fact(
        scene, fact.id, text="  Alice   has a brass key. ", importance=1
    )
    assert updated is before
    assert (updated.text, updated.importance) == ("Alice has a brass key.", 1)
    assert updated.contributions == contributions
    assert updated.present == ["Alice"]
    assert memory.add_many.await_args.args[0][0]["text"] == "Alice has a brass key."
    assert await update_fact(scene, "F404", text="ghost", importance=2) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("importance", [2, 3])
async def test_rebuild_of_the_same_view_keeps_the_edit_and_the_id(
    supported_scene,  # noqa: F811
    monkeypatch,
    importance,
):
    # 2 returns the identical contribution; 3 differs, so the record is re-attached
    scene, summarizer, _ = supported_scene
    _, source = chapter(scene, "Alice has a key.", ("Alice",))
    fact = (
        await store(scene, source, ("Alice",), "Alice has a key.", subjects=["key"])
    )[0]
    await update_fact(scene, fact.id, text="Alice has a brass key.", importance=1)
    monkeypatch.setattr(
        summarizer,
        "extract_facts",
        AsyncMock(
            return_value=[
                ParsedFact(
                    text="Alice has a key.", subjects=["key"], importance=importance
                )
            ]
        ),
    )

    assert await summarizer.rebuild_supported_facts(scene, [source]) == "ok"
    assert set(scene.world_state.facts) == {fact.id}
    rebuilt = scene.world_state.facts[fact.id]
    assert (rebuilt.text, rebuilt.importance) == ("Alice has a brass key.", 1)
    assert rebuilt.contributions[0].text == "Alice has a key."
    assert rebuilt.contributions[0].importance == importance
    assert character_fact(scene, rebuilt, "Alice").text == "Alice has a brass key."


@pytest.mark.asyncio
async def test_false_mark_survives_re_attach(
    supported_scene,  # noqa: F811
    monkeypatch,
):
    scene, summarizer, _ = supported_scene
    _, source = chapter(scene, "Alice has a key.", ("Alice",))
    fact = (
        await store(scene, source, ("Alice",), "Alice has a key.", subjects=["key"])
    )[0]
    stored = scene.world_state.facts[fact.id]
    stored.false = True
    await update_fact(scene, fact.id, text="Alice has a brass key.", importance=1)
    monkeypatch.setattr(
        summarizer,
        "extract_facts",
        AsyncMock(
            return_value=[
                ParsedFact(text="Alice has a key.", subjects=["key"], importance=3)
            ]
        ),
    )

    assert await summarizer.rebuild_supported_facts(scene, [source]) == "ok"
    rebuilt = scene.world_state.facts[fact.id]
    assert (rebuilt.text, rebuilt.importance, rebuilt.false) == (
        "Alice has a brass key.",
        1,
        True,
    )


@pytest.mark.asyncio
async def test_author_link_survives_a_changed_contribution(
    supported_scene,  # noqa: F811
    monkeypatch,
):
    scene, summarizer, _ = supported_scene
    _, source = chapter(scene, "Alice has a key.", ("Alice",))
    fact = (await store(scene, source, ("Alice",), "Alice has a key."))[0]
    scene.world_state.facts["manual"] = Fact(id="manual", text="An author predecessor.")
    await update_fact(scene, fact.id, supersedes="manual")
    monkeypatch.setattr(
        summarizer,
        "extract_facts",
        AsyncMock(return_value=[ParsedFact(text="Alice has a key.", importance=3)]),
    )

    assert await summarizer.rebuild_supported_facts(scene, [source]) == "ok"
    rebuilt = scene.world_state.facts[fact.id]
    assert (
        rebuilt.supersedes == "manual"
        and rebuilt.link_edited is True
        and rebuilt.text_edited is False
    )
    assert rebuilt.contributions[0].importance == 3
    # the character's own chain still comes from their contributions
    assert character_fact(scene, rebuilt, "Alice").supersedes is None


@pytest.mark.asyncio
async def test_marks_and_links_leave_merged_wordings_alone(
    supported_scene,  # noqa: F811
    monkeypatch,
):
    from talemate.knowledge.graph import bucket as character_bucket
    from test_fact_reconciliation import evidence_message, extract

    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    monkeypatch.setattr(
        "talemate.knowledge.fact_comparisons.FactComparisons.distance",
        AsyncMock(return_value=0.01),
    )
    await extract(scene, source, "Alice", "Alice rang the bell.")
    await extract(scene, source, "Bob", "The bell was rung by Alice.")
    (fact_id,) = scene.world_state.facts
    scene.world_state.facts["older"] = Fact(id="older", text="An older bell.")
    # Mark false and Set supersedes send only their own field
    await update_fact(scene, fact_id, false=True)
    await update_fact(scene, fact_id, supersedes="older")
    stored = scene.world_state.facts[fact_id]
    assert (stored.false, stored.supersedes) == (True, "older")
    assert (stored.text_edited, stored.link_edited) == (False, True)
    assert character_bucket(scene, "Alice")[0][0].text == "Alice rang the bell."
    assert character_bucket(scene, "Bob")[0][0].text == "The bell was rung by Alice."
    assert "text_edited" not in stored.model_dump()
    # a re-pick of the same link is still an authored link
    stored.link_edited = False
    await update_fact(scene, fact_id, supersedes="older")
    assert scene.world_state.facts[fact_id].link_edited is True


@pytest.mark.asyncio
async def test_saving_the_canonical_wording_from_a_character_row_is_an_edit(
    supported_scene,  # noqa: F811
    monkeypatch,
):
    from talemate.knowledge.graph import bucket as character_bucket
    from test_fact_reconciliation import evidence_message, extract

    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    monkeypatch.setattr(
        "talemate.knowledge.fact_comparisons.FactComparisons.distance",
        AsyncMock(return_value=0.01),
    )
    await extract(scene, source, "Alice", "Alice rang the bell.")
    await extract(scene, source, "Bob", "The bell was rung by Alice.")
    (fact_id,) = scene.world_state.facts
    stored = scene.world_state.facts[fact_id]
    # Bob's row showed his wording; the author types the record's text into it
    assert character_bucket(scene, "Bob")[0][0].text != stored.text
    await update_fact(scene, fact_id, text=stored.text, importance=2)
    assert scene.world_state.facts[fact_id].text_edited is True
    assert character_bucket(scene, "Bob")[0][0].text == stored.text


@pytest.mark.asyncio
async def test_edit_that_picks_one_merged_wording_wins_everywhere(
    supported_scene,  # noqa: F811
    monkeypatch,
):
    from talemate.knowledge.graph import bucket as character_bucket
    from test_fact_reconciliation import evidence_message, extract

    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    monkeypatch.setattr(
        "talemate.knowledge.fact_comparisons.FactComparisons.distance",
        AsyncMock(return_value=0.01),
    )
    await extract(scene, source, "Alice", "Alice rang the bell.")
    await extract(scene, source, "Bob", "The bell was rung by Alice.")
    (fact_id,) = scene.world_state.facts
    await update_fact(scene, fact_id, text="The bell was rung by Alice.", importance=2)
    for name in ("Alice", "Bob"):
        assert character_bucket(scene, name)[0][0].text == "The bell was rung by Alice."


@pytest.mark.asyncio
async def test_perception_edit_reaches_every_reader(supported_scene):  # noqa: F811
    scene, _, _ = supported_scene
    fact, _ = await summary_fact(scene, "Alice has a key.", subjects=["key"])
    scene.world_state.topics = {"T1": Topic(id="T1", name="key", fact_ids=[fact.id])}
    handler = handler_for(scene)

    with patch(
        "talemate.server.world_state_manager.knowledge.refresh_topics", AsyncMock()
    ):
        await handler.handle_update_fact(
            {"fact_id": fact.id, "text": "Alice has a brass key.", "importance": 3}
        )

    (frame,) = frames(handler, "fact_updated")
    assert frame["data"]["id"] == fact.id
    assert (frame["data"]["text"], frame["data"]["importance"]) == (
        "Alice has a brass key.",
        3,
    )
    assert frame["data"]["contributions"][0]["text"] == "Alice has a key."
    assert [item.text for item in facts_for_entry(scene, "base")] == [
        "Alice has a brass key."
    ]
    (row,) = topic_facts(scene, "Alice", "T1")
    assert (row.text, row.importance, row.known) == ("Alice has a brass key.", 3, True)
    (unknown,) = topic_facts(scene, "Bob", "T1")
    assert (unknown.text, unknown.known) == ("Alice has a brass key.", False)
    recent, _ = known_facts(scene, "Alice", prompt=False)
    assert [item.text for item in recent] == ["Alice has a brass key."]


@pytest.fixture
def standard_scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.world_state.facts = {
        "F1": Fact(
            id="F1",
            text="Edwin keeps the light.",
            ts=1,
            present=["Edwin", "Mara"],
            archive_id="A1",
            subjects=["Edwin"],
        )
    }
    scene.world_state.topics = {"T1": Topic(id="T1", name="light", fact_ids=["F1"])}
    return scene


@pytest.mark.asyncio
async def test_standard_edit_reaches_every_reader(standard_scene):
    scene = standard_scene
    handler = handler_for(scene)
    with (
        ActiveScene(scene),
        patch(
            "talemate.server.world_state_manager.knowledge.refresh_topics", AsyncMock()
        ),
        patch.object(get_agent("memory"), "add_many", AsyncMock()) as add_many,
    ):
        await handler.handle_update_fact(
            {"fact_id": "F1", "text": "Edwin tends the light.", "importance": 1}
        )
        (frame,) = frames(handler, "fact_updated")
        assert frame["data"]["text"] == "Edwin tends the light."
        assert frame["data"]["importance"] == 1
        assert frame["data"]["archive_id"] == "A1"
        assert add_many.await_args.args[0][0]["text"] == "Edwin tends the light."
        assert [item.text for item in facts_for_entry(scene, "A1")] == [
            "Edwin tends the light."
        ]
        (row,) = topic_facts(scene, "Mara", "T1")
        assert (row.text, row.importance, row.subjects) == (
            "Edwin tends the light.",
            1,
            ["Edwin"],
        )
        recent, _ = known_facts(scene, "Edwin", prompt=False)
        assert [item.text for item in recent] == ["Edwin tends the light."]


@pytest.mark.asyncio
async def test_a_patch_names_only_the_fields_the_author_saved(standard_scene):
    scene = standard_scene
    handler = handler_for(scene)
    with (
        ActiveScene(scene),
        patch(
            "talemate.server.world_state_manager.knowledge.refresh_topics", AsyncMock()
        ),
        patch.object(get_agent("memory"), "add_many", AsyncMock()),
    ):
        await handler.handle_update_fact({"fact_id": "F1", "false": True})
        stored = scene.world_state.facts["F1"]
        assert (stored.false, stored.text_edited, stored.link_edited) == (
            True,
            False,
            False,
        )
        await handler.handle_update_fact({"fact_id": "F1", "importance": 3})
        assert (stored.text, stored.importance, stored.text_edited) == (
            "Edwin keeps the light.",
            3,
            False,
        )
        await handler.handle_update_fact({"fact_id": "F1", "text": "Only the text."})
        assert (stored.text, stored.importance, stored.text_edited) == (
            "Only the text.",
            3,
            True,
        )
    assert len(frames(handler, "fact_updated")) == 3


@pytest.mark.asyncio
async def test_update_payload_refuses_blank_text_and_unknown_ids(standard_scene):
    scene = standard_scene
    handler = handler_for(scene)
    with (
        ActiveScene(scene),
        patch(
            "talemate.server.world_state_manager.knowledge.refresh_topics", AsyncMock()
        ) as refresh,
    ):
        with pytest.raises(pydantic.ValidationError):
            await handler.handle_update_fact(
                {"fact_id": "F1", "text": "   ", "importance": 2}
            )
        with pytest.raises(pydantic.ValidationError):
            await handler.handle_update_fact({"fact_id": "F1", "text": " "})
        await handler.handle_update_fact(
            {"fact_id": "F9", "text": "ghost", "importance": 2}
        )
    assert scene.world_state.facts["F1"].text == "Edwin keeps the light."
    assert not frames(handler, "fact_updated")
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_replaces_both_wordings_of_a_merged_fact(
    supported_scene,  # noqa: F811
    monkeypatch,
):
    from talemate.knowledge.graph import bucket as character_bucket
    from test_fact_reconciliation import evidence_message, extract

    scene, _, _ = supported_scene
    _, source = evidence_message(scene)
    monkeypatch.setattr(
        "talemate.knowledge.fact_comparisons.FactComparisons.distance",
        AsyncMock(return_value=0.01),
    )
    await extract(scene, source, "Alice", "Alice rang the bell.")
    await extract(scene, source, "Bob", "The bell was rung by Alice.")
    (fact_id,) = scene.world_state.facts
    assert character_bucket(scene, "Alice")[0][0].text == "Alice rang the bell."
    assert character_bucket(scene, "Bob")[0][0].text == "The bell was rung by Alice."

    await update_fact(scene, fact_id, text="Alice rang the harbour bell.", importance=2)
    for name in ("Alice", "Bob"):
        assert (
            character_bucket(scene, name)[0][0].text == "Alice rang the harbour bell."
        )
    stored = scene.world_state.facts[fact_id]
    assert {item.text for item in stored.contributions} == {
        "Alice rang the bell.",
        "The bell was rung by Alice.",
    }
