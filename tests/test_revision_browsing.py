import asyncio
import json
from pathlib import Path
import weakref
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import test_perception_lifecycle
import talemate.emit.async_signals as async_signals
from test_perception_lifecycle import result
from talemate.exceptions import GenerationCancelled
from talemate.character import Character
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.perspective_models import (
    PerspectiveView,
    SourcePerspectives,
    content_digest,
)
from talemate.knowledge.perspectives import select_character_view, source_reference
from talemate.knowledge.revision_browsing import (
    current_facts,
    defer_revision_work,
    memory_document_current,
)
from talemate.knowledge.message_facts import prune_missing_message_facts
from talemate.knowledge.revision_refresh import (
    _remove_message_evidence,
    _archive_vector_repairs,
    revision_refresh_payload,
    catch_up_revisions,
    refresh_revision,
    revision_operations,
)
from talemate.knowledge.facts import SpanLine, store_facts
from talemate.knowledge.schema import (
    FactRestatement,
    Fact,
    KnowledgeEdge,
    ParsedFact,
)
from talemate.instance import get_agent
from talemate.scene_message import CharacterMessage, RevisionIndexRepair
from talemate.knowledge.topics import known_bucket
from talemate.scene_message import NarratorMessage
from talemate.server.scene_message import SceneMessagePlugin
from talemate.load import load_scene_from_data
from talemate.prompts import Prompt
from talemate.agents.narrator import _narration
from talemate.agents.conversation import knowledge as conversation_knowledge

setup = test_perception_lifecycle.setup


@pytest.fixture
async def browsing(setup, monkeypatch):
    scene, summarizer, request = setup
    message = NarratorMessage(message="The bell rings.")
    for index in range(5):
        message.append_version(f"The bell rings {index + 2} times.", "regenerate")
    await scene.push_history(message)
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
        await summarizer.ensure_perceptions(scene)
        assert analyzed == ["The bell rings."]
    else:
        await scene.push_history(NarratorMessage(message="Alice opens the window."))
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


@pytest.mark.asyncio
async def test_standard_browsing_masks_and_revives_bound_facts_and_grants(
    scene, monkeypatch
):
    _, _, message = standard_revision(scene)
    request = AsyncMock()
    monkeypatch.setattr(Prompt, "request", request)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    baseline = message.revision_state.baseline_index
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=content_digest(message.versions[baseline].message),
        present=["Alice"],
    )
    scene.world_state.facts = {fact.id: fact}
    scene.world_state.knowledge = [
        KnowledgeEdge(
            character="Bob",
            target=fact.id,
            kind="grant",
            source="inferred",
            message_id=message.id,
        )
    ]
    # the selected revision is not the baseline: masked, not removed
    assert current_facts(scene) == []
    assert known_bucket(scene, "Bob") == []
    assert not KnowledgeIndex.from_scene(scene).granted("Bob", fact.id)

    await plugin.handle_swap_revision({"id": message.id, "index": baseline})
    assert message.revision_matches_baseline
    assert current_facts(scene) == [fact]
    assert known_bucket(scene, "Bob") == [fact]
    assert KnowledgeIndex.from_scene(scene).granted("Bob", fact.id)

    await plugin.handle_swap_revision({"id": message.id, "index": 1})
    assert current_facts(scene) == []
    assert fact.id in scene.world_state.facts
    request.assert_not_awaited()


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
    monkeypatch.setattr(get_agent("summarizer"), "flush_fact_memory", forbidden)
    monkeypatch.setattr("talemate.knowledge.revision_refresh.refresh_topics", forbidden)
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


@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize("catch_up", [False, True])
async def test_standard_unrelated_evidence_short_circuits_revision_work(
    scene, monkeypatch, deferred, catch_up
):
    scene.knowledge_eligibility = "legacy"
    previous = NarratorMessage(message="The keeper has a key.")
    message = NarratorMessage(message="The bell rings.")
    scene.history = [previous, message]
    scene.archived_history = [
        {"id": "A9", "text": "The keeper has a key.", "start": 0, "end": 0, "ts": 0}
    ]
    fact = Fact(
        id="F9",
        text="The keeper has a key.",
        archive_id="A9",
        message_id=previous.id,
        message_digest=content_digest(previous.perception_text),
    )
    edge = KnowledgeEdge(
        character="Keeper",
        target="F9",
        kind="grant",
        source="inferred",
        message_id=previous.id,
    )
    scene.world_state.facts = {fact.id: fact}
    scene.world_state.knowledge = [edge]
    message._knowledge_scene = weakref.ref(scene)
    if deferred:
        with defer_revision_work():
            message.append_version("The bell rings twice.", "revision")
        assert message.revision_state.refresh_journal is None
    else:
        message.append_version("The bell rings twice.", "revision")
        assert message.revision_state.refresh_journal is not None
        assert message.revision_state.refresh_journal["mutations"] == []
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    forbidden = AsyncMock(side_effect=AssertionError("No evidence to reconcile"))
    monkeypatch.setattr(get_agent("summarizer"), "flush_fact_memory", forbidden)
    monkeypatch.setattr("talemate.knowledge.revision_refresh.refresh_topics", forbidden)
    monkeypatch.setattr(
        "talemate.knowledge.revision_refresh._record_snapshot",
        Mock(side_effect=AssertionError("Unrelated evidence must not be copied")),
    )

    if catch_up:
        await catch_up_revisions(scene)
    else:
        await refresh_revision(scene, message)

    assert message.revision_matches_baseline
    assert message.revision_state.refresh_journal is None
    scene.attempt_auto_save.assert_awaited_once()
    forbidden.assert_not_called()
    assert scene.world_state.facts == {fact.id: fact}
    assert scene.world_state.knowledge == [edge]


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

    await scene.push_history(message)
    message.append_version("A new silver bell rings.", "regenerate")

    assert message._knowledge_scene() is scene
    # a line outside every archive has no facts to refresh
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
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene)
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        started.set()
        await release.wait()
        return "summary", []

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
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
async def test_browse_retains_dirty_fact_work_without_scheduling(browsing):
    scene, summarizer, _, _, _, _ = browsing
    run = AsyncMock()
    with defer_revision_work():
        summarizer._queue_fact_work(scene, {"F42"}, run)
    await asyncio.sleep(0)
    run.assert_not_awaited()
    assert summarizer._fact_memory_dirty[scene] == {"F42"}
    summarizer._queue_fact_work(scene, set(), run)
    await summarizer._fact_wakeup_tasks[scene]
    run.assert_awaited_once_with(scene)


@pytest.mark.asyncio
async def test_regeneration_keeps_reload_safe_baseline_and_concurrent_manual_work(
    scene, monkeypatch
):
    scene.knowledge_eligibility = "legacy"
    summarizer = get_agent("summarizer")
    summarizer.write_config("archive", "extract_facts", True)
    message = NarratorMessage(message="The brass key turns.")
    message._knowledge_scene = weakref.ref(scene)
    scene.history.append(message)
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=content_digest(message.perception_text),
    )
    scene.world_state.facts[fact.id] = fact
    message.append_version("The silver key turns.", "regenerate")

    assert prune_missing_message_facts(scene) == set()
    assert fact.id in scene.world_state.facts
    fact.text = "The author says the key was brass."
    fact.text_edited = True
    manual = KnowledgeEdge(character="Bob", target=fact.id, source="manual")
    scene.world_state.knowledge.append(manual)
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    await plugin.handle_swap_revision({"id": message.id, "index": 0})

    assert scene.world_state.facts[fact.id].text == fact.text
    assert manual in scene.world_state.knowledge
    assert message.revision_matches_baseline


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
async def test_reload_mid_browse_preserves_and_restores_baseline_fact(
    scene, monkeypatch
):
    scene.knowledge_eligibility = "legacy"
    summarizer = get_agent("summarizer")
    summarizer.write_config("archive", "extract_facts", True)
    message = NarratorMessage(message="The brass key turns.")
    message._knowledge_scene = weakref.ref(scene)
    scene.history.append(message)
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=content_digest(message.perception_text),
    )
    scene.world_state.facts[fact.id] = fact
    message.append_version("The silver key turns.", "regenerate")

    loaded = NarratorMessage.model_validate(message.model_dump(mode="json"))
    loaded._knowledge_scene = weakref.ref(scene)
    scene.history = [loaded]
    scene.world_state.facts = {
        fact.id: Fact.model_validate(fact.model_dump(mode="json"))
    }

    assert prune_missing_message_facts(scene) == set()
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    await plugin.handle_swap_revision({"id": loaded.id, "index": 0})

    assert scene.world_state.facts[fact.id].text == fact.text
    assert loaded.revision_matches_baseline


def test_removing_one_dialogue_support_preserves_other_support_and_manual_grant(scene):
    message = CharacterMessage(message="Alice: The key is brass.")
    scene.history.append(message)
    other = CharacterMessage(message="Bob: The key is brass.")
    scene.history.append(other)
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=content_digest(message.perception_text),
        restatements=1,
        restated_by=(
            FactRestatement(
                message_id=message.id,
                message_digest=content_digest(message.perception_text),
            ),
            FactRestatement(
                message_id=other.id,
                message_digest=content_digest(other.perception_text),
            ),
        ),
    )
    manual = KnowledgeEdge(character="Mara", target=fact.id, source="manual")
    scene.world_state.facts[fact.id] = fact
    scene.world_state.knowledge.append(manual)

    # the promoted fact is not removed, but its document must follow
    assert _remove_message_evidence(scene, message, facts=True) == {fact.id}
    assert scene.world_state.facts[fact.id].message_id == other.id
    assert scene.world_state.facts[fact.id].restatements == 0
    assert scene.world_state.knowledge == [manual]


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


def standard_revision(scene, *, ledger=False, extraction=True, prior=None):
    """
    A revised line inside base entry A1, where facts come from. `prior` is a
    message placed before it inside the same entry; it must be known before
    the revision starts, since the transaction journal baselines the entry.
    """
    scene.knowledge_eligibility = "legacy"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    summarizer = get_agent("summarizer")
    conversation = get_agent("conversation")
    summarizer.write_enabled("archive", extraction)
    summarizer.write_config("archive", "extract_facts", extraction)
    conversation.write_enabled("character_knowledge", ledger)
    conversation.write_config("character_knowledge", "ledger", ledger)
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


def test_scene_status_names_the_archive_entries_of_a_required_refresh(scene):
    summarizer, _, message = standard_revision(scene)
    (item,) = scene.revision_refreshes
    assert item["archive_ids"] == ["A1"]
    summarizer.write_config("archive", "extract_facts", False)
    (item,) = scene.revision_refreshes
    assert item["revision_refresh"]["required"] is False
    assert "archive_ids" not in item


def test_payload_names_only_the_owed_learning_step(scene, monkeypatch):
    import talemate.knowledge.revision_refresh as revision_refresh

    _, _, message = standard_revision(scene, ledger=True)
    identity = revision_refresh._phase_identity(scene, message, "extract")

    def no_hashing(*args, **kwargs):
        raise AssertionError("the status payload hashes the fact inputs")

    monkeypatch.setattr(revision_refresh, "_phase_identity", no_hashing)
    refresh = revision_refresh_payload(scene, message)["revision_refresh"]
    assert (refresh["operations"], refresh["label"]) == (
        ["facts", "learning"],
        "Refresh facts",
    )
    # a refresh that failed after its extraction may extract again
    message.set_revision_status("failed", phase_receipts={"refresh:extract": identity})
    refresh = revision_refresh_payload(scene, message)["revision_refresh"]
    assert refresh["operations"] == ["facts", "learning"]
    # a full history rebuild extracted the selected text
    message.mark_revision_committed(("facts",))
    message.set_revision_status(
        "deferred",
        phase_receipts={"refresh:extract": f"rebuild:{message.revision_digest()}"},
    )
    refresh = revision_refresh_payload(scene, message)["revision_refresh"]
    assert refresh["required"] is True
    assert refresh["operations"] == ["learning"]
    assert refresh["label"] == "Learn from dialogue"
    assert refresh["explanation"] == (
        "Learning from dialogue for this version has not run yet."
    )


def test_a_line_outside_every_chapter_owes_only_learning(scene):
    _, _, message = standard_revision(scene, ledger=True)
    scene.archived_history = []
    refresh = revision_refresh_payload(scene, message)["revision_refresh"]
    assert refresh["required"] is True
    assert (refresh["operations"], refresh["label"]) == (
        ["learning"],
        "Learn from dialogue",
    )


def test_scene_status_refresh_tracks_effective_setting_changes(scene):
    summarizer, _, message = standard_revision(scene)
    assert scene.revision_refreshes[0]["revision_refresh"]["operations"] == ["facts"]
    assert scene.revision_refreshes[0]["revision_refresh"]["required"] is True

    summarizer.write_config("archive", "extract_facts", False)

    assert scene.revision_refreshes[0]["revision_refresh"]["operations"] == []
    assert scene.revision_refreshes[0]["revision_refresh"]["required"] is False
    assert not message.revision_matches_baseline


@pytest.mark.asyncio
async def test_standard_refresh_extracts_selected_passage_with_historical_presence(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene)
    summarize = AsyncMock(
        return_value=(
            "The key is silver.",
            [
                ParsedFact(
                    text="Alice says the key is silver.",
                    importance=2,
                    message_id=message.id,
                )
            ],
        )
    )
    monkeypatch.setattr(summarizer, "summarize", summarize)
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        memory,
        "compare_string_lists",
        AsyncMock(return_value={"distance_matches": []}),
    )
    monkeypatch.setattr(memory, "add_many", AsyncMock())
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    payload = await refresh_revision(scene, message)

    summarize.assert_awaited_once()
    assert summarize.await_args.args[0] == f"[{message.id}] Alice: The key is silver."
    assert summarize.await_args.kwargs["extra_context"] == []
    assert summarize.await_args.kwargs["line_ids"] is True
    assert scene.archived_history[0]["text"] == "The key is silver."
    facts = [
        fact
        for fact in scene.world_state.facts.values()
        if fact.message_id == message.id
    ]
    assert len(facts) == 1
    assert facts[0].present == ["Alice", "Bob"]
    assert facts[0].message_digest == content_digest(message.perception_text)
    assert facts[0] in current_facts(scene)
    assert message.revision_matches_baseline
    assert payload["revision_refresh"]["required"] is False


@pytest.mark.asyncio
async def test_concurrent_standard_refresh_callers_share_one_job(scene, monkeypatch):
    summarizer, _, message = standard_revision(scene)
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        started.set()
        await release.wait()
        return "summary", []

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    first = asyncio.create_task(refresh_revision(scene, message))
    await started.wait()
    second = asyncio.create_task(catch_up_revisions(scene))
    release.set()
    await asyncio.gather(first, second)

    summarizer.summarize.assert_awaited_once()
    assert message.revision_matches_baseline


@pytest.mark.asyncio
async def test_partial_standard_retry_resumes_after_extraction(scene, monkeypatch):
    summarizer, conversation, message = standard_revision(scene, ledger=True)
    operations = revision_operations(scene, message)
    assert operations.learn_facts, (
        conversation.enabled,
        conversation.resolve_enabled("character_knowledge"),
        conversation.resolve_config("character_knowledge", "ledger"),
        scene.knowledge_eligibility,
    )
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(return_value=("summary", [])),
    )
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    learning = AsyncMock(side_effect=[RuntimeError("learning failed"), {}])
    monkeypatch.setattr(conversation, "record_learned_facts", learning)

    with pytest.raises(RuntimeError, match="learning failed"):
        await refresh_revision(scene, message)
    assert message.revision_state.status == "failed"
    await refresh_revision(scene, message)

    summarizer.summarize.assert_awaited_once()
    assert learning.await_count == 2
    assert message.revision_matches_baseline


@pytest.mark.asyncio
async def test_disabling_failed_learning_reuses_successful_extraction(
    scene, monkeypatch
):
    summarizer, conversation, message = standard_revision(scene, ledger=True)
    extract = AsyncMock(return_value=("summary", []))
    learn = AsyncMock(side_effect=RuntimeError("learning failed"))
    monkeypatch.setattr(summarizer, "summarize", extract)
    monkeypatch.setattr(conversation, "record_learned_facts", learn)
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(RuntimeError, match="learning failed"):
        await refresh_revision(scene, message)
    conversation.write_config("character_knowledge", "ledger", False)
    await refresh_revision(scene, message)

    extract.assert_awaited_once()
    learn.assert_awaited_once()
    assert message.revision_matches_baseline


@pytest.mark.asyncio
async def test_dependency_edit_invalidates_successful_extraction_receipt(
    scene, monkeypatch
):
    prior = NarratorMessage(message="The key was brass.")
    summarizer, conversation, message = standard_revision(
        scene, ledger=True, prior=prior
    )
    extract = AsyncMock(return_value=("summary", []))
    learn = AsyncMock(side_effect=[RuntimeError("learning failed"), {}])
    monkeypatch.setattr(summarizer, "summarize", extract)
    monkeypatch.setattr(conversation, "record_learned_facts", learn)
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(RuntimeError, match="learning failed"):
        await refresh_revision(scene, message)
    prior.message = "The key was copper."
    await refresh_revision(scene, message)

    assert extract.await_count == 2
    assert learn.await_count == 2


@pytest.mark.asyncio
async def test_disabled_standard_features_finalize_without_requests(scene, monkeypatch):
    summarizer, conversation, message = standard_revision(
        scene, ledger=False, extraction=False
    )
    extract = AsyncMock()
    learn = AsyncMock()
    monkeypatch.setattr(summarizer, "summarize", extract)
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(conversation, "record_learned_facts", learn)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    assert not revision_operations(scene, message).any
    await refresh_revision(scene, message)

    extract.assert_not_awaited()
    learn.assert_not_awaited()
    assert message.revision_matches_baseline


@pytest.mark.asyncio
async def test_disabled_refresh_prunes_stale_archive_closure_without_model_work(
    scene, monkeypatch
):
    summarizer, conversation, message = standard_revision(
        scene, ledger=False, extraction=False
    )
    scene.archived_history = [
        {"id": "A1", "text": "The key is brass.", "start": 0, "end": 0, "ts": 0}
    ]
    fact = Fact(id="F1", text="The key is brass.", archive_id="A1")
    scene.world_state.facts[fact.id] = fact
    extract = AsyncMock()
    learn = AsyncMock()
    monkeypatch.setattr(summarizer, "summarize", extract)
    monkeypatch.setattr(conversation, "record_learned_facts", learn)
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    memory = get_agent("memory")
    delete = AsyncMock()
    monkeypatch.setattr(memory, "delete", delete)

    assert current_facts(scene) == []
    document = SimpleNamespace(id="A1", meta={"typ": "history"})
    assert not memory_document_current(scene, document)
    await refresh_revision(scene, message)

    assert scene.archived_history == []
    assert fact.id not in scene.world_state.facts
    assert any(call.args[0] == {"ids": ["A1"]} for call in delete.await_args_list)
    extract.assert_not_awaited()
    learn.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_archive_vector_cleanup_restores_record_and_vector(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene, ledger=False, extraction=False)
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
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(RuntimeError, match="vector delete failed"):
        await refresh_revision(scene, message)

    assert scene.archived_history == [original]
    restored.assert_awaited_once()
    assert restored.await_args.kwargs["uid"] == "A1"
    assert restored.await_args.kwargs["typ"] == "history"


@pytest.mark.asyncio
async def test_standard_refresh_rebuilds_affected_archive_and_replaces_its_facts(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene)
    scene.archived_history = [
        {"id": "A1", "text": "The key is brass.", "start": 0, "end": 0, "ts": 0}
    ]
    old = Fact(id="F1", text="The key is brass.", archive_id="A1")
    scene.world_state.facts[old.id] = old
    summarize = AsyncMock(
        return_value=(
            "The key is silver.",
            [ParsedFact(text="The key is silver.", message_id=message.id)],
        )
    )
    monkeypatch.setattr(summarizer, "summarize", summarize)
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    monkeypatch.setattr(memory, "add_many", AsyncMock())
    monkeypatch.setattr(memory, "delete", AsyncMock())
    monkeypatch.setattr(
        memory,
        "compare_string_lists",
        AsyncMock(return_value={"distance_matches": []}),
    )
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    await refresh_revision(scene, message)

    summarize.assert_awaited_once()
    assert scene.archived_history[0]["text"] == "The key is silver."
    refreshed = next(iter(scene.world_state.facts.values()))
    assert refreshed.archive_id == "A1"
    assert refreshed.text == "The key is silver."


@pytest.mark.asyncio
async def test_scene_switch_during_extraction_rolls_back_and_does_not_commit(
    scene, monkeypatch
):
    summarizer, conversation, message = standard_revision(scene)
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=content_digest(message.versions[0].message),
    )
    scene.world_state.facts[fact.id] = fact
    started = asyncio.Event()
    release = asyncio.Event()

    async def extract(*args, **kwargs):
        started.set()
        await release.wait()
        return "summary", []

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    save = AsyncMock()
    monkeypatch.setattr(scene, "attempt_auto_save", save)
    active = scene.active
    task = asyncio.create_task(refresh_revision(scene, message))
    await started.wait()
    other = type(scene)()
    summarizer.scene = other
    conversation.scene = other
    scene.active = not active
    release.set()

    with pytest.raises(GenerationCancelled):
        await task
    assert fact.id in scene.world_state.facts
    assert not message.revision_matches_baseline
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_extraction_off_keeps_the_lines_facts_bound_to_the_edit(
    scene, monkeypatch
):
    summarizer, conversation, message = standard_revision(
        scene, ledger=True, extraction=False
    )
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=content_digest(message.versions[0].message),
    )
    scene.world_state.facts[fact.id] = fact
    queued = []
    monkeypatch.setattr(
        summarizer, "queue_fact_memory", lambda _, ids: queued.append(set(ids))
    )
    monkeypatch.setattr(
        conversation, "record_learned_facts", AsyncMock(return_value={})
    )
    monkeypatch.setattr(summarizer, "summarize", AsyncMock())
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    assert current_facts(scene) == []
    await refresh_revision(scene, message)

    # nothing re-extracts: the fact stays, bound to the edited text
    summarizer.summarize.assert_not_awaited()
    assert message.revision_matches_baseline
    assert fact.message_digest == content_digest(message.perception_text)
    assert current_facts(scene) == [fact]
    assert queued == [{"F1"}]
    assert scene.archived_history[0]["id"] == "A1"


@pytest.mark.asyncio
async def test_rebind_is_undone_when_the_refresh_rolls_back(scene, monkeypatch):
    summarizer, conversation, message = standard_revision(
        scene, ledger=True, extraction=False
    )
    baseline = content_digest(message.versions[0].message)
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=baseline,
    )
    scene.world_state.facts[fact.id] = fact
    monkeypatch.setattr(
        conversation, "record_learned_facts", AsyncMock(side_effect=RuntimeError("x"))
    )
    monkeypatch.setattr(summarizer, "summarize", AsyncMock())
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(RuntimeError):
        await refresh_revision(scene, message)
    edited = content_digest(message.perception_text)
    assert scene.world_state.facts["F1"].message_digest == edited
    # the learning phase failed and the author returns to the original
    # version: the journal undoes the rebind, so the fact follows the line
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    await plugin.handle_swap_revision(
        {"id": message.id, "index": message.revision_state.baseline_index}
    )
    assert scene.world_state.facts["F1"].message_digest == baseline
    assert [item.id for item in current_facts(scene)] == ["F1"]


@pytest.mark.asyncio
async def test_disabled_refresh_queues_the_fact_its_chapter_prune_promotes(
    scene, monkeypatch
):
    prior = CharacterMessage(message="Bob: The key is brass.", present=["Alice", "Bob"])
    summarizer, _, message = standard_revision(
        scene, ledger=False, extraction=False, prior=prior
    )
    later = CharacterMessage(message="Alice: The key is brass.", present=["Alice"])
    scene.history.append(later)
    index = scene.message_index(later.id)
    scene.archived_history.append(
        {"id": "A2", "text": "Alice repeats it.", "start": index, "end": index, "ts": 0}
    )
    # the edited line is not the origin; a later chapter restated the fact
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=prior.id,
        message_digest=content_digest(prior.perception_text),
        present=["Alice", "Bob"],
        ts=0,
        restatements=1,
        restated_by=(
            FactRestatement(
                message_id=later.id,
                message_digest=content_digest(later.perception_text),
                archive_id="A2",
                present=["Alice"],
                ts=0,
            ),
        ),
    )
    scene.world_state.facts[fact.id] = fact
    queued = []
    monkeypatch.setattr(
        summarizer, "queue_fact_memory", lambda _, ids: queued.append(set(ids))
    )
    monkeypatch.setattr(summarizer, "summarize", AsyncMock())
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    monkeypatch.setattr(get_agent("memory"), "delete", AsyncMock())

    await refresh_revision(scene, message)

    # the chapter prune promoted the later line: the document must follow
    assert [entry["id"] for entry in scene.archived_history] == ["A2"]
    assert (fact.message_id, fact.archive_id, fact.present, fact.restated_by) == (
        later.id,
        "A2",
        ["Alice"],
        (),
    )
    assert queued == [{"F1"}]


@pytest.mark.asyncio
async def test_disabled_refresh_queues_the_fact_it_promotes(scene, monkeypatch):
    summarizer, conversation, message = standard_revision(
        scene, ledger=False, extraction=False
    )
    fact = Fact(
        id="F1",
        text="The key is brass.",
        source="manual",
        restatements=1,
        restated_by=(
            FactRestatement(
                message_id=message.id,
                message_digest=content_digest(message.versions[0].message),
                archive_id="A1",
                present=["Alice", "Bob"],
                ts=0,
            ),
        ),
    )
    scene.world_state.facts[fact.id] = fact
    queued = []
    monkeypatch.setattr(
        summarizer, "queue_fact_memory", lambda _, ids: queued.append(set(ids))
    )
    monkeypatch.setattr(summarizer, "summarize", AsyncMock())
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    monkeypatch.setattr(get_agent("memory"), "delete", AsyncMock())

    await refresh_revision(scene, message)

    # not removed, but changed: its memory document follows
    assert fact.id in scene.world_state.facts
    assert fact.restated_by == () and fact.restatements == 0
    assert queued == [{"F1"}]


@pytest.mark.asyncio
async def test_concurrent_writer_during_learning_is_not_owned_by_revision(
    scene, monkeypatch
):
    summarizer, conversation, message = standard_revision(
        scene, ledger=True, extraction=False
    )
    unrelated = Fact(id="F2", text="Original author text", source="manual")
    scene.world_state.facts[unrelated.id] = unrelated
    owned = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=content_digest(message.versions[0].message),
    )
    scene.world_state.facts[owned.id] = owned
    independent = KnowledgeEdge(character="Bob", target=unrelated.id, source="manual")

    async def learn(*args, **kwargs):
        await asyncio.sleep(0)
        unrelated.text = "Concurrent author text"
        unrelated.text_edited = True
        scene.world_state.knowledge.append(independent)
        _remove_message_evidence(scene, message, facts=True)
        return {}

    monkeypatch.setattr(conversation, "record_learned_facts", learn)
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    baseline = message.revision_state.baseline_index
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))

    with pytest.raises(GenerationCancelled, match="changed"):
        await refresh_revision(scene, message)
    await plugin.handle_swap_revision({"id": message.id, "index": baseline})

    assert scene.world_state.facts[unrelated.id].text == "Concurrent author text"
    assert independent in scene.world_state.knowledge
    assert scene.world_state.facts[owned.id].text == "The key is brass."


@pytest.mark.asyncio
async def test_guarded_duplicate_publication_keeps_each_message_support(
    scene, monkeypatch
):
    first = CharacterMessage(message="Alice: The key is brass.")
    second = CharacterMessage(message="Bob: The key is brass.")
    scene.history = [first, second]
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=first.id,
        message_digest=content_digest(first.perception_text),
    )
    scene.world_state.facts = {fact.id: fact}
    scene.world_state.fact_counter = 1
    memory = get_agent("memory")
    monkeypatch.setattr(
        memory,
        "get",
        AsyncMock(return_value=[SimpleNamespace(id=fact.id)]),
    )
    monkeypatch.setattr(
        memory,
        "compare_strings",
        AsyncMock(return_value={"euclidean_distance": 0}),
    )
    monkeypatch.setattr(memory, "add_many", AsyncMock())
    monkeypatch.setattr(memory, "delete", AsyncMock())

    await store_facts(
        scene,
        "A2",
        [ParsedFact(text="The key is brass.", message_id=second.id)],
        0.1,
        lines={
            second.id: SpanLine(
                message_id=second.id,
                message_digest=content_digest(second.perception_text),
                present=["Alice", "Bob"],
                ts=1,
            )
        },
        still_current=lambda: True,
    )

    assert [support.message_id for support in fact.restated_by] == [second.id]
    assert fact.restatements == 1
    scene.history.remove(first)
    assert prune_missing_message_facts(scene) == set()
    # the restatement becomes the origin once the first line is gone
    assert (fact.message_id, fact.archive_id, fact.restated_by) == (second.id, "A2", ())
    assert current_facts(scene) == [fact]


@pytest.mark.asyncio
async def test_revision_rollback_removes_only_its_duplicate_support(scene, monkeypatch):
    other = CharacterMessage(message="Bob: The key is brass.")
    summarizer, _, message = standard_revision(scene, prior=other)
    baseline_digest = content_digest(message.versions[0].message)
    concurrent_digest = content_digest(other.perception_text)
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=baseline_digest,
        text_edited=True,
    )
    scene.world_state.facts = {fact.id: fact}
    scene.world_state.fact_counter = 1
    memory = get_agent("memory")
    monkeypatch.setattr(
        memory, "get", AsyncMock(return_value=[SimpleNamespace(id=fact.id)])
    )
    monkeypatch.setattr(
        memory,
        "compare_strings",
        AsyncMock(return_value={"euclidean_distance": 0}),
    )

    async def publish_documents(*args, **kwargs):
        live = scene.world_state.facts[fact.id]
        if not any(
            support.message_digest == concurrent_digest for support in live.restated_by
        ):
            live.restated_by = (
                *live.restated_by,
                FactRestatement(message_id=other.id, message_digest=concurrent_digest),
            )
            live.restatements += 1

    monkeypatch.setattr(memory, "add_many", AsyncMock(side_effect=publish_documents))
    monkeypatch.setattr(memory, "delete", AsyncMock())
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            return_value=(
                "summary",
                [ParsedFact(text=fact.text, message_id=message.id)],
            )
        ),
    )
    monkeypatch.setattr(
        summarizer,
        "flush_fact_memory",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(GenerationCancelled, match="changed"):
        await refresh_revision(scene, message)
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    await plugin.handle_swap_revision(
        {"id": message.id, "index": message.revision_state.baseline_index}
    )

    supports = {
        (support.message_id, support.message_digest)
        for support in scene.world_state.facts[fact.id].restated_by
    }
    # the concurrent writer's support stays; the refresh's own is gone
    assert supports == {(other.id, concurrent_digest)}
    assert scene.world_state.facts[fact.id].text == fact.text


@pytest.mark.asyncio
async def test_inflight_dependency_edits_cancel_phase_receipts(scene, monkeypatch):
    prior = NarratorMessage(message="The key was brass.")
    summarizer, conversation, message = standard_revision(
        scene, ledger=True, prior=prior
    )
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        started.set()
        await release.wait()
        return "summary", []

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    monkeypatch.setattr(
        conversation, "record_learned_facts", AsyncMock(return_value={})
    )
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    task = asyncio.create_task(refresh_revision(scene, message))
    await started.wait()
    prior.message = "The key was copper."
    release.set()

    with pytest.raises(GenerationCancelled, match="changed"):
        await task
    assert not message.revision_matches_baseline


@pytest.mark.asyncio
async def test_learning_dependency_change_during_await_cancels_receipt(
    scene, monkeypatch
):
    summarizer, conversation, message = standard_revision(
        scene, ledger=True, extraction=False
    )
    dependency = Fact(id="F9", text="The key was brass.", source="manual")
    scene.world_state.facts[dependency.id] = dependency
    started, release = asyncio.Event(), asyncio.Event()

    async def learn(*args, **kwargs):
        started.set()
        await release.wait()
        return {}

    monkeypatch.setattr(conversation, "record_learned_facts", learn)
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    task = asyncio.create_task(refresh_revision(scene, message))
    await started.wait()
    dependency.text = "The key was copper."
    release.set()

    with pytest.raises(GenerationCancelled, match="changed"):
        await task
    assert "refresh:learn" not in message.revision_state.phase_receipts


@pytest.mark.asyncio
async def test_archive_refresh_scene_switch_has_no_publication(scene, monkeypatch):
    summarizer, conversation, message = standard_revision(scene)
    original = {
        "id": "A1",
        "text": "The key is brass.",
        "start": 0,
        "end": 0,
        "ts": 0,
    }
    scene.archived_history = [original.copy()]
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        started.set()
        await release.wait()
        return "The key is silver.", []

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    task = asyncio.create_task(refresh_revision(scene, message))
    await started.wait()
    other = type(scene)()
    summarizer.scene = other
    conversation.scene = other
    release.set()

    with pytest.raises(GenerationCancelled):
        await task
    assert scene.archived_history == [original]
    assert other.archived_history == []


@pytest.mark.asyncio
async def test_archive_refresh_rejects_changed_live_source_inputs(scene, monkeypatch):
    prior = NarratorMessage(message="The old key was iron.")
    summarizer, _, message = standard_revision(scene, prior=prior)
    original = {
        "id": "A1",
        "text": "The key changed.",
        "start": 0,
        "end": 1,
        "ts": 0,
    }
    scene.archived_history = [original.copy()]
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        started.set()
        await release.wait()
        return "The key is silver.", []

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    task = asyncio.create_task(refresh_revision(scene, message))
    await started.wait()
    prior.message = "The old key was copper."
    release.set()

    with pytest.raises(GenerationCancelled):
        await task
    assert scene.archived_history == [original]
    assert "refresh:extract" not in message.revision_state.phase_receipts


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
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
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
async def test_setting_change_during_extraction_prevents_publication(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene)
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        started.set()
        await release.wait()
        return "summary", [ParsedFact(text="The key is silver.")]

    monkeypatch.setattr(summarizer, "summarize", AsyncMock(side_effect=extract))
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    save = AsyncMock()
    monkeypatch.setattr(scene, "attempt_auto_save", save)
    task = asyncio.create_task(refresh_revision(scene, message))
    await started.wait()
    summarizer.write_config("archive", "extract_facts", False)
    release.set()

    with pytest.raises(GenerationCancelled):
        await task
    assert scene.world_state.facts == {}
    assert not message.revision_matches_baseline
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_narration_waits_for_revision_refresh_before_generation(
    scene, monkeypatch
):
    narrator = get_agent("narrator")
    narrator.scene = scene
    generated = AsyncMock()
    catch_up = AsyncMock(side_effect=GenerationCancelled("refresh failed"))
    monkeypatch.setattr(
        "talemate.knowledge.revision_refresh.catch_up_revisions", catch_up
    )

    with pytest.raises(GenerationCancelled, match="refresh failed"):
        await _narration(narrator, generated, (), {})

    catch_up.assert_awaited_once_with(scene)
    generated.assert_not_awaited()


@pytest.mark.asyncio
async def test_standard_refresh_preserves_authored_fact_and_manual_grant(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene)
    fact = Fact(
        id="F1",
        text="The author's corrected key fact.",
        archive_id="A1",
        message_id=message.id,
        message_digest=message.revision_state.baseline_digest,
        text_edited=True,
    )
    manual = KnowledgeEdge(
        character="Bob",
        target=fact.id,
        source="manual",
        message_id=message.id,
    )
    scene.world_state.facts = {fact.id: fact}
    scene.world_state.knowledge = [manual]
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(return_value=("summary", []))
    )
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    await refresh_revision(scene, message)

    assert scene.world_state.facts["F1"].source == "manual"
    assert scene.world_state.facts["F1"].text_edited is True
    assert scene.world_state.facts["F1"].message_id is None
    assert scene.world_state.knowledge == [manual]
    assert manual.message_id is None


@pytest.mark.asyncio
async def test_failed_standard_refresh_restores_baseline_evidence_on_return(
    scene, monkeypatch
):
    summarizer, conversation, message = standard_revision(scene, ledger=True)
    baseline_index = message.revision_state.baseline_index
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=message.revision_state.baseline_digest,
        present=["Alice", "Bob"],
    )
    scene.world_state.facts = {fact.id: fact}
    scene.world_state.knowledge = [
        KnowledgeEdge(
            character="Bob",
            target=fact.id,
            kind="grant",
            source="inferred",
            message_id=message.id,
        )
    ]
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(return_value=("summary", []))
    )
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(
        conversation,
        "record_learned_facts",
        AsyncMock(side_effect=RuntimeError("failed")),
    )
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))

    with pytest.raises(RuntimeError, match="failed"):
        await refresh_revision(scene, message)
    assert "F1" not in scene.world_state.facts

    await plugin.handle_swap_revision({"id": message.id, "index": baseline_index})

    assert scene.world_state.facts["F1"].text == "The key is brass."
    assert scene.world_state.knowledge[0].message_id == message.id
    assert message.revision_matches_baseline


@pytest.mark.parametrize("auto_save", [True, False])
@pytest.mark.parametrize("reload", [True, False])
async def test_failed_commit_browse_restores_memory_and_defers_indexes(
    scene, monkeypatch, auto_save, reload
):
    summarizer, conversation, message = standard_revision(scene, ledger=True)
    scene.world_state.facts["F1"] = Fact(
        id="F1", text="The key is brass.", archive_id="A1"
    )
    monkeypatch.setattr(scene.config.game.general, "auto_save", auto_save)
    monkeypatch.setattr(scene, "save", AsyncMock())
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(return_value=("The key is silver.", []))
    )
    monkeypatch.setattr(
        conversation,
        "record_learned_facts",
        AsyncMock(side_effect=RuntimeError("learning failed")),
    )
    with pytest.raises(RuntimeError, match="learning failed"):
        await refresh_revision(scene, message)
    await asyncio.sleep(0)
    assert "F1" not in scene.world_state.facts

    memory = get_agent("memory")
    for method in ("add", "add_many", "delete"):
        monkeypatch.setattr(memory, method, AsyncMock(return_value=True))
    topics = AsyncMock(return_value=True)
    monkeypatch.setattr("talemate.knowledge.revision_refresh.refresh_topics", topics)
    flush = AsyncMock(wraps=summarizer.flush_fact_memory)
    monkeypatch.setattr(summarizer, "flush_fact_memory", flush)
    scene.save.reset_mock()
    summarizer.summarize.reset_mock()
    conversation.record_learned_facts.reset_mock()
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))

    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    await asyncio.sleep(0)

    assert scene.world_state.facts["F1"].text == "The key is brass."
    assert scene.archived_history[0]["text"] == "The key is brass."
    scene.save.assert_not_awaited()
    flush.assert_not_awaited()
    topics.assert_not_awaited()
    for method in ("add", "add_many", "delete"):
        getattr(memory, method).assert_not_awaited()
    assert message.revision_state.pending_index_repair.fact_ids == ["F1"]
    assert message.revision_state.pending_index_repair.archive_ids == ["base:A1"]

    if reload:
        message = CharacterMessage.model_validate(message.to_dict())
        message._knowledge_scene = weakref.ref(scene)
        scene.history = [message]
        summarizer._fact_memory_dirty.clear()

    await (await plugin.handle_commit_revision({"id": message.id, "index": 0}))

    assert message.revision_state.pending_index_repair is None
    assert message.revision_matches_baseline
    memory.add.assert_awaited_once()
    assert memory.add.call_args.args == ("The key is brass.",)
    memory.add_many.assert_awaited_once()
    assert memory.add_many.call_args.args[0][0]["id"] == "F1"
    topics.assert_awaited_once()
    summarizer.summarize.assert_not_awaited()
    conversation.record_learned_facts.assert_not_awaited()


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
        await scene.push_history(next_message)
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

    await scene.push_history(next_message)

    memory.add.assert_not_awaited()
    memory.delete.assert_awaited_once_with({"ids": ["A1"]})
    assert message.revision_state.pending_index_repair is None
    assert scene.history[-1] is next_message


async def test_deleted_message_fact_repair_uses_background_queue(scene, monkeypatch):
    message = NarratorMessage(message="The bell rings.")
    scene.history = [message]
    message.set_revision_status(
        "clean", pending_index_repair=RevisionIndexRepair(fact_ids=["F1"])
    )
    summarizer = get_agent("summarizer")
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "delete", AsyncMock(side_effect=[False, True]))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    scene.delete_message(message.id)
    assert summarizer._fact_memory_dirty[scene] == {"F1"}
    await summarizer._fact_wakeup_tasks[scene]
    assert memory.delete.await_count == 1
    await scene.push_history(NarratorMessage(message="The keeper waves."))
    assert summarizer._fact_memory_dirty[scene] == {"F1"}
    assert memory.delete.await_count == 1

    summarizer.queue_fact_memory(scene, {"F1"})
    await summarizer._fact_wakeup_tasks[scene]

    assert summarizer._fact_memory_dirty[scene] == set()
    assert memory.delete.await_count == 2
    assert len(scene.history) == 1


async def test_send_does_not_flush_unrelated_fact_work(scene, monkeypatch):
    summarizer = get_agent("summarizer")
    with defer_revision_work():
        summarizer.queue_fact_memory(scene, {"unrelated"})
    flush = AsyncMock(side_effect=AssertionError("Fact work belongs to its runner"))
    monkeypatch.setattr(summarizer, "flush_fact_memory", flush)

    await scene.push_history(NarratorMessage(message="The keeper waves."))

    flush.assert_not_awaited()
    assert summarizer._fact_memory_dirty[scene] == {"unrelated"}


@pytest.mark.parametrize("remove", ["delete", "pop_object", "pop_id", "pop_history"])
async def test_failed_commit_browse_delete_send_repairs_archive(
    scene, monkeypatch, remove
):
    summarizer, conversation, message = standard_revision(scene, ledger=True)
    scene.world_state.facts["F1"] = Fact(
        id="F1", text="The key is brass.", archive_id="A1"
    )
    vectors = {"A1": "The key is brass."}

    async def add(text, **kwargs):
        vectors[kwargs["uid"]] = text
        return True

    memory = get_agent("memory")
    monkeypatch.setattr(memory, "add", AsyncMock(side_effect=add))
    async_signals.get("archive_add").connect(memory.on_archive_add)
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(return_value=("The key is silver.", []))
    )
    monkeypatch.setattr(
        conversation,
        "record_learned_facts",
        AsyncMock(side_effect=RuntimeError("learning failed")),
    )
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    with pytest.raises(RuntimeError, match="learning failed"):
        await refresh_revision(scene, message)
    assert vectors["A1"] == "The key is silver."
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    await plugin.handle_swap_revision({"id": message.id, "index": 0})
    assert scene.archived_history[0]["text"] == "The key is brass."
    assert vectors["A1"] == "The key is silver."

    if remove == "delete":
        scene.delete_message(message.id)
    elif remove == "pop_object":
        scene.pop_message(message)
    elif remove == "pop_id":
        scene.pop_message(message.id)
    else:
        scene.pop_history("character")
    assert message not in scene.history
    assert _archive_vector_repairs[scene] == {"base:A1"}

    await scene.push_history(NarratorMessage(message="A ship passes."))

    assert vectors["A1"] == "The key is brass."
    assert _archive_vector_repairs[scene] == set()


async def test_pending_index_repair_survives_scene_file_reload(
    persistence_scene_factory,
):
    scene = persistence_scene_factory()
    scene.name = "Pending repair"
    scene.project_name = "pending-repair"
    message = NarratorMessage(message="The bell rings.")
    message.set_revision_status(
        "clean",
        pending_index_repair=RevisionIndexRepair(
            fact_ids=["F1"], archive_ids=["base:A1"]
        ),
    )
    scene.history = [message]
    await scene.save(copy_name="repair.json")
    path = Path(scene.full_path)
    saved = json.loads(path.read_text())

    reloaded = persistence_scene_factory()
    await load_scene_from_data(reloaded, saved, name=str(path))

    repair = reloaded.history[0].revision_state.pending_index_repair
    assert repair.fact_ids == ["F1"]
    assert repair.archive_ids == ["base:A1"]
    assert reloaded.revision_refreshes[0]["revision_refresh"]["required"]
    await refresh_revision(reloaded, reloaded.history[0])
    assert reloaded.history[0].revision_state.pending_index_repair is None


async def test_pending_index_repair_is_shared_and_rejects_selection_changes(
    scene, monkeypatch
):
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
    first = asyncio.create_task(refresh_revision(scene, message))
    second = asyncio.create_task(refresh_revision(scene, message))
    await asyncio.wait_for(started.wait(), timeout=5)
    try:
        with defer_revision_work():
            message.set_active_version(0)
    finally:
        release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert all(isinstance(result, GenerationCancelled) for result in results)
    memory.delete.assert_awaited_once()
    assert message.revision_state.pending_index_repair is not None
    await refresh_revision(scene, message)
    assert message.revision_state.pending_index_repair is None


@pytest.mark.asyncio
async def test_obsolete_rollback_is_consumed_before_original_and_retry(
    scene, monkeypatch
):
    other = CharacterMessage(message="Bob: The key is brass.")
    summarizer, _, message = standard_revision(scene, prior=other)
    baseline_digest = content_digest(message.versions[0].message)
    other_digest = content_digest(other.perception_text)
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=baseline_digest,
        restatements=1,
        restated_by=(
            FactRestatement(message_id=other.id, message_digest=other_digest),
        ),
    )
    scene.world_state.facts = {fact.id: fact}
    calls = 0

    async def extract(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            summarizer.write_config("archive", "extract_facts", False)
        return "summary", []

    monkeypatch.setattr(summarizer, "summarize", extract)
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "add_many", AsyncMock())
    monkeypatch.setattr(memory, "delete", AsyncMock())

    with pytest.raises(GenerationCancelled):
        await refresh_revision(scene, message)
    rolled_back = scene.world_state.facts[fact.id]
    assert len(rolled_back.restated_by) == 1
    assert rolled_back.restatements == 1
    assert rolled_back.message_id == message.id

    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    await plugin.handle_swap_revision(
        {"id": message.id, "index": message.revision_state.baseline_index}
    )
    restored = scene.world_state.facts[fact.id]
    assert len(restored.restated_by) == 1
    assert restored.restatements == 1

    summarizer.write_config("archive", "extract_facts", True)
    await plugin.handle_swap_revision({"id": message.id, "index": 1})
    await refresh_revision(scene, message)
    remaining = scene.world_state.facts[fact.id]
    # the revised line's evidence is gone; the other line's restatement is the origin now
    assert (remaining.message_id, remaining.message_digest) == (other.id, other_digest)
    assert remaining.restated_by == () and remaining.restatements == 0
    assert calls == 2


@pytest.mark.asyncio
async def test_archive_restatement_remains_after_source_line_changes(
    scene, monkeypatch
):
    message = CharacterMessage(message="Alice: The key is brass.")
    other = NarratorMessage(message="The archive independently confirms the brass key.")
    scene.history = [message, other]
    scene.archived_history = [
        {"id": "A0", "text": str(message), "start": 0, "end": 0, "ts": 0},
        {"id": "A1", "text": str(other), "start": 1, "end": 1, "ts": 1},
    ]
    memory = get_agent("memory")

    async def nearby(*args, **kwargs):
        if not scene.world_state.facts:
            return []
        fact = next(iter(scene.world_state.facts.values()))
        return [SimpleNamespace(id=fact.id)]

    monkeypatch.setattr(memory, "get", nearby)
    monkeypatch.setattr(
        memory, "compare_strings", AsyncMock(return_value={"euclidean_distance": 0})
    )
    monkeypatch.setattr(memory, "add_many", AsyncMock())
    monkeypatch.setattr(memory, "delete", AsyncMock())

    def line(item, ts):
        return {
            item.id: SpanLine(
                message_id=item.id,
                message_digest=content_digest(item.perception_text),
                present=["Alice", "Bob"],
                ts=ts,
            )
        }

    await store_facts(
        scene,
        "A0",
        [ParsedFact(text="The key is brass.", message_id=message.id)],
        0.1,
        lines=line(message, 1),
    )
    fact = next(iter(scene.world_state.facts.values()))
    await store_facts(
        scene,
        "A1",
        [ParsedFact(text="The key is brass.", message_id=other.id)],
        0.1,
        lines=line(other, 2),
    )
    assert [(r.message_id, r.archive_id) for r in fact.restated_by] == [
        (other.id, "A1")
    ]

    message.append_version("Alice: The key is silver.", "revision")
    assert current_facts(scene) == []
    # promoted, not removed: the id names a document to refresh
    assert _remove_message_evidence(scene, message, facts=True) == {fact.id}
    assert fact.id in scene.world_state.facts
    assert (fact.message_id, fact.archive_id, fact.restated_by) == (other.id, "A1", ())
    assert current_facts(scene) == [fact]
    scene.history.remove(message)
    assert prune_missing_message_facts(scene) == set()
    assert scene.world_state.facts[fact.id] is fact
    assert current_facts(scene) == [fact]


@pytest.mark.asyncio
@pytest.mark.parametrize("affected_index", [0, 1])
async def test_archive_rollback_restores_position_and_dependent_layers(
    scene, monkeypatch, affected_index
):
    summarizer, _, message = standard_revision(scene, ledger=False, extraction=False)
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
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(RuntimeError, match="vector delete failed"):
        await refresh_revision(scene, message)

    assert [record["id"] for record in scene.archived_history] == ["A1", "A2", "A3"]
    assert scene.archived_history[-1]["text"] == "Concurrent neighbor edit"
    assert [record["id"] for record in scene.layered_history[0]] == ["L1", "L2"]
    assert [
        (record["start"], record["end"]) for record in scene.layered_history[0]
    ] == [(0, 1), (2, 2)]


@pytest.mark.asyncio
async def test_rollback_memory_repair_stays_with_captured_scene(scene, monkeypatch):
    summarizer, conversation, message = standard_revision(scene)
    fact = Fact(
        id="F1",
        text="The key is brass.",
        archive_id="A1",
        message_id=message.id,
        message_digest=content_digest(message.versions[0].message),
        restated_by=(
            FactRestatement(
                message_id=message.id,
                message_digest=content_digest(message.versions[0].message),
            ),
        ),
    )
    scene.world_state.facts = {fact.id: fact}
    other = type(scene)()
    memory = get_agent("memory")
    writes = []

    async def publish(documents):
        writes.append((memory.scene, [document["id"] for document in documents]))

    async def switch(*args, **kwargs):
        summarizer.scene = other
        conversation.scene = other
        memory.scene = other
        return "summary", []

    monkeypatch.setattr(memory, "add_many", publish)
    monkeypatch.setattr(memory, "delete", AsyncMock())
    monkeypatch.setattr(summarizer, "summarize", switch)
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    with pytest.raises(GenerationCancelled):
        await refresh_revision(scene, message)
    assert fact.id in scene.world_state.facts
    assert writes == []
    assert fact.id in message.revision_state.refresh_journal["pending_fact_memory_ids"]
    assert fact.id in summarizer._fact_memory_dirty[scene]

    summarizer.scene = scene
    conversation.scene = scene
    memory.scene = scene
    plugin = SceneMessagePlugin(SimpleNamespace(scene=scene, queue_put=lambda _: None))
    await plugin.handle_swap_revision(
        {"id": message.id, "index": message.revision_state.baseline_index}
    )
    assert writes == []
    assert message.revision_state.pending_index_repair.fact_ids == [fact.id]
    await (await plugin.handle_commit_revision({"id": message.id, "index": 0}))
    assert writes == [(scene, [fact.id])]


@pytest.mark.asyncio
async def test_nonempty_learning_does_not_invalidate_extraction_receipt(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene, ledger=True)
    offered = Fact(id="F1", text="The offered fact.", source="manual")
    scene.world_state.facts = {offered.id: offered}
    extract = AsyncMock(return_value=("summary", []))
    request = AsyncMock(return_value=("", {"ledger": '{"Bob":["F1"]}'}))
    monkeypatch.setattr(summarizer, "summarize", extract)
    monkeypatch.setattr(conversation_knowledge.Prompt, "request", request)
    monkeypatch.setattr(
        conversation_knowledge,
        "absence_facts",
        AsyncMock(return_value=[offered]),
    )
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    monkeypatch.setattr(scene, "attempt_auto_save", AsyncMock())

    await refresh_revision(scene, message)
    await refresh_revision(scene, message)

    assert message.revision_matches_baseline
    assert offered.known_by == {"Bob": "inferred"}
    assert [edge.target for edge in scene.world_state.knowledge] == [offered.id]
    assert extract.await_count == 1
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_persistence_input_edit_retries_extraction_and_nonempty_learning(
    scene, monkeypatch
):
    summarizer, _, message = standard_revision(scene, ledger=True)
    offered = Fact(id="F1", text="The offered fact.", source="manual")
    external = Fact(id="F2", text="External initial.", source="manual")
    scene.world_state.facts = {offered.id: offered, external.id: external}
    extract = AsyncMock(return_value=("summary", []))
    request = AsyncMock(return_value=("", {"ledger": '{"Bob":["F1"]}'}))
    monkeypatch.setattr(summarizer, "summarize", extract)
    monkeypatch.setattr(conversation_knowledge.Prompt, "request", request)
    monkeypatch.setattr(
        conversation_knowledge,
        "absence_facts",
        AsyncMock(return_value=[offered]),
    )
    monkeypatch.setattr(summarizer, "flush_fact_memory", AsyncMock(return_value=True))
    saves = 0

    async def save():
        nonlocal saves
        saves += 1
        if saves == 1:
            external.text = "External edit during persistence."
            external.text_edited = True

    monkeypatch.setattr(scene, "attempt_auto_save", save)

    with pytest.raises(GenerationCancelled, match="persistence"):
        await refresh_revision(scene, message)
    assert not message.revision_matches_baseline
    await refresh_revision(scene, message)

    assert message.revision_matches_baseline
    assert external.text == "External edit during persistence."
    assert offered.known_by == {"Bob": "inferred"}
    assert len(scene.world_state.knowledge) == 1
    assert extract.await_count == 2
    assert request.await_count == 2
