from _knowledge_step_helpers import push_and_step
from talemate.knowledge.step import knowledge_step
import asyncio
import json
from pathlib import Path
import weakref
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import test_perception_lifecycle
from test_perception_lifecycle import result
from talemate.exceptions import GenerationCancelled
from talemate.character import Character
from talemate.knowledge.perspective_models import (
    PerspectiveView,
    SourcePerspectives,
    content_digest,
)
from talemate.knowledge.perspectives import select_character_view, source_reference
from talemate.knowledge.revision_browsing import (
    RevisionCurrency,
    defer_revision_work,
)
from talemate.knowledge.revision_refresh import (
    _archive_vector_repairs,
    revision_refresh_payload,
    refresh_revision,
    revision_operations,
)
from talemate.instance import get_agent
from talemate.scene_message import CharacterMessage, RevisionIndexRepair
from talemate.scene_message import NarratorMessage
from talemate.server.scene_message import SceneMessagePlugin
from talemate.load import load_scene_from_data
from talemate.prompts import Prompt
from talemate.agents.narrator import _narration

setup = test_perception_lifecycle.setup


@pytest.fixture
async def browsing(setup, monkeypatch):
    scene, summarizer, request = setup
    message = NarratorMessage(message="The bell rings.")
    for index in range(5):
        message.append_version(f"The bell rings {index + 2} times.", "regenerate")
    await push_and_step(scene, message)
    request.reset_mock()
    frames = []
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))
    yield scene, summarizer, request, message, plugin, frames


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [True, False])
async def test_five_swaps_analyze_only_kept_text(browsing, commit):
    scene, summarizer, request, message, plugin, frames = browsing
    for index in [4, 3, 2, 1, 0]:
        await plugin.handle_swap_revision({"id": message.id, "index": index})
        await asyncio.sleep(0)
        assert message.active_version == index
        assert message.id in scene.pending_perception_messages
        request.assert_not_awaited()
    analyzed = []

    async def analyze(*args, **kwargs):
        analyzed.append(kwargs["vars"]["context"]["passage"]["text"])
        return result()

    request.side_effect = analyze
    if commit:
        task = await plugin.handle_commit_revision(
            {"id": message.id, "index": 0, "request_id": "keep"}
        )
        await task
        assert any(f.get("action") == "revision_committed" for f in frames)
        # Duplicate keep requests and later catch-up reuse the valid analysis.
        await (await plugin.handle_commit_revision({"id": message.id, "index": 0}))
        await knowledge_step(scene)
        assert analyzed == ["The bell rings."]
    else:
        await push_and_step(scene, NarratorMessage(message="Alice opens the window."))
        # One request for the kept passage, one for the new passage.
        assert analyzed == ["The bell rings.", "Alice opens the window."]
        assert request.await_count == 2
    assert scene.pending_perception_messages == []
    assert all(view.status == "ready" for view in message.knowledge.views)


@pytest.mark.asyncio
async def test_failed_summary_repair_keeps_revision_baseline_and_journal(
    browsing, monkeypatch
):
    scene, summarizer, request, message, plugin, _ = browsing
    baseline_index = message.revision_state.baseline_index
    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    request.return_value = result()
    monkeypatch.setattr(
        summarizer,
        "repair_summary_views",
        AsyncMock(side_effect=RuntimeError("repair failed")),
    )

    with pytest.raises(RuntimeError, match="repair failed"):
        await refresh_revision(scene, message)
    assert message.revision_state.status == "failed"
    assert message.revision_state.baseline_index == baseline_index
    assert message.revision_state.refresh_journal is not None

    await plugin.handle_swap_revision({"id": message.id, "index": baseline_index})
    assert message.revision_matches_baseline
    assert message.revision_state.refresh_journal is None


@pytest.mark.asyncio
async def test_failed_commit_returns_correlated_error_and_stays_pending(browsing):
    scene, _, request, message, plugin, frames = browsing
    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    request.side_effect = GenerationCancelled("Cancelled by user")
    task = await plugin.handle_commit_revision(
        {"id": message.id, "index": 0, "request_id": "keep"}
    )
    with pytest.raises(GenerationCancelled):
        await task
    assert message.id in scene.pending_perception_messages
    assert any(f.get("request_id") == "keep" and f.get("error") for f in frames)


@pytest.mark.asyncio
async def test_browsing_preserves_and_revives_committed_perceptions(browsing):
    scene, _, request, message, plugin, _ = browsing
    baseline = message.active_version
    knowledge = message.knowledge
    assert message.revision_matches_baseline

    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    assert message.knowledge is knowledge
    assert message.revision_state.status == "deferred"
    assert (
        select_character_view(
            scene, source_reference(scene, "message", message.id), "Bob"
        ).status
        == "pending"
    )

    await plugin.handle_swap_revision({"id": message.id, "index": baseline})
    assert message.knowledge is knowledge
    assert message.revision_state.status == "clean"
    assert (
        select_character_view(
            scene, source_reference(scene, "message", message.id), "Bob"
        ).status
        == "ready"
    )
    request.assert_not_awaited()


def test_revision_state_persists_and_running_reloads_as_deferred():
    message = NarratorMessage(message="The bell rings.")
    message.append_version("The bell rings twice.", "regenerate")
    payload = message.to_dict()
    assert payload["active_version"] == 1
    assert len(payload["versions"]) == 2
    payload["revision_state"]["status"] = "running"

    restored = NarratorMessage.model_validate(payload)

    assert restored.versions == message.versions
    assert restored.active_version == message.active_version
    assert restored.revision_state.status == "deferred"
    assert restored.revision_matches_baseline


def test_equal_text_at_another_index_reuses_valid_baseline():
    message = NarratorMessage(message="The bell rings.")
    message.append_version("The bell rings.", "regenerate")
    assert message.revision_matches_baseline
    message._knowledge_scene = lambda: None

    with defer_revision_work():
        message.set_active_version(0)

    assert message.revision_matches_baseline
    assert message.revision_state.status == "clean"
    assert message.revision_state.baseline_index == 1


@pytest.mark.parametrize("auto_save", [True, False])
@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_swap_defers_saving_and_derived_work(
    persistence_scene_factory, monkeypatch, auto_save, mode
):
    scene = persistence_scene_factory()
    scene.name = "Browse persistence"
    scene.project_name = "browse-persistence"
    scene.knowledge_eligibility = mode
    monkeypatch.setattr(scene.config.game.general, "auto_save", auto_save)
    message = NarratorMessage(message="The bell rings.")
    message.append_version("The bell rings twice.", "regenerate")
    message._knowledge_scene = weakref.ref(scene)
    scene.history = [message]
    await scene.save(copy_name="browse.json")
    save = AsyncMock(wraps=scene.save)
    monkeypatch.setattr(scene, "save", save)
    forbidden = AsyncMock(side_effect=AssertionError("Derived work ran during browse"))
    monkeypatch.setattr("talemate.prompts.Prompt.request", forbidden)
    monkeypatch.setattr(get_agent("memory"), "add", forbidden)
    monkeypatch.setattr(get_agent("memory"), "add_many", forbidden)
    monkeypatch.setattr(get_agent("memory"), "delete", forbidden)
    frames = []
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))

    for index in (0, 1, 0):
        save.reset_mock()
        await plugin.handle_swap_revision(
            {"id": message.id, "index": index, "request_id": str(index)}
        )
        await asyncio.sleep(0)
        assert message.active_version == index
        save.assert_not_awaited()
        assert scene.saved is False
        assert any(
            frame.get("action") == "revision_swapped"
            and frame.get("request_id") == str(index)
            for frame in frames
        )
        forbidden.assert_not_awaited()


@pytest.mark.parametrize("persist", ["commit", "save"])
@pytest.mark.parametrize("index", [0, 1])
async def test_browsed_selection_persists_on_commit_or_normal_save(
    persistence_scene_factory, persist, index
):
    scene = persistence_scene_factory()
    scene.name = "Browse then save"
    scene.project_name = "browse-then-save"
    message = NarratorMessage(message="The bell rings.")
    message.append_version("The bell rings twice.", "regenerate")
    message._knowledge_scene = weakref.ref(scene)
    scene.history = [message]
    await scene.save(copy_name="selected.json")
    path = Path(scene.full_path)
    before = path.read_bytes()
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))

    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    await plugin.handle_swap_revision({"id": message.id, "index": index})
    assert path.read_bytes() == before
    assert scene.saved is False

    if persist == "commit":
        await (await plugin.handle_commit_revision({"id": message.id, "index": index}))
    else:
        await scene.save()

    assert scene.saved is True
    assert json.loads(path.read_text())["history"][0]["active_version"] == index


@pytest.mark.asyncio
async def test_new_history_message_emits_scene_aware_revision_refresh(browsing):
    scene, _, _, _, _, _ = browsing
    scene.knowledge_eligibility = "legacy"
    message = NarratorMessage(message="A new bell rings.")

    await push_and_step(scene, message)
    message.append_version("A new silver bell rings.", "regenerate")

    assert message._knowledge_scene() is scene
    # Standard revisions need no perception request
    assert message.versions_payload()["revision_refresh"] == {
        "scene_id": scene.id,
        "message_id": message.id,
        "selection_index": 1,
        "selection_digest": message.revision_digest(),
        "selection_serial": message.revision_state.serial,
        "required": False,
        "status": "deferred",
        "operations": [],
        "label": None,
        "explanation": None,
        "running_label": None,
        "deferred_hint": None,
    }


@pytest.mark.asyncio
async def test_old_commit_does_not_analyze_new_selection(browsing):
    _, _, request, message, plugin, frames = browsing
    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    await (
        await plugin.handle_commit_revision(
            {"id": message.id, "index": 1, "request_id": "old"}
        )
    )
    request.assert_not_awaited()
    assert any(f.get("request_id") == "old" and f.get("error") for f in frames)


@pytest.mark.asyncio
async def test_same_index_edit_during_commit_never_publishes_old_success(
    browsing, monkeypatch
):
    scene, summarizer, request, message, _, _ = browsing
    with defer_revision_work():
        message.set_active_version(0)
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        started.set()
        await release.wait()
        return result()

    request.side_effect = extract
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    frames = []
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))
    task = await plugin.handle_commit_revision(
        {
            "id": message.id,
            "index": message.active_version,
            "request_id": "old-selection",
            "scene_id": scene.id,
            "selection_digest": message.revision_digest(),
            "selection_serial": message.revision_state.serial,
        }
    )
    await started.wait()
    message.message = "Alice: The key is bronze."
    release.set()
    with pytest.raises(GenerationCancelled):
        await task

    assert not any(frame.get("action") == "revision_committed" for frame in frames)
    assert message.revision_state.status != "clean"


@pytest.mark.asyncio
@pytest.mark.parametrize("reload", [False, True])
async def test_regeneration_restores_ready_perception_baseline_and_dependents(
    browsing, reload, monkeypatch
):
    scene, _, request, message, _, _ = browsing
    dependent = NarratorMessage(message="A listener remembers the bell.")
    dependent._knowledge_scene = weakref.ref(scene)
    dependent.knowledge = SourcePerspectives(
        content_digest=content_digest(dependent.perception_text),
        acquired=message.knowledge.acquired,
        views=(
            PerspectiveView(
                audience=("Bob",),
                status="ready",
                text="Bob remembers the earlier bell.",
                sources=(source_reference(scene, "message", message.id),),
            ),
        ),
    )
    scene.history.append(dependent)
    baseline = message.active_version
    baseline_knowledge = message.knowledge.model_dump(mode="json")
    dependent_baseline = dependent.knowledge.model_dump(mode="json")
    message.append_version("A newly regenerated bell passage.", "regenerate")
    assert all(view.status == "pending" for view in message.knowledge.views)
    assert dependent.knowledge.views[0].status == "pending"
    assert message.revision_state.refresh_journal["writes"]["perspectives"]

    if reload:
        message = NarratorMessage.model_validate(message.model_dump(mode="json"))
        dependent = NarratorMessage.model_validate(dependent.model_dump(mode="json"))
        message._knowledge_scene = weakref.ref(scene)
        dependent._knowledge_scene = weakref.ref(scene)
        scene.history = [message, dependent]

    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    await plugin.handle_swap_revision({"id": message.id, "index": baseline})

    assert message.knowledge.model_dump(mode="json") == baseline_knowledge
    assert dependent.knowledge.model_dump(mode="json") == dependent_baseline
    assert all(view.status == "ready" for view in message.knowledge.views)
    assert message.revision_matches_baseline
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_rejected_swap_correlates_its_terminal_error(browsing, missing):
    _, _, request, message, plugin, frames = browsing
    await plugin.handle_swap_revision(
        {
            "id": 999999 if missing else message.id,
            "index": 999,
            "request_id": "rejected-swap",
        }
    )
    failures = [frame for frame in frames if frame.get("error")]
    assert len(failures) == 1
    assert failures[0]["request_id"] == "rejected-swap"
    assert failures[0]["failed_action"] == "swap_revision"
    assert message.active_version == 5
    request.assert_not_awaited()


def standard_revision(scene, *, prior=None):
    """
    A revised line inside base entry A1. `prior` is a
    message placed before it inside the same entry; it must be known before
    the revision starts, since the transaction journal baselines the entry.
    """
    scene.knowledge_eligibility = "legacy"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    summarizer = get_agent("summarizer")
    conversation = get_agent("conversation")
    conversation.write_enabled("character_knowledge", True)
    message = CharacterMessage(
        message="Alice: The key is brass.", present=["Alice", "Bob"]
    )
    message._knowledge_scene = weakref.ref(scene)
    if prior is not None:
        scene.history.append(prior)
    scene.history.append(message)
    index = scene.message_index(message.id)
    scene.archived_history.append(
        {
            "id": "A1",
            "text": "The key is brass.",
            "start": index - (1 if prior is not None else 0),
            "end": index,
            "ts": 0,
        }
    )
    message.append_version("Alice: The key is silver.", "revision")
    return summarizer, conversation, message


@pytest.mark.parametrize(
    "text,hidden",
    [("Alice:   ", False), ("Alice: hidden fact", True)],
)
def test_empty_or_hidden_standard_revision_is_not_actionable(scene, text, hidden):
    _, _, message = standard_revision(scene)
    message.message = text
    if hidden:
        message.hide()

    assert not revision_operations(scene, message).any
    assert message.versions_payload()["revision_refresh"]["required"] is False


@pytest.mark.asyncio
async def test_standard_refresh_prunes_stale_archive_closure_without_model_work(
    scene, monkeypatch
):
    summarizer, conversation, message = standard_revision(scene)
    scene.archived_history = [
        {"id": "A1", "text": "The key is brass.", "start": 0, "end": 0, "ts": 0}
    ]
    summarize = AsyncMock()
    monkeypatch.setattr(summarizer, "summarize", summarize)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    memory = get_agent("memory")
    delete = AsyncMock()
    monkeypatch.setattr(memory, "delete", delete)

    document = SimpleNamespace(id="A1", meta={"typ": "history"})
    assert not RevisionCurrency.from_scene(scene).document_current(document)
    await refresh_revision(scene, message)

    assert scene.archived_history == []
    assert any(call.args[0] == {"ids": ["A1"]} for call in delete.await_args_list)
    summarize.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_archive_vector_cleanup_restores_record_and_vector(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene)
    original = {
        "id": "A1",
        "text": "The key is brass.",
        "start": 0,
        "end": 0,
        "ts": 3,
    }
    scene.archived_history = [original.copy()]
    memory = get_agent("memory")
    monkeypatch.setattr(
        memory, "delete", AsyncMock(side_effect=RuntimeError("vector delete failed"))
    )
    restored = AsyncMock()
    monkeypatch.setattr(memory, "add", restored)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(RuntimeError, match="vector delete failed"):
        await refresh_revision(scene, message)

    assert scene.archived_history == [original]
    restored.assert_awaited_once()
    assert restored.await_args.kwargs["uid"] == "A1"
    assert restored.await_args.kwargs["typ"] == "history"


@pytest.mark.asyncio
async def test_coordinated_perception_emits_one_running_and_terminal_ready(
    browsing, monkeypatch
):
    scene, _, request, message, plugin, _ = browsing
    statuses = []

    def status(_, source, state):
        statuses.append((source.id, state))

    monkeypatch.setattr(
        "talemate.agents.summarize.perceptions.emit_perception_status", status
    )
    monkeypatch.setattr("talemate.knowledge.readiness.emit_perception_status", status)
    request.return_value = result()
    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    await refresh_revision(scene, message)

    own = [state for identity, state in statuses if identity == message.id]
    assert own == ["running", "ready"]


@pytest.mark.asyncio
async def test_same_index_edit_during_final_save_keeps_newer_revision_state(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene)
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(return_value=("summary", []))
    )
    saves = 0

    async def save():
        nonlocal saves
        saves += 1
        if saves == 2:
            message.message = "Alice: The key is bronze."

    monkeypatch.setattr(scene, "attempt_auto_save", save)
    old_serial = message.revision_state.serial

    with pytest.raises(GenerationCancelled):
        await refresh_revision(scene, message)

    assert message.message == "Alice: The key is bronze."
    assert message.revision_state.serial == old_serial + 1
    assert message.revision_state.status == "deferred"


@pytest.mark.asyncio
async def test_direct_narration_waits_for_revision_refresh_before_generation(
    scene, monkeypatch
):
    narrator = get_agent("narrator")
    narrator.scene = scene
    generated = AsyncMock()
    catch_up = AsyncMock(side_effect=GenerationCancelled("refresh failed"))
    monkeypatch.setattr("talemate.knowledge.step.catch_up_revisions", catch_up)

    with pytest.raises(GenerationCancelled, match="refresh failed"):
        await _narration(narrator, generated, (), {})

    catch_up.assert_awaited_once_with(scene)
    generated.assert_not_awaited()


async def test_deferred_index_repair_failure_remains_retryable(scene, monkeypatch):
    scene.knowledge_eligibility = "legacy"
    message = NarratorMessage(message="The bell rings.")
    scene.history = [message]
    message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(archive_ids=["base:A1"])
    )
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "delete", AsyncMock(return_value=False))

    await refresh_revision(scene, message)

    assert message.revision_state.pending_index_repair.archive_ids == ["base:A1"]
    scene.attempt_auto_save.assert_not_awaited()
    memory.delete.return_value = True
    await refresh_revision(scene, message)
    assert message.revision_state.pending_index_repair is None
    scene.attempt_auto_save.assert_awaited_once()


async def test_perspectives_repair_only_payload_does_not_offer_analysis(browsing):
    scene, _, request, message, _, _ = browsing
    message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(archive_ids=["base:A1"])
    )

    payload = revision_refresh_payload(scene, message)["revision_refresh"]

    assert payload["required"] is True
    assert payload["operations"] == ["index_repair"]
    assert payload["label"] == "Update knowledge"
    assert payload["running_label"] == "Updating knowledge…"
    assert "restored" in payload["explanation"]
    request.assert_not_awaited()


async def test_restored_archive_repair_ignores_unrelated_backlog(scene, monkeypatch):
    message = NarratorMessage(message="The bell rings.")
    scene.history = [message]
    message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(archive_ids=["base:A1"])
    )
    _archive_vector_repairs[scene] = {"base:unrelated"}
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "delete", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    await refresh_revision(scene, message)

    memory.delete.assert_awaited_once_with({"ids": ["A1"]})
    assert _archive_vector_repairs[scene] == {"base:unrelated"}
    assert message.revision_state.pending_index_repair is None


@pytest.mark.parametrize("failure", [False, RuntimeError("memory unavailable")])
async def test_failed_repair_does_not_block_successive_sends(
    scene, monkeypatch, failure
):
    message = NarratorMessage(message="The bell rings.")
    scene.history = [message]
    message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(archive_ids=["base:A1"])
    )
    memory = get_agent("memory")
    delete = AsyncMock(
        side_effect=failure if isinstance(failure, Exception) else None,
        return_value=failure,
    )
    monkeypatch.setattr(memory, "delete", delete)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    request = AsyncMock(side_effect=AssertionError("Repair must not request analysis"))
    monkeypatch.setattr(Prompt, "request", request)

    for text in ("The keeper waves.", "A ship passes."):
        next_message = NarratorMessage(message=text)
        await push_and_step(scene, next_message)
        assert next_message in scene.history
        assert message.revision_state.pending_index_repair is not None

    assert delete.await_count == 2
    request.assert_not_awaited()


async def test_explicit_failed_index_repair_reports_error_and_can_retry(
    scene, monkeypatch
):
    message = NarratorMessage(message="The bell rings.")
    scene.history = [message]
    scene.saved = False
    message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(archive_ids=["base:A1"])
    )
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "delete", AsyncMock(return_value=False))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    frames = []
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=frames.append))

    await (
        await plugin.handle_commit_revision(
            {"id": message.id, "index": 0, "request_id": "repair"}
        )
    )

    assert frames == [
        {
            "type": "scene_message",
            "action": "operation_done",
            "error": {
                "message": "Knowledge could not be updated. You can retry or continue the story."
            },
            "request_id": "repair",
            "failed_action": "commit_revision",
        }
    ]
    assert message.revision_state.pending_index_repair is not None
    assert scene.saved is False
    scene.attempt_auto_save.assert_not_awaited()

    memory.delete.return_value = True
    await (
        await plugin.handle_commit_revision(
            {"id": message.id, "index": 0, "request_id": "retry"}
        )
    )
    assert message.revision_state.pending_index_repair is None
    assert any(
        frame.get("action") == "revision_committed"
        and frame.get("request_id") == "retry"
        for frame in frames
    )


async def test_send_deletes_empty_archive_vector_and_finishes_repair(
    scene, monkeypatch
):
    message = NarratorMessage(message="The bell rings.")
    scene.history = [message]
    scene.archived_history = [{"id": "A1", "text": "", "start": 0, "end": 0, "ts": 0}]
    message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(archive_ids=["base:A1"])
    )
    memory = get_agent("memory")
    monkeypatch.setattr(
        memory, "add", AsyncMock(side_effect=AssertionError("Empty text"))
    )
    monkeypatch.setattr(memory, "delete", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    next_message = NarratorMessage(message="The keeper waves.")

    await push_and_step(scene, next_message)

    memory.add.assert_not_awaited()
    memory.delete.assert_awaited_once_with({"ids": ["A1"]})
    assert message.revision_state.pending_index_repair is None
    assert scene.history[-1] is next_message


async def test_pending_index_repair_survives_scene_file_reload(
    persistence_scene_factory,
):
    scene = persistence_scene_factory()
    scene.name = "Pending repair"
    scene.project_name = "pending-repair"
    message = NarratorMessage(message="The bell rings.")
    message.set_revision_status(
        "clean",
        pending_index_repair=RevisionIndexRepair(archive_ids=["base:A1"]),
    )
    scene.history = [message]
    await scene.save(copy_name="repair.json")
    path = Path(scene.full_path)
    saved = json.loads(path.read_text())

    reloaded = persistence_scene_factory()
    await load_scene_from_data(reloaded, saved, name=str(path))

    repair = reloaded.history[0].revision_state.pending_index_repair
    assert repair.archive_ids == ["base:A1"]
    assert reloaded.revision_refreshes[0]["revision_refresh"]["required"]
    await refresh_revision(reloaded, reloaded.history[0])
    assert reloaded.history[0].revision_state.pending_index_repair is None


async def test_pending_index_repair_rejects_selection_changes(scene, monkeypatch):
    message = NarratorMessage(message="The bell rings.")
    message.append_version("The bell rings twice.", "regenerate")
    message._knowledge_scene = weakref.ref(scene)
    scene.history = [message]
    message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(archive_ids=["base:A1"])
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def delete(*args, **kwargs):
        started.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        return True

    memory = get_agent("memory")
    monkeypatch.setattr(memory, "delete", AsyncMock(side_effect=delete))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    step = asyncio.create_task(knowledge_step(scene))
    await asyncio.wait_for(started.wait(), timeout=5)
    try:
        with defer_revision_work():
            message.set_active_version(0)
    finally:
        release.set()
    with pytest.raises(GenerationCancelled):
        await step
    memory.delete.assert_awaited_once()
    assert message.revision_state.pending_index_repair is not None
    await refresh_revision(scene, message)
    assert message.revision_state.pending_index_repair is None


@pytest.mark.asyncio
@pytest.mark.parametrize("affected_index", [0, 1])
async def test_archive_rollback_restores_position_and_dependent_layers(
    scene, monkeypatch, affected_index
):
    summarizer, _, message = standard_revision(scene)
    before = NarratorMessage(message="Before passage")
    after = NarratorMessage(message="After passage")
    scene.history = [before, message, after]
    message_index = scene.history.index(message)
    records = [
        {"id": "A1", "text": "First", "start": 0, "end": 0, "ts": 1},
        {
            "id": "A2",
            "text": "Middle",
            "start": message_index,
            "end": message_index,
            "ts": 2,
        },
        {"id": "A3", "text": "Last", "start": 2, "end": 2, "ts": 3},
    ]
    if affected_index == 0:
        records[0]["start"] = message_index
        records[0]["end"] = message_index
        records[1]["start"] = 0
        records[1]["end"] = 0
    scene.archived_history = [record.copy() for record in records]
    layers = [
        {"id": "L1", "text": "First two", "start": 0, "end": 1, "ts": 4},
        {"id": "L2", "text": "Last", "start": 2, "end": 2, "ts": 5},
    ]
    scene.layered_history = [[record.copy() for record in layers]]
    memory = get_agent("memory")

    async def fail_delete(*args, **kwargs):
        scene.archived_history[-1]["text"] = "Concurrent neighbor edit"
        raise RuntimeError("vector delete failed")

    monkeypatch.setattr(memory, "delete", fail_delete)
    monkeypatch.setattr(memory, "add", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(RuntimeError, match="vector delete failed"):
        await refresh_revision(scene, message)

    assert [record["id"] for record in scene.archived_history] == ["A1", "A2", "A3"]
    assert scene.archived_history[-1]["text"] == "Concurrent neighbor edit"
    assert [record["id"] for record in scene.layered_history[0]] == ["L1", "L2"]
    assert [
        (record["start"], record["end"]) for record in scene.layered_history[0]
    ] == [(0, 1), (2, 2)]
