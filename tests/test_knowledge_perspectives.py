import copy
import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import MockScene
import test_scene_format
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.history import HistoryEntry, update_history_entry
from talemate.knowledge.perspective_models import (
    CharacterView,
    PerspectiveOutput,
    SourcePerspectives,
    SourceReference,
)
from talemate.knowledge.perspectives import (
    add_disclosure,
    bind_perspective_sources,
    perspectives_changed,
    select_character_view,
    set_source_perspectives,
    source_reference,
    validate_saved_knowledge,
)
from talemate.load import load_scene_from_data, load_scene_from_zip, _load_history


FIXTURE = Path(__file__).parent / "data/knowledge_perspectives/scene.json"
load_env = test_scene_format.load_env


@pytest.fixture
def scene_data():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def scene(scene_data):
    scene = MockScene()
    scene.knowledge_eligibility = "perception"
    scene.knowledge = validate_saved_knowledge(scene_data)
    scene.character_data = {
        name: Character(**data) for name, data in scene_data["character_data"].items()
    }
    scene.history = _load_history(copy.deepcopy(scene_data["history"]))
    scene.archived_history = copy.deepcopy(scene_data["archived_history"])
    bind_perspective_sources(scene)
    return scene


@pytest.fixture
def notifications(scene):
    events = []

    def receiver(sender, *, event):
        assert sender is scene
        events.append(event)

    perspectives_changed.connect(receiver, sender=scene, weak=False)
    yield events
    perspectives_changed.disconnect(receiver, sender=scene)


def message_ref(scene):
    return source_reference(scene, "message", 101)


def test_distinct_shared_and_reader_content(scene, scene_data):
    ref = message_ref(scene)
    alice = select_character_view(scene, ref, "Alice")
    bob = select_character_view(scene, ref, "Bob")
    cara = select_character_view(scene, ref, "Cara")
    dan = select_character_view(scene, ref, "Dan")
    assert alice.text == "Alice hides the ledger beneath the bed."
    assert bob.text == "Bob sees Alice kneel beside the bed."
    assert cara == dan
    assert cara.text == "Footsteps sound in the room."
    assert alice.source.view_id == "alice-view"
    assert alice.acquired.order == 1
    assert scene.history[0].message == scene_data["history"][0]["message"]


@pytest.mark.parametrize(
    "name,status",
    [
        ("Erin", "omitted"),
        ("Finn", "pending"),
        ("Grace", "failed"),
        ("Hazel", "unavailable"),
    ],
)
def test_explicit_omission_differs_from_unavailable(scene, name, status):
    result = select_character_view(scene, message_ref(scene), name)
    assert result.status == status
    assert result.text is None


def test_legacy_mode_does_not_create_or_select_views(scene):
    scene.knowledge_eligibility = "legacy"
    assert (
        select_character_view(scene, message_ref(scene), "Alice").status
        == "unavailable"
    )
    before = scene.json
    with pytest.raises(ValueError, match="perception mode"):
        add_disclosure(scene, "Text", ["Alice"])
    assert scene.json == before


@pytest.mark.parametrize(
    "output",
    [
        {"audience": [], "status": "ready", "text": "Text"},
        {"audience": "Alice", "status": "ready", "text": "Text"},
        {"audience": ["Alice", "Alice"], "status": "ready", "text": "Text"},
        {"audience": [" Alice"], "status": "ready", "text": "Text"},
        {"audience": [12], "status": "ready", "text": "Text"},
        {"audience": ["Alice"], "status": "omitted", "text": "Secret"},
        {"audience": ["Alice"], "status": "ready", "text": "  "},
        {"audience": ["Alice"], "status": "missing"},
        {"audience": ["Alice"], "status": "failed", "text": "Secret"},
        {"id": " ", "audience": ["Alice"], "status": "pending"},
    ],
)
def test_rejects_invalid_output(output):
    with pytest.raises(ValidationError):
        PerspectiveOutput.model_validate(output)


@pytest.mark.parametrize("audience", [["Nobody"], ["alice"], ["*"], ["__narrator__"]])
def test_unresolved_audience_is_transactional(scene, notifications, audience):
    before = scene.json
    with pytest.raises(ValueError, match="Unresolved"):
        set_source_perspectives(
            scene,
            "message",
            101,
            [{"audience": audience, "status": "ready", "text": "Text"}],
        )
    assert scene.json == before
    assert notifications == []


def test_overlapping_views_rejected_without_mutation(scene, notifications):
    before = scene.json
    with pytest.raises(ValidationError, match="overlapping"):
        set_source_perspectives(
            scene,
            "message",
            101,
            [
                {"audience": ["Alice", "Bob"], "status": "ready", "text": "Shared"},
                {"audience": ["Bob"], "status": "omitted"},
            ],
        )
    assert scene.json == before
    assert notifications == []


@pytest.mark.parametrize("edit", ["direct", "scene", "append", "switch"])
def test_text_changes_advance_revision_and_invalidate_descendants(
    scene, notifications, edit
):
    message = scene.history[0]
    original = message_ref(scene)
    disclosure = source_reference(scene, "disclosure", "disclosure-1")
    if edit == "direct":
        message.message = "Alice puts a book on the desk."
    elif edit == "scene":
        scene.edit_message(101, "Alice puts a book on the desk.")
    elif edit == "append":
        scene.append_message_version(101, "Alice puts a book on the desk.", "revision")
    else:
        scene.append_message_version(101, "Alice puts a book on the desk.", "revision")
        scene.set_message_active_version(101, 0)
    assert message.knowledge.revision == (3 if edit == "switch" else 2)
    assert message.rev == 9
    assert select_character_view(scene, original, "Alice").status == "pending"
    assert select_character_view(scene, message_ref(scene), "Alice").text is None
    summary = source_reference(scene, "summary", "summary-1")
    assert select_character_view(scene, summary, "Alice").status == "pending"
    assert (
        select_character_view(scene, disclosure, "Bob").text
        == "The ledger is under the bed."
    )
    assert {ref.key for ref in notifications[0].affected} == {original.key, summary.key}
    assert notifications[0].source == original
    assert notifications[0].reason == "content"


def test_identical_text_and_changelog_revision_do_not_invalidate(scene, notifications):
    message = scene.history[0]
    scene.edit_message(101, message.message)
    message.rev = 50
    assert message.knowledge.revision == 1
    assert notifications == []


def test_disclosures_have_independent_content_order_and_provenance(scene):
    scene.ts = 456
    evidence = source_reference(scene, "summary", "summary-1")
    disclosure = add_disclosure(
        scene,
        "Alice said the ledger was burned.",
        ["Cara", "Dan"],
        provenance=[evidence],
    )
    assert disclosure.acquired.order == 4
    assert disclosure.acquired.ts == 456
    assert disclosure.provenance == (evidence,)
    assert "fact" not in disclosure.model_dump()
    scene.delete_message(101)
    ref = source_reference(scene, "disclosure", disclosure.id)
    assert select_character_view(scene, ref, "Cara").text == disclosure.text
    assert select_character_view(scene, ref, "Alice").status == "unavailable"


async def test_summary_edit_preserves_sources_and_invalidates_view(scene):
    original = scene.archived_history[0]["knowledge"]["views"][0]["sources"]
    await update_history_entry(
        scene,
        HistoryEntry(
            text="A revised reader summary", ts=20, index=0, layer=0, id="summary-1"
        ),
    )
    stored = scene.archived_history[0]["knowledge"]
    assert stored["revision"] == 2
    assert stored["views"][0]["status"] == "pending"
    assert stored["views"][0]["sources"] == original
    assert stored["views"][0]["text"] is None


def test_ready_summary_requires_appropriate_fresh_source_view(scene):
    ref = select_character_view(scene, message_ref(scene), "Alice").source
    with pytest.raises(ValueError, match="outside its audience"):
        set_source_perspectives(
            scene,
            "summary",
            "summary-1",
            [
                {
                    "audience": ["Bob"],
                    "status": "ready",
                    "text": "Private",
                    "sources": [ref],
                }
            ],
        )
    summary = set_source_perspectives(
        scene,
        "summary",
        "summary-1",
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice knows the location.",
                "sources": [ref],
            }
        ],
    )
    assert (
        select_character_view(scene, summary, "Alice").text
        == "Alice knows the location."
    )


def test_raw_text_change_cannot_serve_stale_view(scene):
    ref = source_reference(scene, "summary", "summary-1")
    scene.archived_history[0]["text"] = "Changed without adapter"
    assert select_character_view(scene, ref, "Alice").status == "pending"


def test_rename_retains_views_and_does_not_grant_old_name(scene, notifications):
    bob = scene.character_data["Bob"]
    with ActiveScene(scene):
        bob.rename("Robert")
    assert "Bob" not in scene.character_data
    scene.character_data["Bob"] = Character(name="Bob")
    assert select_character_view(scene, message_ref(scene), "Robert").status == "ready"
    assert (
        select_character_view(scene, message_ref(scene), "Bob").status == "unavailable"
    )
    disclosure = source_reference(scene, "disclosure", "disclosure-1")
    assert select_character_view(scene, disclosure, "Robert").status == "ready"
    assert select_character_view(scene, disclosure, "Bob").status == "unavailable"
    assert notifications[-1].reason == "rename"
    validate_saved_knowledge(json.loads(scene.json))


@pytest.mark.parametrize("name", ["Alice", "alice", "", " Alice "])
def test_invalid_rename_changes_nothing(scene, name):
    before = scene.json
    with ActiveScene(scene), pytest.raises(ValueError):
        scene.character_data["Bob"].rename(name)
    assert scene.json == before


async def test_scene_save_reload_retains_all_evidence(load_env, scene_data):
    original = copy.deepcopy(scene_data)
    await load_scene_from_data(load_env, scene_data, name="perspectives.json")
    await load_env.save()
    path = Path(load_env.save_dir) / "perspectives.json"
    saved = json.loads(path.read_text())
    assert saved["history"][0]["knowledge"] == original["history"][0]["knowledge"]
    assert (
        saved["archived_history"][0]["knowledge"]
        == original["archived_history"][0]["knowledge"]
    )
    assert saved["knowledge"] == original["knowledge"]
    await load_scene_from_data(load_env, saved, name=str(path))
    assert (
        select_character_view(load_env, message_ref(load_env), "Bob").text
        == "Bob sees Alice kneel beside the bed."
    )
    load_env.edit_message(101, "Changed after reload")
    assert load_env.history[0].knowledge.revision == 2


async def test_perception_zip_success_preserves_records(load_env, tmp_path, scene_data):
    path = tmp_path / "perspectives.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("scene.json", json.dumps(scene_data))
    original = path.read_bytes()
    await load_scene_from_zip(load_env, str(path))
    assert path.read_bytes() == original
    for filename in ["perspectives.json", "initial.json"]:
        saved = json.loads((Path(load_env.save_dir) / filename).read_text())
        assert saved["knowledge"] == scene_data["knowledge"]
        assert saved["history"][0]["knowledge"] == scene_data["history"][0]["knowledge"]


async def test_invalid_audience_rejected_before_scene_assignment(load_env, scene_data):
    scene_data["history"][0]["knowledge"]["views"][0]["audience"] = ["Nobody"]
    before = load_env.json
    with pytest.raises(ValueError, match="Unresolved"):
        await load_scene_from_data(load_env, scene_data)
    assert load_env.json == before


@pytest.mark.parametrize(
    "kind,identity",
    [
        ("message", "101"),
        ("message", True),
        ("message", -1),
        ("summary", 1),
        ("disclosure", ""),
    ],
)
def test_invalid_source_identity(kind, identity):
    with pytest.raises(ValidationError):
        SourceReference(kind=kind, id=identity, revision=1)


def test_selection_result_cannot_carry_unavailable_text():
    with pytest.raises(ValidationError):
        CharacterView(status="pending", text="Reader secret")


def test_legacy_serialization_has_no_new_fields():
    from talemate.scene_message import CharacterMessage
    from talemate.history import ArchiveEntry

    message = CharacterMessage("Legacy text")
    assert "knowledge" not in message.to_dict()
    assert "knowledge" not in message.model_dump()
    assert "knowledge" not in ArchiveEntry(text="Legacy summary").model_dump()
    assert "knowledge" not in MockScene().serialize


def test_source_references_survive_stale_reload(scene):
    scene.edit_message(101, "New reader text")
    saved = json.loads(scene.json)
    state = validate_saved_knowledge(saved)
    assert state.disclosures[0].provenance[0].revision == 1
    summary = SourcePerspectives.model_validate(
        saved["archived_history"][0]["knowledge"]
    )
    assert summary.views[0].sources[0].revision == 1
    assert summary.views[0].status == "pending"


def add_layered_view(scene):
    scene.layered_history = [
        [{"id": "layer-1", "text": "Alice remembers the ledger.", "ts": 25}]
    ]
    dependency = select_character_view(
        scene, source_reference(scene, "summary", "summary-1"), "Alice"
    ).source
    return set_source_perspectives(
        scene,
        "summary",
        "layer-1",
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice remembers hiding the ledger.",
                "sources": [dependency],
            }
        ],
        layer=1,
    )


def test_transitive_invalidation_preserves_unrelated_source(scene, notifications):
    from talemate.scene_message import NarratorMessage

    scene.history.append(NarratorMessage("A bell rings.", id=102))
    independent = set_source_perspectives(
        scene,
        "message",
        102,
        [{"audience": ["Alice"], "status": "ready", "text": "A bell rings."}],
    )
    layered = add_layered_view(scene)
    scene.edit_message(101, "The ledger never arrived.")
    assert select_character_view(scene, layered, "Alice").status == "pending"
    assert select_character_view(scene, independent, "Alice").text == "A bell rings."
    assert {ref.key for ref in notifications[-1].affected} == {
        ("message", 101, 0),
        ("summary", "summary-1", 0),
        ("summary", "layer-1", 1),
    }


async def test_layered_summary_adapter_preserves_dependency_records(scene):
    add_layered_view(scene)
    before = copy.deepcopy(scene.layered_history[0][0]["knowledge"])
    updated = await update_history_entry(
        scene,
        HistoryEntry(
            text="Updated layered reader text",
            ts=25,
            index=0,
            layer=1,
            id="layer-1",
        ),
    )
    assert updated.knowledge.revision == 2
    assert updated.knowledge.views[0].status == "pending"
    assert (
        updated.knowledge.model_dump(mode="json")["views"][0]["sources"]
        == before["views"][0]["sources"]
    )


def test_rename_updates_every_summary_layer_without_staling_views(scene):
    layered = add_layered_view(scene)
    with ActiveScene(scene):
        scene.character_data["Alice"].rename("Alicia")
    assert select_character_view(scene, layered, "Alicia").status == "ready"
    scene.character_data["Alice"] = Character(name="Alice")
    assert select_character_view(scene, layered, "Alice").status == "unavailable"
    assert scene.layered_history[0][0]["knowledge"]["views"][0]["audience"] == [
        "Alicia"
    ]


def test_replacing_audience_views_invalidates_dependents(scene, notifications):
    previous_acquisition = scene.history[0].knowledge.acquired
    ref = set_source_perspectives(
        scene,
        "message",
        101,
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Alice saw only a closed box.",
            }
        ],
    )
    assert ref.revision == 1
    assert scene.history[0].knowledge.views[0].revision == 2
    assert scene.history[0].knowledge.acquired == previous_acquisition
    assert select_character_view(scene, ref, "Bob").status == "unavailable"
    assert scene.archived_history[0]["knowledge"]["views"][0]["status"] == "pending"
    assert notifications[-1].reason == "views"


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda data: data.pop("knowledge"), "acquisition counter"),
        (lambda data: data.update(knowledge_eligibility="legacy"), "perception scene"),
        (lambda data: data["history"][0].pop("id"), "persisted source identity"),
        (lambda data: data["knowledge"].update(last_order=0), "counter precedes"),
        (
            lambda data: data["history"].append(copy.deepcopy(data["history"][0])),
            "Duplicate knowledge source",
        ),
        (
            lambda data: data["knowledge"]["disclosures"].append(
                copy.deepcopy(data["knowledge"]["disclosures"][0])
            ),
            "Duplicate disclosure",
        ),
        (
            lambda data: data["character_data"].update(imposter={"name": "alice"}),
            "unambiguous",
        ),
    ],
)
def test_invalid_saved_contract_rejected(scene_data, mutate, match):
    mutate(scene_data)
    with pytest.raises(ValueError, match=match):
        validate_saved_knowledge(scene_data)


def test_standalone_message_invalidates_without_owner(scene):
    from talemate.scene_message import CharacterMessage

    message = CharacterMessage(**scene.history[0].to_dict())
    message.message = "Changed detached message"
    assert message.knowledge.revision == 2
    assert all(
        view.status == "pending" and view.text is None
        for view in message.knowledge.views
    )
    assert scene.history[0].knowledge.revision == 1


def test_failed_disclosure_creation_has_no_side_effects(scene, notifications):
    before = scene.json
    ref = message_ref(scene).model_copy(update={"revision": 99})
    with pytest.raises(ValueError, match="existing source revision"):
        add_disclosure(scene, "Private text", ["Bob"], provenance=[ref])
    with pytest.raises(ValueError, match="Unresolved"):
        add_disclosure(scene, "Private text", ["Nobody"])
    assert scene.json == before
    assert notifications == []


def test_reset_clears_later_disclosures(scene):
    scene.reset()
    assert scene.knowledge.disclosures == ()
    assert scene.knowledge_eligibility == "perception"


@pytest.mark.parametrize("method", ["pop_message", "pop_history", "delete_message"])
async def test_message_removal_emits_invalidation(scene, notifications, method):
    old = message_ref(scene)
    if method == "pop_message":
        scene.pop_message(scene.history[0])
    elif method == "pop_history":
        scene.pop_history("character")
    else:
        scene.delete_message(101)
    assert select_character_view(scene, old, "Alice").status == "unavailable"
    assert notifications[-1].reason == "deleted"
    assert notifications[-1].replacement is None
    assert scene.archived_history[0]["knowledge"]["views"][0]["status"] == "pending"


@pytest.mark.parametrize("name", ["Alice", "Bob", "Cara"])
async def test_character_deletion_save_reload_and_name_reuse(
    load_env, scene_data, name
):
    await load_scene_from_data(load_env, scene_data, name="delete.json")
    add_layered_view(load_env)
    shared = add_disclosure(load_env, "Shared evidence", [name, "Dan"])
    events = []

    def receiver(sender, *, event):
        events.append(event)

    perspectives_changed.connect(receiver, sender=load_env)
    await load_env.remove_character(
        load_env.character_data[name], purge_from_memory=False
    )
    assert len(events) == 1
    assert events[0].reason == "deleted"
    await load_env.save()
    saved = json.loads((Path(load_env.save_dir) / "delete.json").read_text())
    validate_saved_knowledge(saved)
    await load_scene_from_data(load_env, saved, name="delete.json")
    load_env.character_data[name] = Character(name=name)
    for kind, identity, layer in [
        ("message", 101, 0),
        ("summary", "summary-1", 0),
        ("summary", "layer-1", 1),
    ]:
        ref = source_reference(load_env, kind, identity, layer=layer)
        assert select_character_view(load_env, ref, name).status == "unavailable"
    ref = source_reference(load_env, "disclosure", shared.id)
    assert select_character_view(load_env, ref, name).status == "unavailable"
    assert select_character_view(load_env, ref, "Dan").text == "Shared evidence"
    assert all(name not in item.audience for item in load_env.knowledge.disclosures)


def test_dependency_edit_preserves_sibling_views_and_reader_revision(
    scene, notifications
):
    from talemate.scene_message import NarratorMessage

    scene.history.append(NarratorMessage("Bell.", id=102))
    second = set_source_perspectives(
        scene,
        "message",
        102,
        [{"audience": ["Bob"], "status": "ready", "text": "Bell."}],
    )
    first = select_character_view(scene, message_ref(scene), "Alice").source
    summary = set_source_perspectives(
        scene,
        "summary",
        "summary-1",
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Ledger.",
                "sources": [first],
            },
            {
                "audience": ["Bob"],
                "status": "ready",
                "text": "Bell.",
                "sources": [second],
            },
        ],
    )
    sibling = select_character_view(scene, summary, "Bob")
    before = copy.deepcopy(scene.archived_history[0]["knowledge"])
    scene.edit_message(101, "Changed ledger.")
    after = scene.archived_history[0]["knowledge"]
    assert after["revision"] == before["revision"]
    assert after["content_digest"] == before["content_digest"]
    assert after["views"][1] == before["views"][1]
    assert select_character_view(scene, summary, "Alice").status == "pending"
    assert select_character_view(scene, sibling.source, "Bob") == sibling
    assert sibling.source not in notifications[-1].affected


@pytest.mark.parametrize("explicit_id", [False, True])
def test_retry_preserves_sibling_identity_and_dependents(scene, explicit_id):
    outputs = [
        {"audience": ["Alice"], "status": "ready", "text": "Ledger."},
        {"audience": ["Bob"], "status": "failed"},
    ]
    ref = set_source_perspectives(scene, "message", 101, outputs)
    alice = select_character_view(scene, ref, "Alice")
    bob = select_character_view(scene, ref, "Bob")
    summary = set_source_perspectives(
        scene,
        "summary",
        "summary-1",
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Ledger.",
                "sources": [alice.source],
            }
        ],
    )
    if explicit_id:
        outputs[0]["id"] = alice.source.view_id
        outputs[1]["id"] = bob.source.view_id
    outputs[1].update(status="ready", text="Footsteps.")
    retried = set_source_perspectives(scene, "message", 101, outputs)
    assert select_character_view(scene, retried, "Alice") == alice
    new_bob = select_character_view(scene, retried, "Bob")
    assert new_bob.source.view_id == bob.source.view_id
    assert new_bob.source.view_revision == bob.source.view_revision + 1
    assert select_character_view(scene, summary, "Alice").status == "ready"
    assert scene.archived_history[0]["knowledge"]["views"][0]["sources"][
        0
    ] == alice.source.model_dump(mode="json")
    assert select_character_view(scene, bob.source, "Bob").status == "pending"


@pytest.mark.parametrize("dep_status", ["ready", "omitted", "pending", "failed"])
@pytest.mark.parametrize("out_status", ["ready", "omitted", "pending", "failed"])
def test_dependency_currency_readability_matrix(scene, dep_status, out_status):
    dep = {"audience": ["Alice"], "status": dep_status}
    if dep_status == "ready":
        dep["text"] = "Evidence."
    message = set_source_perspectives(scene, "message", 101, [dep])
    evidence = select_character_view(scene, message, "Alice").source
    output = {"audience": ["Alice"], "status": out_status, "sources": [evidence]}
    if out_status == "ready":
        output["text"] = "Summary."
    if out_status in ("ready", "omitted") and dep_status not in ("ready", "omitted"):
        before = scene.json
        with pytest.raises(ValueError, match="dependency"):
            set_source_perspectives(scene, "summary", "summary-1", [output])
        assert scene.json == before
        return
    summary = set_source_perspectives(scene, "summary", "summary-1", [output])
    saved = json.loads(scene.json)
    validate_saved_knowledge(saved)
    scene.history = _load_history(saved["history"])
    scene.archived_history = saved["archived_history"]
    assert select_character_view(scene, summary, "Alice").status == out_status
    scene.history[0].knowledge = scene.history[0].knowledge.invalidated("Changed")
    if out_status == "omitted":
        assert select_character_view(scene, summary, "Alice").status == "pending"


@pytest.mark.parametrize("name", ["alice", "Alice", "", " Bob "])
def test_rename_guard_before_any_records(scene, name):
    scene.knowledge = None
    with ActiveScene(scene), pytest.raises(ValueError):
        scene.character_data["Bob"].rename(name)
    assert scene.character_data["Bob"].name == "Bob"


@pytest.mark.parametrize("eligibility", ["legacy", "perception"])
def test_rename_rekeys_without_records_in_every_mode(scene, eligibility):
    scene.knowledge = None
    scene.knowledge_eligibility = eligibility
    with ActiveScene(scene):
        scene.character_data["Bob"].rename("Robert")
    assert "Bob" not in scene.character_data
    assert scene.character_data["Robert"].name == "Robert"


async def test_load_rejects_ambiguous_names_before_any_records(load_env, scene_data):
    scene_data.pop("knowledge")
    scene_data["history"] = []
    scene_data["archived_history"] = []
    scene_data["character_data"]["Bob"]["name"] = "alice"
    before = load_env.json
    with pytest.raises(ValueError, match="unambiguous"):
        await load_scene_from_data(load_env, scene_data)
    assert load_env.json == before


@pytest.mark.parametrize("reset_progress", [False, True])
def test_export_knowledge_reset_is_isolated_from_live_scene(scene, reset_progress):
    from talemate.export import ExportOptions, scene_export_json

    scene.archived_history[0]["end"] = None
    before = scene.json
    exported = json.loads(
        scene_export_json(
            scene, ExportOptions(name="export", reset_progress=reset_progress)
        )
    )
    assert scene.json == before
    validate_saved_knowledge(exported)
    if reset_progress:
        assert exported["knowledge"]["disclosures"] == []
        assert "knowledge" not in exported["archived_history"][0]
    else:
        assert exported["knowledge"]["disclosures"]
        assert exported["archived_history"][0]["knowledge"]


@pytest.mark.parametrize("reset_path", ["scene", "tool"])
async def test_all_reset_paths_clear_static_views_and_disclosures(
    scene, monkeypatch, reset_path
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from talemate.server.world_state_manager.scene_state_reset import (
        SceneStateResetMixin,
    )

    scene.archived_history[0]["end"] = None
    if reset_path == "scene":
        scene.reset()
    else:
        monkeypatch.setattr(scene, "emit_history", AsyncMock())
        monkeypatch.setattr(scene, "emit_status", Mock())
        handler = SimpleNamespace(
            scene=scene, websocket_handler=Mock(), signal_operation_done=AsyncMock()
        )
        await SceneStateResetMixin.handle_execute_scene_state_reset(
            handler, {"wipe_history": True}
        )
    assert scene.knowledge.disclosures == ()
    assert "knowledge" not in scene.archived_history[0]
    validate_saved_knowledge(json.loads(scene.json))


def test_noop_and_new_audience_publication_notifications(scene, notifications):
    outputs = [
        PerspectiveOutput.model_validate(view.model_dump(exclude={"revision"}))
        for view in scene.history[0].knowledge.views
    ]
    before = scene.json
    set_source_perspectives(scene, "message", 101, outputs)
    assert scene.json == before
    assert notifications == []
    outputs.append(PerspectiveOutput(audience=["Hazel"], status="omitted"))
    set_source_perspectives(scene, "message", 101, outputs)
    assert len(notifications) == 1
    hazel = select_character_view(scene, message_ref(scene), "Hazel")
    assert hazel.source in notifications[0].affected
    assert scene.archived_history[0]["knowledge"]["views"][0]["status"] == "ready"


def test_view_revision_withholds_stale_saved_dependency_without_notification(scene):
    evidence = select_character_view(scene, message_ref(scene), "Alice").source
    summary = set_source_perspectives(
        scene,
        "summary",
        "summary-1",
        [
            {
                "audience": ["Alice"],
                "status": "ready",
                "text": "Ledger.",
                "sources": [evidence],
            }
        ],
    )
    previous = scene.history[0].knowledge
    changed = previous.views[0].model_copy(
        update={"revision": 2, "text": "Different evidence."}
    )
    scene.history[0].knowledge = previous.model_copy(
        update={"views": (changed, *previous.views[1:])}
    )
    validate_saved_knowledge(json.loads(scene.json))
    assert select_character_view(scene, summary, "Alice").status == "pending"
    with pytest.raises(ValueError, match="at this revision"):
        add_disclosure(scene, "Claim", ["Alice"], provenance=[evidence])


@pytest.mark.parametrize("eligibility", ["legacy", "perception"])
@pytest.mark.parametrize("new_name", ["Bob", "bob"])
def test_rename_collision_preserves_both_characters_in_both_modes(
    scene, eligibility, new_name
):
    scene.knowledge_eligibility = eligibility
    scene.knowledge = None
    alice, bob = scene.character_data["Alice"], scene.character_data["Bob"]
    alice.description = "Alice's description"
    bob.description = "Bob's description"
    before = scene.json
    with ActiveScene(scene), pytest.raises(ValueError, match="another character"):
        alice.rename(new_name)
    assert scene.json == before
    assert scene.character_data["Alice"] is alice
    assert scene.character_data["Bob"] is bob
    assert alice.name == "Alice"
    assert bob.name == "Bob"


def test_rename_rejects_occupied_stale_registry_key(scene):
    scene.knowledge_eligibility = "legacy"
    bob = scene.character_data["Bob"]
    bob.name = "Robert"
    before = scene.json
    with ActiveScene(scene), pytest.raises(ValueError, match="another character"):
        scene.character_data["Alice"].rename("Bob")
    assert scene.json == before
    assert scene.character_data["Bob"] is bob


def test_removed_explicit_view_id_cannot_revive_historical_pin(scene, notifications):
    old_pin = select_character_view(scene, message_ref(scene), "Alice").source
    disclosure = add_disclosure(
        scene, "Historical claim", ["Alice"], provenance=[old_pin]
    )
    set_source_perspectives(scene, "message", 101, [])
    saved = json.loads(scene.json)
    scene.knowledge = validate_saved_knowledge(saved)
    scene.history = _load_history(saved["history"])
    bind_perspective_sources(scene)
    before = scene.json
    notifications.clear()
    with pytest.raises(ValueError, match="existing view"):
        set_source_perspectives(
            scene,
            "message",
            101,
            [
                {
                    "id": old_pin.view_id,
                    "audience": ["Alice"],
                    "status": "ready",
                    "text": "Different",
                }
            ],
        )
    assert scene.json == before
    assert notifications == []
    assert select_character_view(scene, old_pin, "Alice").status == "unavailable"
    ref = set_source_perspectives(
        scene,
        "message",
        101,
        [{"audience": ["Alice"], "status": "ready", "text": "Different"}],
    )
    assert select_character_view(scene, ref, "Alice").source.view_id != old_pin.view_id
    assert select_character_view(scene, old_pin, "Alice").status == "unavailable"
    assert scene.knowledge.disclosures[-1].provenance == disclosure.provenance


def test_initial_publication_rejects_unknown_explicit_id_atomically(
    scene, notifications
):
    from talemate.scene_message import NarratorMessage

    scene.history.append(NarratorMessage("Bell", id=102))
    before = scene.json
    with pytest.raises(ValueError, match="existing view"):
        set_source_perspectives(
            scene,
            "message",
            102,
            [
                {
                    "id": "unknown",
                    "audience": ["Alice"],
                    "status": "ready",
                    "text": "Bell",
                }
            ],
        )
    assert scene.json == before
    assert notifications == []


@pytest.mark.parametrize("explicit_id", [False, True])
def test_reordered_audience_is_noop_and_preserves_dependent_prose(
    scene, notifications, explicit_id
):
    output = {
        "audience": ["Alice", "Bob"],
        "status": "ready",
        "text": "Shared evidence",
    }
    source = set_source_perspectives(scene, "message", 101, [output])
    pin = select_character_view(scene, source, "Alice").source
    summary = set_source_perspectives(
        scene,
        "summary",
        "summary-1",
        [
            {
                "audience": ["Alice", "Bob"],
                "status": "ready",
                "text": "Shared summary",
                "sources": [pin],
            }
        ],
    )
    before = scene.json
    notifications.clear()
    output["audience"] = ["Bob", "Alice"]
    if explicit_id:
        output["id"] = pin.view_id
    set_source_perspectives(scene, "message", 101, [output])
    assert scene.json == before
    assert notifications == []
    for name in ["Alice", "Bob"]:
        selected = select_character_view(scene, source, name)
        assert selected.source == pin
        assert select_character_view(scene, pin, name).text == "Shared evidence"
        assert select_character_view(scene, summary, name).text == "Shared summary"
