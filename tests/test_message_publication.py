import asyncio
from copy import deepcopy
from time import monotonic_ns
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import json

import test_load_character_activation
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.emit import signals
from talemate.exceptions import GenerationCancelled
from talemate import exceptions
from talemate.instance import get_agent
from talemate.load import load_scene, new_scene
from talemate.knowledge.schema import Fact
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    DirectorMessage,
    NarratorMessage,
    TimePassageMessage,
)
from talemate.tale_mate import Actor
from talemate.world_state import Reinforcement


load_env = test_load_character_activation.load_env


@pytest.fixture
def dialogue(scene, monkeypatch):
    """Track learning from dialogue on, with a mocked ledger answer."""
    from talemate.prompts import Prompt

    conversation = get_agent("conversation")
    config = conversation.actions["character_knowledge"]
    config.enabled = True
    config.config["ledger"].value = True
    scene.character_data = {
        name: Character(name=name, is_player=name == "Alice")
        for name in ("Alice", "Edwin", "Mara")
    }
    scene.active_characters = ["Alice", "Edwin", "Mara"]
    scene.actors = [
        Actor(character, conversation) for character in scene.character_data.values()
    ]
    for actor in scene.actors:
        actor.scene = scene
    scene.ts = 500
    scene.history = []
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    monkeypatch.setattr(memory, "add_many", AsyncMock())
    monkeypatch.setattr(memory, "delete", AsyncMock())
    monkeypatch.setattr(
        memory, "compare_string_lists", AsyncMock(return_value={"distance_matches": []})
    )
    monkeypatch.setattr(
        memory, "compare_strings", AsyncMock(return_value={"euclidean_distance": 0.01})
    )
    monkeypatch.setattr(scene, "emit_status", Mock())
    request = AsyncMock(return_value=("", {"ledger": json.dumps({})}))
    monkeypatch.setattr(Prompt, "request", request)
    with ActiveScene(scene):
        yield scene, conversation, memory, request


@pytest.fixture
def published():
    records = []

    def receive(emission):
        snapshot = SimpleNamespace(
            id=emission.id,
            message=emission.message,
            data=deepcopy(emission.data),
            kwargs=deepcopy(emission.kwargs),
            character=SimpleNamespace(name=emission.character.name)
            if emission.character is not None
            else None,
        )
        records.append((emission.typ, monotonic_ns(), snapshot))

    names = (
        "character",
        "narrator",
        "director",
        "time",
        "context_investigation",
        "world_state",
        "message_edited",
        "knowledge_changed",
        "message_asset_update",
        "clear_screen",
    )
    for name in names:
        signals.handlers[name].connect(receive)
    yield records
    for name in names:
        signals.handlers[name].disconnect(receive)


@pytest.fixture
def publication_scene(scene, isolate_signals, monkeypatch):
    isolate_signals(
        "push_history",
        "push_history.after",
        "game_loop_new_message",
        "agent.conversation.finalized",
    )
    scene.knowledge_eligibility = "perception"
    scene.character_data = {name: Character(name=name) for name in ("Alice", "Bob")}
    scene.active_characters = ["Alice", "Bob"]
    scene.actors = [
        Actor(c, get_agent("conversation")) for c in scene.character_data.values()
    ]
    for actor in scene.actors:
        actor.scene = scene
    monkeypatch.setattr(scene, "emit_status", Mock())
    monkeypatch.setattr(get_agent("summarizer"), "finalize_perceptions", AsyncMock())
    with ActiveScene(scene):
        yield scene


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_player_is_visible_while_analysis_blocks_reply(
    publication_scene, published, monkeypatch, cancel
):
    scene = publication_scene
    started, release = asyncio.Event(), asyncio.Event()
    ordering = []
    message = CharacterMessage(message="Alice: Hello.", source="player")
    reply = AsyncMock()

    async def analyze(*args):
        ordering.append(monotonic_ns())
        started.set()
        await release.wait()
        if cancel:
            raise GenerationCancelled("Stopped perception analysis")

    monkeypatch.setattr(get_agent("summarizer"), "finalize_perceptions", analyze)

    async def turn():
        await scene.push_history(message, emit_message=True)
        await reply()

    task = asyncio.create_task(turn())
    try:
        await asyncio.wait_for(started.wait(), 2)
        lines = [r for r in published if r[0] == "character"]
        assert len(lines) == 1
        assert lines[0][1] < ordering[0]
        assert lines[0][2].message == "Alice: Hello."
        assert scene.history == [message]
        reply.assert_not_awaited()
        release.set()
        if cancel:
            with pytest.raises(GenerationCancelled):
                await asyncio.wait_for(task, 2)
            reply.assert_not_awaited()
        else:
            await asyncio.wait_for(task, 2)
            reply.assert_awaited_once()
        assert len([r for r in published if r[0] == "character"]) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,kwargs",
    [
        (CharacterMessage, {"message": "Alice: Draft."}),
        (NarratorMessage, {"message": "Draft."}),
        (DirectorMessage, {"message": "Draft.", "meta": {"character": "Alice"}}),
        (ContextInvestigationMessage, {"message": "Draft."}),
        (TimePassageMessage, {"message": "One hour later", "ts": 3600}),
    ],
)
async def test_every_visible_type_publishes_after_edit_before_hooks(
    publication_scene, published, monkeypatch, kind, kwargs
):
    scene = publication_scene
    message = kind(**kwargs)
    calls = []

    async def edit(event):
        calls.append("edit")
        event.messages[0].message = (
            "Alice: Final." if kind is CharacterMessage else "Final."
        )

    async def analyze(*args):
        calls.append("perceptions")
        assert published[0][2].message == message.message

    async def hook(event):
        calls.append("ledger/tts")
        assert len(published) == 1

    async def archive(event):
        calls.append("archive")
        assert len(published) == 1

    scene.signals["push_history"].connect(edit)
    scene.signals["game_loop_new_message"].connect(hook)
    scene.signals["push_history.after"].connect(archive)
    monkeypatch.setattr(get_agent("summarizer"), "finalize_perceptions", analyze)
    await scene.push_history(message, emit_message=True)
    assert calls == ["edit", "perceptions", "ledger/tts", "archive"]
    assert len(published) == 1
    assert published[0][0] == message.typ
    assert published[0][2].id == message.id
    if kind in (CharacterMessage, DirectorMessage):
        assert published[0][2].character.name == "Alice"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_silent_push_stays_silent_even_on_cancellation(
    publication_scene, published, cancel
):
    message = CharacterMessage(message="Alice: Hidden from display.")
    get_agent("summarizer").finalize_perceptions.side_effect = (
        GenerationCancelled("Stopped") if cancel else None
    )
    if cancel:
        with pytest.raises(GenerationCancelled):
            await publication_scene.push_history(message)
    else:
        await publication_scene.push_history(message)
    assert publication_scene.history == [message]
    assert published == []


@pytest.mark.asyncio
async def test_batch_filters_empty_director_and_emits_each_line_once(
    publication_scene, published
):
    messages = [
        NarratorMessage(message="First."),
        DirectorMessage(message="  "),
        CharacterMessage(message="Alice: Second."),
    ]
    await publication_scene.push_history(messages, emit_message=True)
    assert [r[2].id for r in published] == [messages[0].id, messages[2].id]


@pytest.mark.asyncio
async def test_real_ledger_grants_after_publication_and_records_no_fact(
    dialogue, published, isolate_signals
):
    scene, conversation, _, request = dialogue
    scene.active = True
    old_fact = Fact(
        id="F100", text="The key is under the lantern.", ts=500, present=["Alice"]
    )
    scene.world_state.facts[old_fact.id] = old_fact
    isolate_signals("push_history", "push_history.after", "game_loop_new_message")
    scene.signals["game_loop_new_message"].connect(conversation.on_new_message)
    response = request.return_value
    response[1]["ledger"] = '{"Edwin": ["F100"]}'

    async def record(*args, **kwargs):
        assert [r[0] for r in published] == ["character"]
        assert "Edwin" not in old_fact.known_by
        return response

    request.side_effect = record
    await scene.push_history(
        CharacterMessage(
            message="Alice: I moved into the lighthouse.", source="player"
        ),
        emit_message=True,
    )
    request.assert_awaited_once()
    assert old_fact.known_by["Edwin"] == "inferred"
    # the ledger grants; facts come from the archive step only
    assert list(scene.world_state.facts) == [old_fact.id]
    assert "knowledge_changed" in [r[0] for r in published][1:]


@pytest.mark.asyncio
@pytest.mark.parametrize("insert", ["sequential", "all-context"])
@pytest.mark.parametrize("manual", [False, True])
async def test_track_state_answer_precedes_analysis(
    publication_scene, published, monkeypatch, insert, manual
):
    scene = publication_scene
    question = "Where is the key?"

    async def analyze(*args):
        updates = [r[2].data for r in published if r[0] == "world_state"]
        assert updates[-1]["reinforce"][0]["answer"] == "Under the lantern."
        raise GenerationCancelled("Stopped")

    monkeypatch.setattr(get_agent("summarizer"), "finalize_perceptions", analyze)
    with pytest.raises(GenerationCancelled):
        if manual:
            await scene.world_state.add_reinforcement(
                question, insert=insert, answer="Under the lantern."
            )
        else:
            reinforcement = Reinforcement(question=question, insert=insert)
            scene.world_state.reinforce.append(reinforcement)
            agent = get_agent("world_state")
            message = agent._prepare_reinforcement(reinforcement, False)
            await agent._apply_reinforcement(
                reinforcement, message, "Under the lantern.", False
            )
    assert scene.world_state.reinforce[0].answer == "Under the lantern."


@pytest.mark.asyncio
async def test_avatar_runs_after_line_and_updates_its_saved_id(
    publication_scene, published, isolate_signals, monkeypatch
):
    scene = publication_scene
    message = CharacterMessage(message="Alice: Hello.")
    message._avatar_pending = True
    avatar = "selected-avatar"
    signal = isolate_signals("agent.conversation.finalized")
    snapshots = []

    async def choose(event):
        snapshots.append([r[0] for r in published])
        assert event.message_ids == [message.id]
        assert scene.get_message(message.id) is message
        event.avatar = avatar

    signal.connect(choose)
    monkeypatch.setattr(scene.assets, "validate_asset_id", lambda _: True)
    monkeypatch.setattr(
        scene.assets,
        "get_asset",
        lambda _: SimpleNamespace(meta=SimpleNamespace(vis_type="CHARACTER_PORTRAIT")),
    )
    await scene.push_history(message, emit_message=True)
    assert snapshots == [["character"]]
    assert message.asset_id == avatar
    assert [r[0] for r in published] == ["character", "message_asset_update"]
    assert published[-1][2].kwargs["message_id"] == message.id
    await get_agent("conversation").finalize_message_avatar(message)
    assert len(snapshots) == 1


@pytest.mark.asyncio
async def test_load_publishes_hydrated_history_before_indexing(
    load_env, published, tmp_path, monkeypatch
):
    import json

    scene = load_env
    data = new_scene()
    data["intro"] = "The lighthouse is quiet."
    data["character_data"] = {"Alice": {"name": "Alice", "is_player": True}}
    data["active_characters"] = ["Alice"]
    data["history"] = [NarratorMessage(message="A bell rings.").to_dict()]
    path = tmp_path / "load.json"
    path.write_text(json.dumps(data))
    order = []

    async def display(loaded):
        order.append("display")
        assert loaded.history[0].message == "A bell rings."
        assert loaded.main_character is not None
        await loaded.emit_history()

    async def index():
        order.append("index")
        assert any(r[2].message == "A bell rings." for r in published)

    monkeypatch.setattr(scene, "commit_to_memory", index)
    with ActiveScene(scene):
        loaded = await load_scene(
            scene, str(path), add_to_recent=False, before_memory=display
        )
    assert loaded is scene
    assert order == ["display", "index"]


@pytest.mark.asyncio
@pytest.mark.parametrize("startup_changes", [False, True])
async def test_visible_history_is_not_replayed_unless_startup_changes_it(
    publication_scene, monkeypatch, startup_changes
):
    scene = publication_scene
    scene.active = False
    scene.history = [NarratorMessage(message="Before startup.")]

    async def startup():
        if startup_changes:
            scene.history[0].message = "After startup."

    monkeypatch.setattr(scene, "_game_startup", startup)
    replay = AsyncMock()
    monkeypatch.setattr(scene, "emit_history", replay)
    await scene._run_game_loop(history_visible=True)
    assert replay.await_count == int(startup_changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancel", "none", "error"])
async def test_incomplete_load_does_not_publish_or_index(
    load_env, monkeypatch, tmp_path, outcome
):
    import talemate.load as loader

    scene = load_env
    path = tmp_path / "scene.json"
    path.write_text('{"name": "Incomplete"}')
    monkeypatch.setattr(loader, "identify_import_spec", lambda _: "talemate")

    async def hydrate(*args, **kwargs):
        if outcome == "cancel":
            raise asyncio.CancelledError()
        if outcome == "error":
            raise ValueError("Invalid scene")
        return None

    display = AsyncMock()
    index = AsyncMock()
    monkeypatch.setattr(loader, "load_scene_from_data", hydrate)
    monkeypatch.setattr(scene, "commit_to_memory", index)
    with ActiveScene(scene):
        if outcome == "none":
            assert await load_scene(scene, str(path), before_memory=display) is None
        else:
            error = asyncio.CancelledError if outcome == "cancel" else ValueError
            with pytest.raises(error):
                await load_scene(scene, str(path), before_memory=display)
    display.assert_not_awaited()
    index.assert_not_awaited()


@pytest.mark.asyncio
async def test_shipped_avatar_listener_binds_the_published_message(
    publication_scene, published, monkeypatch
):
    from talemate.game.engine.nodes.core import GraphContext
    from talemate.game.engine.nodes.event import collect_listeners, connect_listeners
    from talemate.game.engine.nodes.layout import load_graph
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded

    ensure_registry_loaded()
    scene = publication_scene
    graph, _ = load_graph("scene-loop.json")
    listeners = collect_listeners(graph)
    avatar_listeners = [
        listener
        for listener in listeners.get("agent.conversation.finalized", [])
        if listener.registry == "agents/summarizer/onMessageSetAvatar"
    ]
    assert len(avatar_listeners) == 1
    assert all(
        listener.registry != "agents/summarizer/onMessageSetAvatar"
        for listener in listeners.get("agent.conversation.generated", [])
    )
    message = CharacterMessage(message="Alice: The lantern is lit.")
    message._avatar_pending = True
    calls = []
    determine = next(
        node
        for node in avatar_listeners[0].nodes.values()
        if node.registry == "agents/world_state/determineCharacterAvatar"
    )

    async def choose(node, state):
        calls.append(node.get_input_values())
        assert published[0][0] == "character"

    monkeypatch.setattr(type(determine), "run", choose)
    with GraphContext() as state:
        connect_listeners(graph, state)
        await scene.push_history(message, emit_message=True)
    assert len(calls) == 1
    assert calls[0]["content"] == message.message
    assert calls[0]["character"] is scene.get_character("Alice")
    assert calls[0]["asset_ctx"].message_ids == [message.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["attachment", "graph"])
async def test_portrait_failure_does_not_skip_new_message_or_archive_hooks(
    publication_scene, published, isolate_signals, failure
):
    scene = publication_scene
    message = CharacterMessage(message="Alice: Still process this turn.")
    message._avatar_pending = True
    order = []

    async def choose(event):
        if failure == "graph":
            raise ValueError("Invalid custom avatar graph")
        event.avatar = "missing-asset"

    async def new_message(event):
        order.append("ledger-tts")

    async def archive(event):
        order.append("archive")

    isolate_signals("agent.conversation.finalized").connect(choose)
    scene.signals["game_loop_new_message"].connect(new_message)
    scene.signals["push_history.after"].connect(archive)
    await scene.push_history(message, emit_message=True)
    assert order == ["ledger-tts", "archive"]
    assert [item[0] for item in published] == ["character"]


@pytest.mark.asyncio
async def test_no_portrait_decision_preserves_regenerated_message_asset(
    publication_scene, monkeypatch
):
    scene = publication_scene
    scene.get_character("Alice").current_avatar = "current-avatar"
    message = CharacterMessage(
        message="Alice: Regenerated.", asset_id="recorded-avatar", asset_type="avatar"
    )
    message._avatar_pending = True
    scene.history.append(message)
    update = AsyncMock()
    monkeypatch.setattr(scene.assets, "update_message_asset", update)
    await get_agent("conversation").finalize_message_avatar(message)
    update.assert_not_awaited()
    assert message.asset_id == "recorded-avatar"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type",
    [
        exceptions.GenerationCancelled,
        exceptions.ExitScene,
        exceptions.RestartSceneLoop,
        exceptions.ResetScene,
        exceptions.AbortCommand,
        exceptions.AbortWaitForInput,
        exceptions.ActedAsCharacter,
    ],
)
async def test_finalized_portrait_preserves_control_flow(
    publication_scene, isolate_signals, exception_type
):
    message = CharacterMessage(message="Alice: Interrupted.")
    message._avatar_pending = True
    publication_scene.history.append(message)
    interrupt = exception_type("Alice")

    async def choose(event):
        raise interrupt

    isolate_signals("agent.conversation.finalized").connect(choose)
    with pytest.raises(exception_type) as raised:
        await get_agent("conversation").finalize_message_avatar(message)
    assert raised.value is interrupt


@pytest.mark.asyncio
async def test_manual_clear_restores_default_avatar_cadence(
    publication_scene, published
):
    message = CharacterMessage(
        message="Alice: Clear this.", asset_id="old", asset_type="avatar"
    )
    publication_scene.history.append(message)
    await publication_scene.assets.clear_message_asset(message.id)
    update = next(
        event for kind, _, event in published if kind == "message_asset_update"
    )
    assert update.kwargs == {
        "message_id": message.id,
        "asset_id": None,
        "asset_type": None,
    }


@pytest.mark.asyncio
async def test_manual_determine_avatar_route_overrides_cadence(
    publication_scene, published, monkeypatch
):
    from talemate.game.engine.nodes.core import GraphState
    from talemate.game.engine.nodes.registry import get_node
    from talemate.game.engine.nodes.tools.analysis import ensure_registry_loaded
    from talemate.agents.world_state.websocket_handler import WorldStateWebsocketHandler
    from talemate.scene_assets import AssetMeta
    from talemate.agents.visual.schema import VIS_TYPE

    ensure_registry_loaded()
    scene = publication_scene
    scene.nodegraph_state = GraphState()
    monkeypatch.setattr(type(scene), "auto_save", property(lambda _: False))
    message = CharacterMessage(message="Alice: Choose my portrait.")
    scene.history.append(message)
    asset = await scene.assets.add_asset(
        b"portrait",
        "png",
        "image/png",
        meta=AssetMeta(vis_type=VIS_TYPE.CHARACTER_PORTRAIT),
    )
    calls = []

    async def choose(node, state):
        calls.append(node.get_input_values())
        node.set_output_values({"asset_id": asset.id})

    monkeypatch.setattr(
        get_node("agents/world_state/determineCharacterAvatar"), "run", choose
    )
    handler = SimpleNamespace(scene=scene, queue_put=Mock())
    router = WorldStateWebsocketHandler(handler)
    agent = get_agent("world_state")
    monkeypatch.setattr(WorldStateWebsocketHandler, "sub_handlers", {}, raising=False)
    await type(agent).init_nodes(scene, scene.nodegraph_state)
    original_create_task = asyncio.create_task
    tasks = []

    def track(coro, **kwargs):
        task = original_create_task(coro, **kwargs)
        tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", track)
    await router.handle(
        {
            "type": "world_state_agent",
            "action": "determine_avatar",
            "character": "Alice",
            "response": message.message,
            "message_ids": [message.id],
            "force_determine": True,
        }
    )
    assert tasks
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    assert len(calls) == 1
    assert calls[0]["force_determine"] is True
    updates = [
        event.kwargs for kind, _, event in published if kind == "message_asset_update"
    ]
    assert updates == [
        {
            "message_id": message.id,
            "asset_id": asset.id,
            "asset_type": "avatar",
            "override_cadence": True,
        }
    ]
    assert message.asset_id == asset.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,expected",
    [("knowledge", 1), ("outside", 0), ("asset", 1), ("text", 1), ("version", 1)],
)
async def test_startup_replay_compares_only_visible_window(
    publication_scene, monkeypatch, change, expected
):
    scene = publication_scene
    scene.active = False
    monkeypatch.setattr(type(scene), "max_backscroll", property(lambda _: 1))
    scene.history = [
        NarratorMessage(message="Outside."),
        CharacterMessage(message="Alice: Visible."),
    ]

    async def startup():
        message = scene.history[-1]
        if change == "knowledge":
            from talemate.knowledge.perspectives import set_source_perspectives

            set_source_perspectives(
                scene,
                "message",
                message.id,
                [{"audience": ["Bob"], "status": "failed"}],
            )
            message.rev += 1
            message.present = ["Alice"]
        elif change == "outside":
            scene.history[0].message = "Changed outside the window."
        elif change == "asset":
            message.asset_id = "new-avatar"
        elif change == "text":
            message.message = "Alice: Changed."
        else:
            message.append_version(message.message, "revision")

    monkeypatch.setattr(scene, "_game_startup", startup)
    replay = AsyncMock()
    monkeypatch.setattr(scene, "emit_history", replay)
    await scene._run_game_loop(history_visible=True)
    assert replay.await_count == expected
