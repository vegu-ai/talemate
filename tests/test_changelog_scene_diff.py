"""The changelog diff shares unchanged subtrees before DeepDiff runs.

The shared diff must give exactly the delta a plain DeepDiff gives, and a
chain written with it must reconstruct every revision; an append must not
make DeepDiff compare the unchanged history.
"""

from __future__ import annotations

import copy
import json
from unittest.mock import AsyncMock

import deepdiff
import pytest

import talemate.changelog as changelog

from _changelog_test_helpers import make_changelog_scene, persist_test_mutation
from talemate.changelog import (
    EXCLUDE_FROM_DELTAS,
    EXCLUDE_FROM_DELTAS_REGEX,
    _apply_delta,
    _compute_delta,
    _delta_reproduces_state,
    _full_list_opcode_ops,
    _full_subtree_world_state_ops,
    _latest_path,
    check_chain_divergence,
    reconstruct_scene_data,
)
from talemate.scene_message import CharacterMessage, NarratorMessage

MUTATIONS = [
    "append",
    "append dispatch flag",
    "stamp rev",
    "edit old message",
    "delete middle",
    "delete last",
    "regenerate",
    "revision state",
    "reorder history",
    "reorder basic list",
    "world state pins",
    "excluded path",
    "int to bool",
    "type change",
]

# `==` holds between the kept values, their JSON types differ; DeepDiff
# reports the parent whole
TYPED_CASES = {
    "replaced dict": (
        {"history": [{"meta": {"enabled": 1, "ratio": 1, **dict.fromkeys("abcd")}}]},
        {
            "history": [
                {"meta": {"enabled": True, "ratio": 1.0, **dict.fromkeys("efgh")}}
            ]
        },
    ),
    "reordered list": (
        {"l": [{"a": ["a"], "e": True}, {"d": [False], "e": True, "c": [1.0]}]},
        {"l": [{"d": [0.0], "e": 1, "c": [1]}, {"a": ["a"], "e": True}]},
    ),
}


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _plain_diff(prev: dict, curr: dict) -> deepdiff.DeepDiff:
    return deepdiff.DeepDiff(
        prev,
        curr,
        ignore_order=False,
        exclude_paths=EXCLUDE_FROM_DELTAS,
        exclude_regex_paths=EXCLUDE_FROM_DELTAS_REGEX,
        ignore_type_in_groups=[(type(None), str, int, float, bool, list, dict)],
    )


def _plain_delta(prev: dict, curr: dict) -> dict:
    diff = _plain_diff(prev, curr)
    if not diff:
        return {}
    delta = diff._to_delta_dict()
    _full_list_opcode_ops(delta, prev, curr)
    _full_subtree_world_state_ops(delta, prev, curr)
    return delta


def _messages(count: int) -> list:
    return [
        CharacterMessage(message=f"Alice: line {i}", id=i + 1, present=["Alice"])
        if i % 2
        else NarratorMessage(message=f"The tide turns {i}.", id=i + 1)
        for i in range(count)
    ]


def _state(messages: list, **extra) -> dict:
    data = {
        "name": "Diff",
        "ts": 0,
        "active_characters": ["Alice", "Bob"],
        "history": [message.to_dict() for message in messages],
        "world_state": {"pins": {}, "reinforce": [], "character_name_mappings": {}},
        "memory_session_id": "session-1",
        **extra,
    }
    return json.loads(json.dumps(data))


def _mutate(name: str, data: dict) -> None:
    history = data["history"]
    if name == "append":
        history.append({**copy.deepcopy(history[-1]), "id": 999, "message": "new"})
    elif name == "append dispatch flag":
        history.append(
            {
                **copy.deepcopy(history[-1]),
                "id": 999,
                "history_dispatch_pending": True,
                "history_dispatch_completed": [],
            }
        )
    elif name == "stamp rev":
        history[-1]["rev"] = 7
    elif name == "edit old message":
        history[3]["message"] = "Alice: changed"
    elif name == "delete middle":
        del history[5]
    elif name == "delete last":
        history.pop()
    elif name == "regenerate":
        history[-1]["versions"].append({"message": "again", "source": "regenerate"})
        history[-1]["active_version"] = 1
        history[-1]["message"] = "again"
    elif name == "revision state":
        history[4]["revision_state"]["status"] = "running"
    elif name == "reorder history":
        history.insert(2, history.pop(8))
    elif name == "reorder basic list":
        data["active_characters"].reverse()
    elif name == "world state pins":
        data["world_state"]["pins"]["p1"] = {"text": "The key is brass."}
    elif name == "excluded path":
        data["memory_session_id"] = "session-2"
    elif name == "int to bool":
        history[2]["flags"] = False
    elif name == "type change":
        history[2]["meta"] = {"a": [1, 2]}
        data["ts"] = "PT1H"
    else:
        raise AssertionError(name)


@pytest.mark.parametrize("name", MUTATIONS)
def test_shared_diff_matches_plain_deepdiff(name):
    prev = _state(_messages(12))
    curr = copy.deepcopy(prev)
    _mutate(name, curr)

    assert _json(_compute_delta(prev, curr)) == _json(_plain_delta(prev, curr))


@pytest.mark.parametrize("case", TYPED_CASES)
def test_shared_diff_keeps_the_json_type_of_each_value(case):
    prev, curr = TYPED_CASES[case]

    delta = _compute_delta(prev, curr)
    applied = _apply_delta(prev, json.loads(json.dumps(delta)))

    assert _json(delta) == _json(_plain_delta(prev, curr))
    assert _json(applied) == _json(curr)
    assert _delta_reproduces_state(prev, curr, delta)


@pytest.mark.parametrize("case", TYPED_CASES)
def test_check_refuses_a_written_value_of_another_json_type(case):
    prev, curr = TYPED_CASES[case]
    # the state the delta must write, with one kept value of another type
    written = copy.deepcopy(curr)
    if case == "replaced dict":
        written["history"][0]["meta"]["enabled"] = 1
    else:
        written["l"][0]["e"] = True

    delta = _plain_delta(prev, written)

    assert delta
    assert not _delta_reproduces_state(prev, curr, delta)


@pytest.mark.parametrize("name", MUTATIONS)
def test_delta_check_matches_plain_deepdiff(name):
    prev = _state(_messages(12))
    curr = copy.deepcopy(prev)
    _mutate(name, curr)
    delta = _compute_delta(prev, curr)

    if delta:
        assert _delta_reproduces_state(prev, curr, delta)
    # a wrong target state must still fail the check
    wrong = copy.deepcopy(curr)
    wrong["history"][0]["message"] = "not what the delta wrote"
    assert not _delta_reproduces_state(prev, wrong, delta or {"values_changed": {}})


def test_shared_diff_leaves_inputs_unchanged():
    prev = _state(_messages(12))
    curr = copy.deepcopy(prev)
    _mutate("append", curr)
    prev_copy, curr_copy = _json(prev), _json(curr)

    _compute_delta(prev, curr)

    assert _json(prev) == prev_copy
    assert _json(curr) == curr_copy


@pytest.mark.asyncio
async def test_chain_reconstructs_every_revision(tmp_path):
    messages = _messages(20)
    scene = make_changelog_scene(str(tmp_path), initial_serialize=_state(messages))
    expected = {}

    async def save(**extra):
        scene.serialize = _state(messages, **extra)
        rev = await persist_test_mutation(scene)
        if rev is not None:
            expected[rev] = copy.deepcopy(scene.serialize)
        return rev

    await save()
    player = CharacterMessage(message="Alice: I take the key.", source="player")
    player.history_dispatch_pending = True
    messages.append(player)
    await save()
    player.history_dispatch_pending = False
    await save()
    messages.append(NarratorMessage(message="The lamp flickers."))
    await save()
    messages[-1].append_version("The lamp goes dark.", "regenerate")
    await save()
    messages[6].append_version("Alice: line 6, told again.", "revision")
    await save()
    messages[6].set_active_version(0)
    await save()
    messages[9].hide()
    await save()
    del messages[4]
    await save()
    messages.pop()
    await save()
    pinned = {
        "pins": {"p1": {"text": "brass"}},
        "reinforce": [],
        "character_name_mappings": {},
    }
    await save(world_state=pinned)
    assert await save(world_state=pinned, memory_session_id="session-2") is None

    assert sorted(expected) == list(range(1, 11))
    for rev, state in expected.items():
        reconstructed = await reconstruct_scene_data(scene, to_rev=rev)
        assert not _plain_diff(reconstructed, state), rev
        assert _json(reconstructed["history"]) == _json(state["history"]), rev
    assert await check_chain_divergence(scene) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [500, 2500, 5000])
async def test_append_diff_work_does_not_grow_with_history(
    tmp_path, monkeypatch, count
):
    messages = _messages(count)
    scene = make_changelog_scene(str(tmp_path), initial_serialize=_state(messages))
    await persist_test_mutation(scene)

    compared = []
    diff_dict = deepdiff.DeepDiff._diff_dict

    def counting_diff_dict(self, level, *args, **kwargs):
        compared.append(level.path())
        return diff_dict(self, level, *args, **kwargs)

    monkeypatch.setattr(deepdiff.DeepDiff, "_diff_dict", counting_diff_dict)
    messages.append(CharacterMessage(message="Alice: one more.", source="player"))
    scene.serialize = _state(messages)

    assert await persist_test_mutation(scene) == 1
    # only the root of the delta: the new message is added whole, and the
    # check's applied state equals the scene, so its diff compares nothing
    assert compared == ["root"]


@pytest.mark.asyncio
async def test_latest_snapshot_is_unindented_and_an_indented_one_still_reads(
    tmp_path,
):
    messages = _messages(3)
    scene = make_changelog_scene(str(tmp_path), initial_serialize=_state(messages))
    await persist_test_mutation(scene)
    messages.append(NarratorMessage(message="The lamp flickers.", id=100))
    scene.serialize = _state(messages)
    assert await persist_test_mutation(scene) == 1

    with open(_latest_path(scene)) as f:
        text = f.read()
    assert "\n" not in text
    # the latest snapshot as 0.39.0 wrote it
    with open(_latest_path(scene), "w") as f:
        json.dump(json.loads(text), f, indent=2)

    messages.append(NarratorMessage(message="The lamp goes dark.", id=101))
    scene.serialize = _state(messages)
    assert await persist_test_mutation(scene) == 2
    reconstructed = await reconstruct_scene_data(scene, to_rev=2)
    assert _json(reconstructed["history"]) == _json(scene.serialize["history"])


KIND_CHANGES = {
    "list to string": (["sword"], "sword"),
    "list to dict": (["sword"], {"sword": 1}),
    "string to list": ("sword", ["sword"]),
    "dict to list": ({"sword": 1}, ["sword"]),
    "empty list to dict": ([], {"a": 1}),
    "empty list to string": ([], ""),
    "empty list to empty dict": ([], {}),
    "list to int": (["sword"], 3),
    "dict to int": ({"sword": 1}, 3),
}

KIND_CHANGE_PLACES = ["game state variable", "agent state", "message meta"]


def _with_value(messages: list, place: str, value) -> dict:
    if place == "game state variable":
        return _state(messages, game_state={"variables": {"inv": value}})
    if place == "agent state":
        return _state(messages, agent_state={"director": {"inv": value}})
    data = _state(messages)
    data["history"][2]["meta"] = {"inv": value}
    return data


@pytest.mark.asyncio
@pytest.mark.parametrize("place", KIND_CHANGE_PLACES)
@pytest.mark.parametrize("change", KIND_CHANGES)
async def test_container_kind_change_keeps_recording(tmp_path, change, place):
    before, after = KIND_CHANGES[change]
    messages = _messages(4)
    scene = make_changelog_scene(
        str(tmp_path), initial_serialize=_with_value(messages, place, before)
    )
    await persist_test_mutation(scene)
    expected = {}

    async def save(scene, value):
        messages.append(NarratorMessage(message=f"Line {len(messages)}."))
        scene.serialize = _with_value(messages, place, value)
        rev = await persist_test_mutation(scene)
        expected[rev] = copy.deepcopy(scene.serialize)
        return rev

    assert await save(scene, after) == 1
    assert await save(scene, after) == 2
    # a reload reads the chain and the latest snapshot from disk again
    reloaded = make_changelog_scene(str(tmp_path), initial_serialize=scene.serialize)
    assert await save(reloaded, after) == 3
    assert await save(reloaded, before) == 4

    for rev, state in expected.items():
        reconstructed = await reconstruct_scene_data(reloaded, to_rev=rev)
        assert _json(reconstructed) == _json(state), rev
    assert await check_chain_divergence(reloaded) == []
    # every save wrote a small delta, not the full state
    assert _full_state_revisions(reloaded) == []


def _full_state_revisions(scene) -> list[int]:
    return [
        entry["rev"]
        for _, path in changelog._get_changelog_files(scene)
        for entry in json.load(open(path))["deltas"]
        if "root" in (entry["delta"].get("values_changed") or {})
    ]


@pytest.mark.parametrize("change", KIND_CHANGES)
def test_container_kind_change_is_written_whole(change):
    before, after = KIND_CHANGES[change]
    prev = _with_value(_messages(4), "game state variable", before)
    curr = _with_value(_messages(5), "game state variable", after)

    delta = changelog._exact_delta(prev, curr)
    applied = _apply_delta(prev, json.loads(json.dumps(delta)))

    assert "root" not in delta.get("values_changed", {})
    assert _json(applied) == _json(curr)
    assert _delta_reproduces_state(prev, curr, delta)


QUOTE_KEY = "a'b\"c"


@pytest.mark.parametrize(
    "before,after",
    [(1, 2), (["sword"], "sword"), ({"x": 1}, {"x": 2, "y": 3})],
    ids=["value change", "kind change", "nested change"],
)
def test_a_key_with_both_quote_kinds_writes_its_dict_not_the_full_state(before, after):
    prev = _state(_messages(4), game_state={"variables": {QUOTE_KEY: before, "n": 1}})
    curr = _state(_messages(5), game_state={"variables": {QUOTE_KEY: after, "n": 1}})

    delta = changelog._exact_delta(prev, curr)

    assert "root" not in delta.get("values_changed", {})
    assert "root['game_state']['variables']" in delta["values_changed"]
    assert _json(_apply_delta(prev, json.loads(json.dumps(delta)))) == _json(curr)


def test_a_kind_change_at_an_excluded_path_under_a_whole_dict():
    prev = {"agent_state": {"director": {"cached_guidance": ["x"], "a": 1, "b": 2}}}
    curr = {"agent_state": {"director": {"cached_guidance": "x", "d": 1, "e": 2}}}

    delta = changelog._exact_delta(prev, curr)

    assert list(delta["values_changed"]) == ["root['agent_state']['director']"]
    assert _json(_apply_delta(prev, json.loads(json.dumps(delta)))) == _json(curr)
    # a kind change only at the excluded path writes nothing
    prev["agent_state"]["director"] = {"cached_guidance": ["x"], "a": 1}
    curr["agent_state"]["director"] = {"cached_guidance": "x", "a": 1}
    assert changelog._exact_delta(prev, curr) == {}


def test_container_kind_change_under_a_dict_reported_whole():
    prev = {"m": {"inv": ["sword"], "a": 1, "b": 2, "c": 3, "d": 4}}
    curr = {"m": {"inv": "sword", "e": 1, "f": 2, "g": 3, "h": 4}}

    delta = _compute_delta(prev, curr)

    assert _json(_apply_delta(prev, json.loads(json.dumps(delta)))) == _json(curr)
    assert _delta_reproduces_state(prev, curr, delta)


@pytest.mark.asyncio
async def test_a_refused_delta_is_replaced_by_the_full_state(tmp_path, monkeypatch):
    messages = _messages(4)
    scene = make_changelog_scene(str(tmp_path), initial_serialize=_state(messages))
    await persist_test_mutation(scene)
    bogus = {"values_changed": {"root['name']": {"new_value": "not the scene"}}}
    monkeypatch.setattr(changelog, "_compute_delta", lambda prev, curr: bogus)
    messages.append(NarratorMessage(message="The lamp flickers."))
    scene.serialize = _state(messages)

    assert await persist_test_mutation(scene) == 1

    monkeypatch.undo()
    reconstructed = await reconstruct_scene_data(scene, to_rev=1)
    assert _json(reconstructed) == _json(scene.serialize)
    messages.append(NarratorMessage(message="The lamp goes dark."))
    scene.serialize = _state(messages)
    assert await persist_test_mutation(scene) == 2


@pytest.mark.asyncio
async def test_no_exact_delta_raises_and_keeps_the_baseline(tmp_path, monkeypatch):
    messages = _messages(4)
    scene = make_changelog_scene(str(tmp_path), initial_serialize=_state(messages))
    await persist_test_mutation(scene)
    monkeypatch.setattr(changelog, "_delta_reproduces_state", lambda *args: False)
    message = NarratorMessage(message="The lamp flickers.")
    scene.history.append(message)
    scene.serialize = _state([*messages, message])

    async with changelog.InMemoryChangelog(scene) as memory:
        baseline = memory.last_state
        with pytest.raises(changelog.ChangelogDeltaError):
            await memory.append_delta()

        assert memory.pending_count == 0
        assert memory.last_state is baseline
        assert message.rev == 0


@pytest.mark.asyncio
async def test_scene_save_writes_the_file_and_shows_the_error(tmp_path, monkeypatch):
    import talemate.tale_mate as tale_mate

    messages = _messages(4)
    scene = make_changelog_scene(str(tmp_path), initial_serialize=_state(messages))
    scene.name = "Diff"
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    await persist_test_mutation(scene)
    shown = []
    monkeypatch.setattr(
        tale_mate,
        "emit",
        lambda typ, *args, **kwargs: shown.append((typ, kwargs.get("status"))),
    )
    monkeypatch.setattr(changelog, "_delta_reproduces_state", lambda *args: False)
    scene.serialize = _state([*messages, NarratorMessage(message="The lamp.")])

    async with changelog.InMemoryChangelog(scene) as memory:
        scene._changelog = memory
        await scene.save(auto=True)

    with open(tmp_path / "scene.json") as f:
        assert json.load(f)["history"][-1]["message"] == "The lamp."
    assert ("status", "error") in shown
    assert scene.saved


@pytest.mark.asyncio
async def test_a_diff_error_is_replaced_by_the_full_state(tmp_path, monkeypatch):
    messages = _messages(4)
    scene = make_changelog_scene(str(tmp_path), initial_serialize=_state(messages))
    await persist_test_mutation(scene)

    def fail(prev, curr):
        raise TypeError("'int' object is not iterable")

    monkeypatch.setattr(changelog, "_compute_delta", fail)
    messages.append(NarratorMessage(message="The lamp flickers."))
    scene.serialize = _state(messages)

    assert await persist_test_mutation(scene) == 1
    reconstructed = await reconstruct_scene_data(scene, to_rev=1)
    assert _json(reconstructed) == _json(scene.serialize)


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [{}, 3])
async def test_divergence_check_reports_a_container_kind_change(tmp_path, stored):
    messages = _messages(4)
    scene = make_changelog_scene(
        str(tmp_path),
        initial_serialize=_state(messages, game_state={"variables": {"inv": []}}),
    )
    await persist_test_mutation(scene)
    messages.append(NarratorMessage(message="The lamp flickers."))
    scene.serialize = _state(messages, game_state={"variables": {"inv": []}})
    await persist_test_mutation(scene)
    # a latest snapshot that the chain does not reproduce, as a wrong delta
    # of 0.39.0 leaves it
    with open(_latest_path(scene)) as f:
        latest = json.load(f)
    latest["game_state"]["variables"]["inv"] = stored
    with open(_latest_path(scene), "w") as f:
        json.dump(latest, f)
    changelog._DIVERGENCE_CHECK_CACHE.clear()

    assert await check_chain_divergence(scene) == [
        "root['game_state']['variables']['inv']"
    ]
