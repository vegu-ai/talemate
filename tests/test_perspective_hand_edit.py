from _knowledge_stale_helpers import not_current
import pytest

from talemate.knowledge.perspectives import (
    edit_message_view,
    invalidate_message_view_dependents,
    message_view_dependents,
    select_character_view,
    set_source_perspectives,
    source_reference,
)
from talemate.scene_message import DirectorMessage, NarratorMessage

import test_knowledge_perspectives

add_layered_view = test_knowledge_perspectives.add_layered_view
message_ref = test_knowledge_perspectives.message_ref
notifications = test_knowledge_perspectives.notifications
scene = test_knowledge_perspectives.scene
scene_data = test_knowledge_perspectives.scene_data


def summary_ref(scene):
    return source_reference(scene, "summary", "summary-1")


def test_edit_replaces_one_view_and_keeps_its_identity(scene, notifications):
    reference = edit_message_view(scene, 101, "Alice", "  Alice burns the ledger. ")
    view = select_character_view(scene, message_ref(scene), "Alice")
    assert view.status == "ready"
    assert view.text == "Alice burns the ledger."
    assert reference.view_id == "alice-view"
    assert reference.view_revision == 2
    assert reference.revision == 1
    assert (
        select_character_view(scene, message_ref(scene), "Bob").text
        == "Bob sees Alice kneel beside the bed."
    )
    assert [event.affected for event in notifications] == [(reference,)]


def test_edit_starts_no_cascade(scene):
    layered = add_layered_view(scene)
    edit_message_view(scene, 101, "Alice", "Alice burns the ledger.")
    summary = select_character_view(scene, summary_ref(scene), "Alice")
    assert summary.status == "ready"
    assert summary.text == "Alice concealed the ledger under the bed."
    assert select_character_view(scene, layered, "Alice").status == "ready"
    cited = scene.archived_history[0]["knowledge"]["views"][0]["sources"][0]
    assert cited["view_revision"] == 2
    assert scene.archived_history[0]["knowledge"]["views"][0]["revision"] == 1


def test_dependents_count_is_what_the_invalidation_flags(scene, notifications):
    layered = add_layered_view(scene)
    edit_message_view(scene, 101, "Alice", "Alice burns the ledger.")
    dependents = message_view_dependents(scene, 101, "Alice")
    assert {reference.key for reference in dependents} == {
        ("summary", "summary-1", 0),
        ("summary", "layer-1", 1),
    }
    assert invalidate_message_view_dependents(scene, 101, "Alice") == len(dependents)
    assert select_character_view(scene, summary_ref(scene), "Alice").stale
    assert select_character_view(scene, layered, "Alice").stale
    assert (
        select_character_view(scene, message_ref(scene), "Alice").text
        == "Alice burns the ledger."
    )
    assert set(notifications[-1].affected[1:]) == set(dependents)


def test_view_without_dependents_reports_none(scene):
    edit_message_view(scene, 101, "Bob", "Bob sees nothing odd.")
    assert message_view_dependents(scene, 101, "Bob") == []
    assert invalidate_message_view_dependents(scene, 101, "Bob") == 0


def test_stale_citation_is_not_revived(scene):
    edit_message_view(scene, 101, "Alice", "First edit.")
    view = scene.archived_history[0]["knowledge"]["views"][0]
    view["sources"][0]["view_revision"] = 1
    edit_message_view(scene, 101, "Alice", "Second edit.")
    assert view["sources"][0]["view_revision"] == 1
    assert not_current(scene, summary_ref(scene), "Alice")


def test_empty_text_omits_the_view(scene):
    edit_message_view(scene, 101, "Alice", "   ")
    view = select_character_view(scene, message_ref(scene), "Alice")
    assert view.status == "omitted"
    assert view.text is None


def test_identical_text_is_a_noop(scene, notifications):
    assert edit_message_view(scene, 101, "Alice", "Alice burns the ledger.")
    assert edit_message_view(scene, 101, "Alice", "Alice burns the ledger.") is None
    assert message_ref(scene).revision == 1
    assert len(notifications) == 1


def analysis_view(scene):
    """Views as the Summarizer writes them: each cites what its audience knew before."""
    scene.history.append(NarratorMessage("A bell rings.", id=102))

    def cited(name):
        return select_character_view(scene, message_ref(scene), name).source

    set_source_perspectives(
        scene,
        "message",
        102,
        [
            {
                "audience": ["Cara", "Dan"],
                "status": "ready",
                "text": "A bell rings somewhere below.",
                "sources": [cited("Cara")],
            },
            {"audience": ["Erin"], "status": "omitted", "sources": [cited("Erin")]},
        ],
    )
    return scene.history[-1]


@pytest.mark.parametrize(
    "character,text",
    [("Cara", "  A bell rings somewhere below. "), ("Erin", ""), ("Erin", "   ")],
)
def test_same_text_and_status_writes_nothing_to_an_analysis_view(
    scene, notifications, character, text
):
    message = analysis_view(scene)
    before = message.knowledge
    order, events = scene.knowledge.last_order, len(notifications)
    assert edit_message_view(scene, 102, character, text) is None
    assert message.knowledge is before
    assert scene.knowledge.last_order == order
    assert len(notifications) == events
    assert before.views[0].sources and before.views[0].audience == ("Cara", "Dan")


def test_changed_text_on_an_analysis_view_is_a_hand_edit(scene):
    message = analysis_view(scene)
    reference = edit_message_view(scene, 102, "Cara", "Cara hears a bell.")
    assert reference.view_id != message.knowledge.views[0].id
    assert select_character_view(scene, reference, "Cara").text == "Cara hears a bell."
    assert (
        select_character_view(
            scene, source_reference(scene, "message", 102), "Dan"
        ).text
        == "A bell rings somewhere below."
    )


@pytest.mark.parametrize("name", ["Erin", "Finn", "Grace", "Hazel"])
def test_empty_cell_with_a_path_accepts_an_edit(scene, name):
    edit_message_view(scene, 101, name, f"{name} hears a floorboard.")
    view = select_character_view(scene, message_ref(scene), name)
    assert view.text == f"{name} hears a floorboard."


def test_message_without_knowledge_accepts_an_edit(scene):
    scene.history.append(NarratorMessage("A bell rings.", id=102))
    reference = edit_message_view(scene, 102, "Alice", "Alice hears a bell.")
    assert (
        select_character_view(scene, reference, "Alice").text == "Alice hears a bell."
    )
    assert scene.history[-1].knowledge.acquired.order == 4
    assert scene.knowledge.last_order == 4


def test_shared_view_is_split_for_the_edited_character(scene):
    scene.history.append(NarratorMessage("The steps stop.", id=102))
    shared = select_character_view(scene, message_ref(scene), "Cara").source
    later = set_source_perspectives(
        scene,
        "message",
        102,
        [
            {
                "audience": ["Cara", "Dan"],
                "status": "ready",
                "text": "The steps stop at the door.",
                "sources": [shared],
            }
        ],
    )
    edit_message_view(scene, 101, "Cara", "Cara hears Alice's steps.")
    cara = select_character_view(scene, message_ref(scene), "Cara")
    dan = select_character_view(scene, message_ref(scene), "Dan")
    assert cara.text == "Cara hears Alice's steps."
    assert dan.text == "Footsteps sound in the room."
    assert dan.source.view_id == "shared-view"
    assert cara.source.view_id != "shared-view"
    for name in ("Cara", "Dan"):
        view = select_character_view(scene, later, name)
        assert view.status == "ready"
        assert view.text == "The steps stop at the door."
    assert message_view_dependents(scene, 101, "Cara") == [
        select_character_view(scene, later, "Cara").source
    ]


def test_edit_survives_a_later_analysis_publication(scene):
    edit_message_view(scene, 101, "Alice", "Alice burns the ledger.")
    knowledge = scene.history[0].knowledge
    set_source_perspectives(
        scene,
        "message",
        101,
        [view.model_dump(exclude={"revision"}) for view in knowledge.views],
    )
    assert (
        select_character_view(scene, message_ref(scene), "Alice").text
        == "Alice burns the ledger."
    )


def test_message_text_change_flags_the_edit(scene):
    scene.history[0].present = ["Alice"]
    scene.history[0].mark_revision_committed()
    edit_message_view(scene, 101, "Alice", "Alice burns the ledger.")
    scene.edit_message(101, "The ledger never arrived.")
    view = select_character_view(scene, message_ref(scene), "Alice")
    assert view.stale
    assert view.text == "Alice burns the ledger."


def test_refusals_change_nothing(scene, notifications):
    scene.history.append(DirectorMessage(message="Bob, hurry.", id=102))
    before = scene.history[0].knowledge
    with pytest.raises(ValueError, match="no perspectives"):
        edit_message_view(scene, 102, "Bob", "Bob hurries.")
    with pytest.raises(ValueError, match="does not exist"):
        edit_message_view(scene, 999, "Bob", "Bob hurries.")
    with pytest.raises(ValueError, match="Unresolved perspective audience"):
        edit_message_view(scene, 101, "Nobody", "Text.")
    scene.knowledge_eligibility = "legacy"
    with pytest.raises(ValueError, match="perception mode"):
        edit_message_view(scene, 101, "Bob", "Bob hurries.")
    assert scene.history[0].knowledge == before
    assert notifications == []


def test_uncommitted_version_refuses_the_edit(scene):
    message = scene.history[0]
    message.append_version("A new version of the passage.", source="custom")
    assert not message.revision_matches_baseline
    with pytest.raises(ValueError, match="not current"):
        edit_message_view(scene, 101, "Alice", "Alice burns the ledger.")
