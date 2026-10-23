"""Actual prompt/lifecycle checks; only model transport and memory storage are fakes."""

import asyncio
import json
from collections import deque

import pytest

from conftest import MockScene, bootstrap_scene
from _world_state_helpers import install_tracking_memory
from talemate.context import ActiveScene
from talemate.exceptions import GenerationCancelled
from talemate.export import ExportOptions, scene_export_json
from talemate.instance import get_agent
from talemate.load import load_scene_from_data
from talemate.prompts.base import PrependTemplateDirectories
from talemate.regenerate import regenerate
from talemate.save import scene_data_dumps
from talemate.scene_message import (
    DirectorMessage,
    NarratorMessage,
    ReinforcementMessage,
    TimePassageMessage,
)
from talemate.world_state import Suggestion
from talemate.game.focal.schema import Call
from talemate.world_state.snapshot_revision import SnapshotRevision

pytestmark = pytest.mark.asyncio
BEFORE = "PRE_MESSAGE: intact brass door."
AFTER = "POST_MESSAGE: shattered brass door."


class Transport:
    def __init__(self):
        self.responses = deque()
        self.prompts = []

    async def send(self, prompt, *args, **kwargs):
        self.prompts.append(prompt.prompt)
        assert self.responses, "Unexpected extra model request"
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return await response()
        return response


@pytest.fixture
def setup(monkeypatch):
    scene = MockScene()
    bootstrap_scene(scene)
    install_tracking_memory(scene)
    scene.knowledge_eligibility = "legacy"
    world = get_agent("world_state")
    monkeypatch.setattr(
        world.actions["update_world_state"].config["inject_as_scene_memory"],
        "value",
        True,
    )
    monkeypatch.setattr(get_agent("editor").actions["revision"], "enabled", False)
    transport = Transport()
    monkeypatch.setattr(scene.mock_client, "send_prompt", transport.send)
    scene.history = [NarratorMessage(message="The brass door is shut.")]
    return scene, world, transport


def response(location):
    # The production prompt prefills the opening characters object.
    return '}, "location": ' + json.dumps(location) + "}\n```"


def entity_response(entity):
    return json.dumps(entity)[1:] + "}\n```"


async def snapshot(setup, location):
    scene, _, transport = setup
    transport.responses.append(response(location))
    with ActiveScene(scene):
        await scene.world_state.request_update()
    assert scene.world_state.location == location


def append_target(scene):
    target = NarratorMessage(
        message="The brass door bursts into splinters.",
        meta={"agent": "narrator", "function": "narrate_scene", "arguments": {}},
    )
    scene.history.append(target)
    return target


async def replace(setup, text="The brass door remains closed."):
    scene, _, transport = setup
    transport.responses.append(text)
    with ActiveScene(scene):
        return await regenerate(scene)


@pytest.mark.parametrize("pinned", [True, False])
async def test_incompatible_override_reports_repair_and_default_template_recovers(
    setup, monkeypatch, tmp_path, pinned
):
    scene, world, transport = setup
    monkeypatch.setattr(
        world.actions["update_world_state"].config["inject_as_scene_memory"],
        "value",
        pinned,
    )
    await snapshot(setup, BEFORE)
    statuses = []
    monkeypatch.setattr(
        "talemate.agents.world_state.snapshot.emit",
        lambda typ, message, **kwargs: statuses.append((message, kwargs)),
    )
    override = tmp_path / "request-world-state-v2.jinja2"
    override.write_text(
        "{% set history = scene.context_history(budget=max_tokens) %}\n"
        '{{ history|join("\\n") }}\n'
        '{{ set_data_response(dict(characters={"name":{}}), cutoff=3) }}\n'
    )
    transport.responses.append(response(AFTER))
    with ActiveScene(scene), PrependTemplateDirectories(str(tmp_path)):
        await scene.world_state.request_update()
    assert len(transport.prompts) == 2
    assert scene.world_state.location == BEFORE
    assert len(statuses) == 1
    notice, detail = statuses[0]
    assert detail["status"] == "error"
    assert "world_state/request-world-state-v2.jinja2" in notice
    assert "incompatible" in notice
    assert "Update or reset" in notice and "Prompt Manager" in notice
    statuses.clear()
    await snapshot(setup, AFTER)
    assert scene.world_state.snapshot_provenance.matches(scene)
    assert len(transport.prompts) == 3
    assert not statuses


@pytest.mark.parametrize("reason", ["cancel", "stale"])
async def test_cancelled_or_stale_snapshot_request_stays_quiet(
    setup, monkeypatch, reason
):
    scene, _, transport = setup
    await snapshot(setup, BEFORE)
    statuses = []
    monkeypatch.setattr(
        "talemate.agents.world_state.snapshot.emit",
        lambda *args, **kwargs: statuses.append((args, kwargs)),
    )

    async def interrupted():
        if reason == "cancel":
            raise GenerationCancelled("Cancelled by user", by_user=True)
        scene.history[-1].message = "A different scene input."
        return response(AFTER)

    transport.responses.append(interrupted)
    with ActiveScene(scene):
        await scene.world_state.request_update()
    assert scene.world_state.location == BEFORE
    assert not statuses
    assert len(transport.prompts) == 2


@pytest.mark.parametrize("manual", [False, True])
async def test_history_advancing_during_template_rag_is_the_rollback_source(
    setup, monkeypatch, manual
):
    scene, world, transport = setup
    await snapshot(setup, BEFORE)
    selected = scene.history[-1]
    added = []

    async def rag(**kwargs):
        await asyncio.sleep(0)
        added.append(append_target(scene))
        return []

    monkeypatch.setattr(world, "rag_build", rag)
    if manual:
        transport.responses.append(
            entity_response(
                {
                    "resolved": True,
                    "kind": "item",
                    "name": "Brass door",
                    "snapshot": AFTER,
                    "mentions": ["brass door"],
                }
            )
        )
        with ActiveScene(scene):
            result = await world.add_snapshot_entity(selected.id, "brass door")
        assert result.resolved
    else:
        await snapshot(setup, AFTER)

    assert len(added) == 1
    target = added[0]
    assert target.message in transport.prompts[-1]
    assert scene.world_state.snapshot_provenance.source_message_id == target.id
    assert target.id not in scene.world_state.anchor_message_ids
    assert scene.world_state.previous_snapshot.location == BEFORE
    monkeypatch.setattr(
        world, "rag_build", lambda **kwargs: asyncio.sleep(0, result=[])
    )
    count = len(transport.prompts)
    await replace(setup)
    assert len(transport.prompts) == count + 1
    assert AFTER not in transport.prompts[-1]
    assert scene.world_state.location == BEFORE


@pytest.mark.parametrize("manual", [False, True])
async def test_excluded_director_rotation_does_not_invalidate_request_or_revision(
    setup, monkeypatch, manual
):
    scene, world, transport = setup
    monkeypatch.setattr(world.actions["use_long_term_memory"], "enabled", False)
    control = DirectorMessage(message="DIRECTOR OLD", source="actor:Alice")
    scene.history.append(control)
    await snapshot(setup, BEFORE)
    target = append_target(scene)

    async def rotate():
        scene.history.remove(control)
        scene.history.insert(
            0, DirectorMessage(message="DIRECTOR NEW", source="actor:Alice")
        )
        if manual:
            return entity_response(
                {
                    "resolved": True,
                    "kind": "item",
                    "name": "Brass door",
                    "snapshot": AFTER,
                }
            )
        return response(AFTER)

    transport.responses.append(rotate)
    with ActiveScene(scene):
        if manual:
            assert (await world.add_snapshot_entity(target.id, "brass door")).resolved
        else:
            await scene.world_state.request_update()
            assert scene.world_state.location == AFTER
    assert "DIRECTOR OLD" not in transport.prompts[-1]
    assert "DIRECTOR NEW" not in transport.prompts[-1]
    assert scene.world_state.snapshot_provenance.source_message_id == target.id
    assert scene.world_state.previous_snapshot.location == BEFORE
    await replace(setup)
    assert scene.world_state.location == BEFORE


@pytest.mark.parametrize("change", ["edit", "delete"])
async def test_changes_to_early_inputs_during_rag_do_not_publish(
    setup, monkeypatch, change
):
    scene, world, transport = setup
    await snapshot(setup, BEFORE)
    target = append_target(scene)

    async def rag(**kwargs):
        if change == "edit":
            target.message = "The brass door never broke."
        else:
            scene.history.remove(target)
        return []

    monkeypatch.setattr(world, "rag_build", rag)
    with ActiveScene(scene):
        await scene.world_state.request_update()
    assert scene.world_state.location == BEFORE
    assert len(transport.prompts) == 1


async def test_director_used_by_semantic_rag_remains_a_dependency(setup):
    scene, world, transport = setup
    await snapshot(setup, BEFORE)
    control = DirectorMessage(
        message="Alice must leave the brass door closed.", source="actor:Alice"
    )
    scene.history.append(control)
    assert world.long_term_memory_enabled

    async def rotate():
        control.message = "Alice must break the brass door."
        return response(AFTER)

    transport.responses.append(rotate)
    with ActiveScene(scene):
        await scene.world_state.request_update()
    assert scene.world_state.location == BEFORE


async def test_manual_add_during_regeneration_reports_wait_even_for_popped_message(
    setup, monkeypatch
):
    scene, world, transport = setup
    target = append_target(scene)
    await snapshot(setup, AFTER)
    statuses = []
    monkeypatch.setattr(
        "talemate.agents.world_state.snapshot.emit",
        lambda *args, **kwargs: statuses.append((args, kwargs)),
    )

    async def generating():
        assert scene.get_message(target.id) is None
        await world.add_and_report_snapshot_entity(target.id, "brass door")
        return "The door stays closed."

    transport.responses.append(generating)
    with ActiveScene(scene):
        await regenerate(scene)
    assert len(transport.prompts) == 2
    assert any("Wait for message regeneration" in str(status) for status in statuses)
    assert not any("did not resolve" in str(status) for status in statuses)


@pytest.mark.parametrize("prior", [True, False])
@pytest.mark.parametrize("durable", [True, False])
async def test_actual_request_restores_or_clears_without_extra_request(
    setup, monkeypatch, prior, durable
):
    scene, world, transport = setup
    monkeypatch.setattr(
        world.actions["update_world_state"].config["durable_snapshot"], "value", durable
    )
    if prior:
        await snapshot(setup, BEFORE)
    target = append_target(scene)
    await snapshot(setup, AFTER)
    original_id = target.id
    count = len(transport.prompts)
    assert await replace(setup) == [target]
    assert target.id == original_id
    assert len(transport.prompts) == count + 1
    assert AFTER not in transport.prompts[-1]
    assert "The brass door bursts into splinters." not in transport.prompts[-1]
    assert (BEFORE in transport.prompts[-1]) == prior
    assert scene.world_state.location == (BEFORE if prior else None)
    assert world.resolve_config("update_world_state", "inject_as_scene_memory")
    assert target.id not in scene.world_state.anchor_message_ids
    assert await replace(setup, "The door is still shut.") == [target]
    assert AFTER not in transport.prompts[-1]
    assert scene.world_state.location == (BEFORE if prior else None)
    await snapshot(setup, "REFRESHED: door still shut.")
    assert scene.world_state.snapshot_provenance.source_message_id == target.id


async def test_repeated_refresh_and_save_reload_preserve_earlier_candidate(setup):
    scene, world, transport = setup
    await snapshot(setup, BEFORE)
    target = append_target(scene)
    await snapshot(setup, AFTER)
    await snapshot(setup, AFTER + " Again.")
    assert scene.world_state.previous_snapshot.location == BEFORE
    provenance = scene.world_state.snapshot_provenance.model_dump()
    previous_provenance = (
        scene.world_state.previous_snapshot.snapshot_provenance.model_dump()
    )
    data = json.loads(scene_data_dumps(scene.serialize))
    await load_scene_from_data(scene, data, name="snapshot-regeneration.json")
    assert scene.world_state.previous_snapshot.location == BEFORE
    assert scene.world_state.previous_snapshot.snapshot_provenance.matches(scene)
    assert scene.world_state.snapshot_provenance.matches(scene)
    assert scene.world_state.snapshot_provenance.source_message_id == target.id
    assert scene.world_state.snapshot_provenance.model_dump() == provenance
    assert (
        scene.world_state.previous_snapshot.snapshot_provenance.model_dump()
        == previous_provenance
    )
    await replace(setup)
    assert BEFORE in transport.prompts[-1]
    assert AFTER not in transport.prompts[-1]
    assert scene.world_state.location == BEFORE


@pytest.mark.parametrize("mode", ["unpinned", "earlier"])
async def test_unrelated_snapshots_are_untouched(setup, monkeypatch, mode):
    scene, world, transport = setup
    await snapshot(setup, BEFORE)
    append_target(scene)
    if mode == "unpinned":
        await snapshot(setup, AFTER)
        monkeypatch.setattr(
            world.actions["update_world_state"].config["inject_as_scene_memory"],
            "value",
            False,
        )
    original = scene.world_state.model_dump()
    await replace(setup)
    assert scene.world_state.model_dump() == original
    assert (BEFORE in transport.prompts[-1]) == (mode == "earlier")
    assert AFTER not in transport.prompts[-1]


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("failed"),
        GenerationCancelled("cancelled"),
        asyncio.CancelledError(),
        "",
        "The brass door bursts into splinters.",
    ],
)
async def test_failed_regeneration_restores_message_snapshot_and_other_state(
    setup, failure
):
    scene, _, _ = setup
    await snapshot(setup, BEFORE)
    target = append_target(scene)
    await snapshot(setup, AFTER)
    trailing = ReinforcementMessage(message="Current reinforcement")
    scene.history.append(trailing)
    scene.world_state.suggestions = [
        Suggestion(
            id="character-Nora",
            name="Nora",
            type="character",
            proposals=[
                Call(uid="n1", name="update_attribute", result="happy", called=True)
            ],
        )
    ]
    original = scene.world_state.model_dump()
    if isinstance(failure, (GenerationCancelled, asyncio.CancelledError)):
        with pytest.raises(type(failure)):
            await replace(setup, failure)
    else:
        assert await replace(setup, failure) == []
    assert scene.history[-2:] == [target, trailing]
    assert target.message == "The brass door bursts into splinters."
    assert scene.world_state.model_dump() == original
    assert not scene.world_state._snapshot_regenerating


@pytest.mark.parametrize("change", ["edit", "delete", "intro"])
async def test_invalid_previous_revision_is_not_restored(setup, change):
    scene, _, transport = setup
    await snapshot(setup, BEFORE)
    append_target(scene)
    await snapshot(setup, AFTER)
    if change == "edit":
        scene.history[0].message = "The gate was already open."
    elif change == "delete":
        scene.history.pop(0)
    else:
        scene.intro = "An entirely different beginning."
    await replace(setup)
    assert BEFORE not in transport.prompts[-1]
    assert AFTER not in transport.prompts[-1]
    assert scene.world_state.location is None


async def test_inflight_old_snapshot_cannot_publish_after_regeneration(setup):
    scene, world, transport = setup
    await snapshot(setup, BEFORE)
    append_target(scene)
    await snapshot(setup, AFTER)
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed():
        started.set()
        await release.wait()
        return response("STALE: old message snapshot.")

    transport.responses.append(delayed)
    with ActiveScene(scene):
        task = asyncio.create_task(world.apply_snapshot_update(scene.world_state))
        await started.wait()
        await replace(setup)
        release.set()
        await task
    assert scene.world_state.location == BEFORE


async def test_inflight_manual_add_cannot_publish_after_regeneration(setup):
    scene, world, transport = setup
    await snapshot(setup, BEFORE)
    target = append_target(scene)
    await snapshot(setup, AFTER)
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed():
        started.set()
        await release.wait()
        return entity_response(
            {"resolved": True, "kind": "item", "name": "Brass door", "snapshot": AFTER}
        )

    transport.responses.append(delayed)
    with ActiveScene(scene):
        task = asyncio.create_task(world.add_snapshot_entity(target.id, "brass door"))
        await started.wait()
        await replace(setup)
        release.set()
        with pytest.raises(GenerationCancelled):
            await task
    assert scene.world_state.location == BEFORE
    assert not scene.world_state.items


async def test_snapshot_mutation_is_blocked_during_rollback_and_preserves_suggestions(
    setup,
):
    scene, world, transport = setup
    await snapshot(setup, BEFORE)
    append_target(scene)
    await snapshot(setup, AFTER)
    scene.world_state.suggestions = [
        Suggestion(
            id="character-Nora",
            name="Nora",
            type="character",
            proposals=[
                Call(uid="n1", name="update_attribute", result="happy", called=True)
            ],
        )
    ]
    original = scene.world_state.suggestions[0].model_dump()

    async def generating():
        assert scene.world_state.location == BEFORE
        await world.apply_snapshot_update(scene.world_state)
        assert scene.world_state.location == BEFORE
        return "The door stays shut."

    count = len(transport.prompts)
    await replace(setup, generating)
    assert len(transport.prompts) == count + 1
    assert scene.world_state.suggestions[0].model_dump() == original


async def test_wipe_and_history_free_export_remove_retained_snapshot(setup):
    scene, _, _ = setup
    await snapshot(setup, BEFORE)
    append_target(scene)
    await snapshot(setup, AFTER)
    original = SnapshotRevision.capture(scene.world_state)
    exported = json.loads(
        scene_export_json(scene, ExportOptions(name="reset", reset_progress=True))
    )
    assert exported["world_state"]["snapshot_provenance"] is None
    assert exported["world_state"]["previous_snapshot"] is None
    assert SnapshotRevision.capture(scene.world_state) == original
    scene.world_state.reset()
    assert scene.world_state.snapshot_provenance is None
    assert scene.world_state.previous_snapshot is None


async def test_previous_snapshot_does_not_cross_a_time_jump(setup):
    scene, _, transport = setup
    await snapshot(setup, BEFORE)
    scene.history.append(TimePassageMessage(message="A day passes."))
    append_target(scene)
    await snapshot(setup, AFTER)
    assert scene.world_state.previous_snapshot is None
    await replace(setup)
    assert BEFORE not in transport.prompts[-1]
    assert scene.world_state.location is None


async def test_intro_snapshot_is_a_valid_previous_revision(setup):
    scene, _, transport = setup
    scene.history = []
    scene.intro = "A locked gate stands ahead."
    await snapshot(setup, BEFORE)
    append_target(scene)
    await snapshot(setup, AFTER)
    await replace(setup)
    assert BEFORE in transport.prompts[-1]


async def test_all_snapshot_fields_restore_together(setup):
    scene, _, transport = setup
    transport.responses.append(
        '"Nora": {"snapshot": "BEFORE_CHARACTER", "emotion": "calm", "mentions": ["Nora"]}}, "items": {"Door": {"snapshot": "BEFORE_ITEM"}}, "places": {"Hall": {"snapshot": "BEFORE_PLACE"}}, "location": "BEFORE_LOCATION"}\n```'
    )
    with ActiveScene(scene):
        await scene.world_state.request_update()
    before = SnapshotRevision.capture(scene.world_state)
    append_target(scene)
    await snapshot(setup, AFTER)
    scene.world_state.characters["Nora"].snapshot = "AFTER_CHARACTER"
    scene.world_state.items["Door"].snapshot = "AFTER_ITEM"
    scene.world_state.places["Hall"].snapshot = "AFTER_PLACE"
    await replace(setup)
    assert SnapshotRevision.capture(scene.world_state) == before
    for token in ("BEFORE_CHARACTER", "BEFORE_ITEM", "BEFORE_PLACE", "BEFORE_LOCATION"):
        assert token in transport.prompts[-1]
    for token in ("AFTER_CHARACTER", "AFTER_ITEM", "AFTER_PLACE", AFTER):
        assert token not in transport.prompts[-1]
