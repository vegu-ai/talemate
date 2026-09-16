"""
Tests for the scene time migration on the load and changelog paths.

Scene time used to be persisted as ISO8601 durations ("P1M", "PT1H") and is
now integer seconds. Saves, changelog snapshots and changelog deltas written
before that switch are never rewritten on disk, so every path that feeds
persisted scene data back into scene state has to convert on read.

The fixtures under ``tests/data/scene_time_migration`` are hand-authored in
the OLD format: a scene file (revision 1), a base snapshot (revision 0), a
latest snapshot and a single delta between the two revisions. They stand in
for a scene that was last saved before the migration.
"""

import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

import talemate.agents.tts.voice_library as voice_library
import talemate.instance as instance
from _changelog_test_helpers import persist_test_mutation, make_changelog_scene
from conftest import MockScene, bootstrap_scene
from talemate.character import Character
from talemate.changelog import (
    InMemoryChangelog,
    _base_path,
    _compute_delta,
    _latest_path,
    _load_latest_scene_data,
    fork_scene_at_revision,
    reconstruct_cleanup,
    reconstruct_scene_data,
)
from talemate.history import add_history_entry, history_with_relative_time
from talemate.knowledge.chronology import fact_time
from talemate.load import SceneInitialization, load_scene_from_data
from talemate.load import new_scene as new_scene_data
from talemate.util.time import migrate_scene_time
from talemate.scene_message import SceneMessage, TimePassageMessage
from talemate.server.world_state_manager.shared_context import SharedContextMixin
from talemate.shared_context import SharedContext
from talemate.tale_mate import Scene

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "data", "scene_time_migration")
SCENE_FILE = "legacy-time-scene.json"

SHARED_CONTEXT_FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "data", "shared_context_migration"
)
SHARED_CONTEXT_FILE = "legacy-shared-context.json"
RELEASED_LINKED_WORLD = "released-linked-world.json"
FILE_TEXTS = {
    "harbor": "The harbor was quiet.",
    "tavern": "The tavern stays open all night.",
}
RECOVERED = {**FILE_TEXTS, "promise": "Kaira promised to return."}

MONTH = 2_592_000
HOUR = 3600
DAY = 86400

# Scene time the fixture's history adds up to: the last no-end archive entry
# ("P3M") plus both time passage messages ("PT1H" + "P1D").
EXPECTED_SCENE_TS = 3 * MONTH + HOUR + DAY

YEAR = 31_536_000

# scene.ts that the load of each shipped scene gave before `start_ts` existed
SHIPPED_SCENE_TS = {
    "infinity-quest-dynamic-scenario/infinity-quest.json": 28_512_000,
    "infinity-quest-dynamic-story-v2/infinity-quest.json": 31_104_000,
    "infinity-quest/infinity-quest.json": 31_104_000,
    "model-testing-harness/model-testing-harness.json": 27_900,
    "model-testing-harness/restore.json": 27_900,
}


def _read_fixture(name: str = SCENE_FILE) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), "r") as f:
        return json.load(f)


def _assert_scene_time_is_int(data: dict):
    assert isinstance(data["ts"], int)
    for message in data["history"]:
        if message["typ"] == "time":
            assert isinstance(message["ts"], int)
    for entry in data["archived_history"]:
        assert isinstance(entry["ts"], int)
    for layer in data["layered_history"]:
        for entry in layer:
            assert isinstance(entry["ts"], int)
            assert isinstance(entry["ts_start"], int)
            assert isinstance(entry["ts_end"], int)


def _digests(root: str) -> dict[str, str]:
    """Map of relative path -> sha256 for every file under ``root``."""
    digests = {}
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            with open(path, "rb") as f:
                digests[os.path.relpath(path, root)] = hashlib.sha256(
                    f.read()
                ).hexdigest()
    return digests


@pytest.fixture
def fixture_copy(tmp_path):
    """Copy of the fixture set the changelog tests may write into."""
    target = str(tmp_path / "legacy-scene")
    shutil.copytree(FIXTURE_DIR, target)
    return target


@pytest.fixture
def changelog_scene(fixture_copy):
    scene = make_changelog_scene(
        fixture_copy,
        filename=SCENE_FILE,
        initial_serialize=_read_fixture(),
    )
    return scene


# ---------------------------------------------------------------------------
# migrate_scene_time
# ---------------------------------------------------------------------------


class TestMigrateSceneTime:
    def test_converts_every_location(self):
        data = migrate_scene_time(_read_fixture())

        assert data["ts"] == 3 * MONTH + 25 * HOUR
        assert [m["ts"] for m in data["history"] if m["typ"] == "time"] == [HOUR, DAY]
        assert [e["ts"] for e in data["archived_history"]] == [
            MONTH,
            3 * MONTH,
            3 * MONTH + HOUR,
        ]

        layer_entry = data["layered_history"][0][0]
        assert layer_entry["ts"] == MONTH
        assert layer_entry["ts_start"] == MONTH
        assert layer_entry["ts_end"] == 3 * MONTH + HOUR

    def test_leaves_non_time_messages_alone(self):
        data = migrate_scene_time(_read_fixture())

        narrator = data["history"][0]
        assert narrator["typ"] == "narrator"
        assert "ts" not in narrator

    def test_idempotent(self):
        once = migrate_scene_time(_read_fixture())
        twice = migrate_scene_time(json.loads(json.dumps(once)))

        assert twice == once

    def test_missing_keys_stay_missing(self):
        data = migrate_scene_time(
            {
                "history": [{"typ": "time", "message": "later"}],
                "archived_history": [{"text": "no timestamps"}],
                "layered_history": [[{"text": "no timestamps", "ts": "PT1H"}]],
            }
        )

        assert "ts" not in data
        assert "ts" not in data["history"][0]
        assert data["archived_history"][0] == {"text": "no timestamps"}
        assert "ts_start" not in data["layered_history"][0][0]

    def test_null_timestamps_stay_null(self):
        data = migrate_scene_time(
            {"layered_history": [[{"ts": "PT1H", "ts_start": None, "ts_end": None}]]}
        )

        entry = data["layered_history"][0][0]
        assert entry["ts"] == HOUR
        assert entry["ts_start"] is None
        assert entry["ts_end"] is None

    def test_integers_pass_through(self):
        data = migrate_scene_time(
            {
                "ts": 900,
                "history": [{"typ": "time", "ts": 60}],
                "archived_history": [{"ts": 0, "ts_start": 0, "ts_end": 120}],
            }
        )

        assert data["ts"] == 900
        assert data["history"][0]["ts"] == 60
        assert data["archived_history"][0] == {"ts": 0, "ts_start": 0, "ts_end": 120}

    def test_empty_scene_data(self):
        assert migrate_scene_time({}) == {}

    @pytest.mark.parametrize(
        "scene_data",
        [
            {"ts": "not a duration"},
            {"history": [{"typ": "time", "ts": "1 hour"}]},
            {"archived_history": [{"text": "x", "ts": "P"}]},
            {"layered_history": [[{"text": "x", "ts_end": ""}]]},
        ],
    )
    def test_malformed_value_raises(self, scene_data):
        with pytest.raises(ValueError):
            migrate_scene_time(scene_data)

    def test_tolerant_mode_repairs_malformed_values(self):
        data = migrate_scene_time(
            {
                "ts": "not a duration",
                "history": [
                    {"typ": "time", "ts": "1 hour"},
                    {"typ": "time", "ts": "PT1H"},
                ],
                "archived_history": [{"text": "x", "ts": ""}],
                "layered_history": [[{"text": "x", "ts": "P1M", "ts_end": "P"}]],
            },
            tolerant=True,
        )

        # non-nullable locations fall back to zero
        assert data["ts"] == 0
        assert data["history"][0]["ts"] == 0
        assert data["archived_history"][0]["ts"] == 0
        # only the nullable range bounds fall back to null
        assert data["layered_history"][0][0]["ts_end"] is None
        # everything readable still migrates
        assert data["history"][1]["ts"] == HOUR
        assert data["layered_history"][0][0]["ts"] == MONTH

    def test_tolerant_mode_repairs_non_finite_values(self):
        data = migrate_scene_time(
            {
                "ts": float("inf"),
                "archived_history": [{"text": "x", "ts": float("nan")}],
                "layered_history": [[{"text": "x", "ts_end": float("-inf")}]],
            },
            tolerant=True,
        )

        assert data["ts"] == 0
        assert data["archived_history"][0]["ts"] == 0
        assert data["layered_history"][0][0]["ts_end"] is None


# ---------------------------------------------------------------------------
# Full scene load
# ---------------------------------------------------------------------------


@pytest.fixture
def new_scene(tmp_path, monkeypatch):
    """
    Each call gives a new scene, with the agent stack bound to it, that a
    legacy scene can be loaded into. Use the scenes one after another.
    """
    monkeypatch.setattr(
        Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)), raising=True
    )

    def create():
        scene = MockScene()
        bootstrap_scene(scene)
        scene.project_name = "legacy-time-scene"
        memory = instance.get_agent("memory")
        monkeypatch.setattr(memory, "set_db", _noop, raising=False)
        monkeypatch.setattr(memory, "get_document", _no_documents, raising=False)
        voice_library.VOICE_LIBRARY = voice_library.VoiceLibrary(voices={})
        return scene

    return create


@pytest.fixture
def load_env(new_scene):
    """Agent stack + scenes directory a legacy scene can be loaded into."""
    return new_scene()


async def _noop(*args, **kwargs):
    return None


async def _no_documents(*args, **kwargs):
    return {}


@pytest.mark.asyncio
async def test_load_scene_migrates_legacy_time(load_env):
    scene = await load_scene_from_data(load_env, _read_fixture(), name=SCENE_FILE)

    assert scene.ts == EXPECTED_SCENE_TS

    time_messages = [m for m in scene.history if isinstance(m, TimePassageMessage)]
    assert [m.ts for m in time_messages] == [HOUR, DAY]

    # Entries without an `end` index keep their persisted timestamp; the rest
    # are recomputed by fix_time().
    assert scene.archived_history[0]["ts"] == MONTH
    assert scene.archived_history[1]["ts"] == 3 * MONTH
    for entry in scene.archived_history:
        assert isinstance(entry["ts"], int)

    for layer in scene.layered_history:
        for entry in layer:
            assert isinstance(entry["ts"], int)
            assert isinstance(entry["ts_start"], int)
            assert isinstance(entry["ts_end"], int)


@pytest.mark.asyncio
async def test_a_save_without_scene_start_loads_as_before(load_env):
    scene = await load_scene_from_data(load_env, _read_fixture(), name=SCENE_FILE)

    # the scene starts at the newest static entry before the first summary
    assert scene.start_ts == 3 * MONTH
    assert scene.ts == EXPECTED_SCENE_TS
    assert [e["ts"] for e in scene.archived_history] == [
        MONTH,
        3 * MONTH,
        3 * MONTH + HOUR,
    ]
    assert [
        (e["ts"], e["ts_start"], e["ts_end"]) for e in scene.layered_history[0]
    ] == [(MONTH, MONTH, 3 * MONTH + HOUR)]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(SHIPPED_SCENE_TS))
async def test_shipped_scenes_load_as_before(load_env, path):
    scenes_dir = Path(__file__).parent.parent / "scenes"
    with open(scenes_dir / path) as f:
        data = json.load(f)
    assert "start_ts" not in data
    saved = migrate_scene_time(copy.deepcopy(data))["archived_history"]

    scene = await load_scene_from_data(load_env, data, name=os.path.basename(path))

    assert scene.ts == SHIPPED_SCENE_TS[path]
    assert [entry["ts"] for entry in scene.archived_history] == [
        entry["ts"] for entry in saved
    ]


@pytest.mark.asyncio
async def test_static_entry_offset_survives_a_reload(load_env):
    data = _read_fixture()
    data["archived_history"] = []
    data["layered_history"] = []
    scene = await load_scene_from_data(load_env, data, name=SCENE_FILE)
    assert scene.ts == HOUR + DAY

    await add_history_entry(scene, "The war ended.", offset=10 * MONTH)
    assert scene.ts == 10 * MONTH

    reloaded = await load_scene_from_data(
        load_env, json.loads(scene.json), name=SCENE_FILE
    )

    assert reloaded.ts == 10 * MONTH
    rows = history_with_relative_time(reloaded.archived_history, reloaded.ts)
    assert rows[0]["time"] == "10 Months ago"
    assert reloaded.start_ts == scene.start_ts == 10 * MONTH - HOUR - DAY


@pytest.mark.asyncio
async def test_load_scene_leaves_fixture_files_untouched(load_env):
    before = _digests(FIXTURE_DIR)
    await load_scene_from_data(load_env, _read_fixture(), name=SCENE_FILE)
    assert _digests(FIXTURE_DIR) == before


# ---------------------------------------------------------------------------
# Message id stability across save/load
# ---------------------------------------------------------------------------


def _fixture_with_gapped_ids() -> dict:
    """Scene data whose persisted history ids have holes (deleted messages)."""
    scene_data = _read_fixture()
    for idx, entry in enumerate(scene_data["history"]):
        entry["id"] = (idx + 1) * 10
    return scene_data


@pytest.mark.asyncio
async def test_load_preserves_history_message_ids(load_env):
    scene_data = _fixture_with_gapped_ids()
    scene = await load_scene_from_data(load_env, scene_data, name=SCENE_FILE)

    # Message ids are message identity for the changelog chain; a reload must
    # not renumber them.
    assert [m.id for m in scene.history] == [
        (idx + 1) * 10 for idx in range(len(scene_data["history"]))
    ]


@pytest.mark.asyncio
async def test_new_message_id_after_load_cannot_collide(load_env):
    scene_data = _fixture_with_gapped_ids()
    max_id = len(scene_data["history"]) * 10
    await load_scene_from_data(load_env, scene_data, name=SCENE_FILE)

    new_message = SceneMessage(message="brand new")
    assert new_message.id > max_id


@pytest.mark.asyncio
async def test_load_mixed_id_entries_do_not_collide(load_env):
    # A hand-edited or partially migrated file can mix id-bearing and idless
    # entries: an idless entry must not take a counter id that a later entry
    # preserves.
    scene_data = _read_fixture()
    history = scene_data["history"]
    assert len(history) >= 3
    for entry in history:
        entry.pop("id", None)
    history[-1]["id"] = 2

    scene = await load_scene_from_data(load_env, scene_data, name=SCENE_FILE)

    ids = [m.id for m in scene.history]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
    assert 2 in ids


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_context_migrates_static_history():
    shared = SharedContext(
        filepath=Path(SHARED_CONTEXT_FIXTURE_DIR) / SHARED_CONTEXT_FILE
    )
    await shared.init_from_file()

    assert [entry.ts for entry in shared.static_history] == [MONTH, 3 * MONTH + HOUR]
    for entry in shared.static_history:
        assert isinstance(entry.ts, int)


@pytest.mark.asyncio
async def test_load_scene_with_legacy_shared_context(load_env):
    shared_context_dir = Path(load_env.shared_context_dir)
    shared_context_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        os.path.join(SHARED_CONTEXT_FIXTURE_DIR, SHARED_CONTEXT_FILE),
        shared_context_dir,
    )

    scene_data = _read_fixture()
    scene_data["shared_context"] = SHARED_CONTEXT_FILE

    scene = await load_scene_from_data(load_env, scene_data, name=SCENE_FILE)

    assert [entry.ts for entry in scene.shared_context.static_history] == [
        MONTH,
        3 * MONTH + HOUR,
    ]
    # the shared static entries replace the scene's own static entries, the
    # summarized entry (the only one with an `end`) is kept and re-timed
    assert [entry["ts"] for entry in scene.archived_history[:2]] == [
        MONTH,
        3 * MONTH + HOUR,
    ]
    assert scene.archived_history[2]["end"] == 2
    for entry in scene.archived_history:
        assert isinstance(entry["ts"], int)
    # a save without `start_ts` starts at the newest shared static entry,
    # as the load did before `start_ts` existed
    assert scene.start_ts == 3 * MONTH + HOUR
    assert scene.ts == 3 * MONTH + DAY + 2 * HOUR
    assert scene.archived_history[2]["ts"] == 3 * MONTH + 2 * HOUR
    assert scene.layered_history[0][0]["ts_end"] == 3 * MONTH + 2 * HOUR


def _static_scene_data(
    start_ts: int | None, static: list[tuple[str, int]], **extra
) -> dict:
    """
    The fixture's history (passages of 1 hour and 1 day) with these static
    entries. A `start_ts` of None stands for a save from an older version.
    """
    data = _read_fixture()
    data["archived_history"] = [
        {"text": text, "ts": ts, "id": text} for text, ts in static
    ]
    data["layered_history"] = []
    if start_ts is not None:
        data["start_ts"] = start_ts
    data.update(extra)
    return data


def _with_fact(data: dict, ts: int) -> dict:
    data["world_state"] = {
        **data.get("world_state", {}),
        "facts": {
            "F1": {
                "id": "F1",
                "text": "Kaira checked the hull.",
                "ts": ts,
                "last_seen_ts": ts,
                "source": "manual",
            }
        },
    }
    return data


def _static_ages(scene) -> list[tuple[str, str]]:
    return [
        (row["text"], row["time"])
        for row in history_with_relative_time(scene.archived_history, scene.ts)
        if row["end"] is None
    ]


def _timeline(scene) -> tuple:
    """Every stored time of the scene, as plain values."""
    return (
        scene.start_ts,
        scene.ts,
        [(entry["text"], entry["ts"]) for entry in scene.archived_history],
        [
            [
                (entry.get("ts"), entry.get("ts_start"), entry.get("ts_end"))
                for entry in layer
            ]
            for layer in scene.layered_history
        ],
        {
            fact.id: (fact.ts, fact.last_seen_ts)
            for fact in scene.world_state.facts.values()
        },
    )


async def _load(new_scene, data: dict):
    return await load_scene_from_data(new_scene(), copy.deepcopy(data), name=SCENE_FILE)


async def _write_shared_context(scene) -> str:
    shared_dir = Path(scene.shared_context_dir)
    shared_dir.mkdir(parents=True, exist_ok=True)
    shared = SharedContext(
        filepath=shared_dir / "world.json", share_static_history=True
    )
    await shared.init_from_scene(scene, write=True)
    return shared.filename


async def _save(scene) -> dict:
    """What `Scene.save` writes: the shared context first, then the scene."""
    if scene.shared_context:
        await scene.shared_context.commit_changes(scene)
    return json.loads(scene.json)


@pytest.mark.asyncio
async def test_a_new_scene_places_shared_static_history_from_its_start(new_scene):
    writer = await _load(
        new_scene,
        _static_scene_data(10 * YEAR, [("war", 0), ("lighthouse", 5 * YEAR)]),
    )
    filename = await _write_shared_context(writer)

    scene = await _load(new_scene, _static_scene_data(0, [], shared_context=filename))

    assert _static_ages(scene) == [
        ("war", "10 Years ago"),
        ("lighthouse", "5 Years ago"),
    ]
    assert scene.start_ts == 10 * YEAR
    before = _timeline(scene)
    reloaded = await _load(new_scene, await _save(scene))
    assert _timeline(reloaded) == before


@pytest.mark.asyncio
async def test_an_older_shared_entry_keeps_every_age_in_the_other_scene(new_scene):
    first_data = _with_fact(
        _static_scene_data(10 * YEAR, [("war", 0), ("lighthouse", 5 * YEAR)]),
        10 * YEAR + DAY,
    )
    first = await _load(new_scene, first_data)
    assert fact_time(first, first.world_state.facts["F1"]) == "1 Hour ago"
    first_data["shared_context"] = await _write_shared_context(first)

    second = await _load(
        new_scene, _static_scene_data(0, [], shared_context="world.json")
    )
    await add_history_entry(second, "ruins", offset=20 * YEAR)
    await _save(second)

    first = await _load(new_scene, first_data)

    assert _static_ages(first) == [
        ("ruins", "20 Years ago"),
        ("war", "10 Years ago"),
        ("lighthouse", "5 Years ago"),
    ]
    assert fact_time(first, first.world_state.facts["F1"]) == "1 Hour ago"
    before = _timeline(first)
    reloaded = await _load(new_scene, await _save(first))
    assert _timeline(reloaded) == before


@pytest.mark.asyncio
async def test_an_older_save_keeps_the_start_of_a_shared_file_from_this_version(
    new_scene,
):
    writer_data = _static_scene_data(10 * YEAR, [("war", 0), ("lighthouse", 5 * YEAR)])
    writer = await _load(new_scene, writer_data)
    writer_data["shared_context"] = await _write_shared_context(writer)
    writer_timeline = _timeline(writer)

    # an older version started this scene at its newest static entry (5y)
    older_data = _with_fact(
        _static_scene_data(
            None,
            [("war", 0), ("lighthouse", 5 * YEAR)],
            shared_context="world.json",
        ),
        5 * YEAR + DAY,
    )
    older = await _load(new_scene, older_data)

    assert _static_ages(older) == [
        ("war", "10 Years ago"),
        ("lighthouse", "5 Years ago"),
    ]
    assert older.start_ts == 10 * YEAR
    assert fact_time(older, older.world_state.facts["F1"]) == "1 Hour ago"
    await _save(older)

    writer = await _load(new_scene, writer_data)
    assert _timeline(writer) == writer_timeline
    assert _static_ages(writer) == [
        ("war", "10 Years ago"),
        ("lighthouse", "5 Years ago"),
    ]


@pytest.mark.asyncio
async def test_a_shared_entry_from_the_writers_story_survives_a_round_trip(
    new_scene,
):
    # storm: 1 hour ago in a scene with 1 day and 1 hour of passages
    writer_data = _static_scene_data(
        10 * YEAR, [("war", 0), ("storm", 10 * YEAR + DAY)]
    )
    writer = await _load(new_scene, writer_data)
    writer_data["shared_context"] = await _write_shared_context(writer)
    writer_timeline = _timeline(writer)
    assert _static_ages(writer) == [("war", "10 Years ago"), ("storm", "1 Hour ago")]

    # fewer passages: only the hour, and a summary at that hour
    data = _static_scene_data(0, [], shared_context="world.json")
    data["history"] = data["history"][:3]
    data["archived_history"] = [
        {"text": "They left the station.", "ts": HOUR, "start": 0, "end": 2, "id": "s1"}
    ]
    scene = await _load(new_scene, data)

    # each entry keeps its distance from the start, also storm, which is now
    # later than this scene's clock (#647)
    start_ts, _, entries, _, _ = _timeline(scene)
    assert [(text, ts - start_ts) for text, ts in entries[:2]] == [
        ("war", -10 * YEAR),
        ("storm", DAY),
    ]
    await _save(scene)

    writer = await _load(new_scene, writer_data)
    assert _timeline(writer) == writer_timeline
    assert _static_ages(writer) == [("war", "10 Years ago"), ("storm", "1 Hour ago")]


@pytest.mark.asyncio
async def test_a_shared_start_moves_the_state_that_arrives_after_it(new_scene):
    """The state loaded after the shared step follows the moved start (#640)."""

    writer_data = _static_scene_data(10 * YEAR, [("war", 0), ("lighthouse", 5 * YEAR)])
    writer = await _load(new_scene, writer_data)
    await _write_shared_context(writer)

    # an older save: its own start is the newest static entry, 5 years, so the
    # shared file's start moves this scene's timeline forward by 5 years
    data = _static_scene_data(
        None, [("war", 0), ("lighthouse", 5 * YEAR)], shared_context="world.json"
    )
    data["format_version"] = 1
    data["knowledge_eligibility"] = "perception"
    data["knowledge"] = {"last_order": 2, "disclosures": []}
    data["intro_knowledge"] = {
        "revision": 1,
        "content_digest": hashlib.sha256(data["intro"].encode()).hexdigest(),
        "acquired": {"order": 1, "ts": 5 * YEAR + HOUR},
        "views": [],
    }
    passage = "The reactor runs hot."
    data["world_state"] = {
        **data.get("world_state", {}),
        "knowledge": [
            {
                "id": "e1",
                "character": "Kaira",
                "target": "F1",
                "kind": "grant",
                "source": "manual",
                "ts": 5 * YEAR + DAY,
            }
        ],
        # a pin made from the chat records the scene time
        "manual_context": {
            "promise": {
                "id": "promise",
                "text": "Kaira promised to return",
                "meta": {"ts": 5 * YEAR + DAY, "pin_only": True},
            }
        },
        # a world entry that is inserted directly keeps its own passage
        "reinforce": [
            {
                "question": "reactor",
                "answer": passage,
                "insert": "all-context",
                "perspective_source": {
                    "typ": "reinforcement",
                    "id": 9001,
                    "message": passage,
                    "source": "ai",
                    "knowledge": {
                        "revision": 1,
                        "content_digest": hashlib.sha256(passage.encode()).hexdigest(),
                        "acquired": {"order": 2, "ts": 5 * YEAR + DAY},
                        "views": [],
                    },
                },
            }
        ],
    }

    scene = await _load(new_scene, data)

    assert scene.start_ts == 10 * YEAR
    assert scene.intro_knowledge.acquired.ts == 10 * YEAR + HOUR
    assert scene.intro_knowledge.acquired.order == 1
    assert [edge.ts for edge in scene.world_state.knowledge] == [10 * YEAR + DAY]
    acquired = scene.world_state.reinforce[0].perspective_source.knowledge.acquired
    assert (acquired.ts, acquired.order) == (10 * YEAR + DAY, 2)
    promise = scene.world_state.manual_context["promise"]
    assert promise.meta["ts"] == 10 * YEAR + DAY


@pytest.mark.asyncio
async def test_a_new_linked_scene_keeps_the_shared_static_history(new_scene):
    writer_data = _static_scene_data(10 * YEAR, [("war", 0), ("lighthouse", 5 * YEAR)])
    writer = await _load(new_scene, writer_data)
    writer_data["shared_context"] = await _write_shared_context(writer)
    writer_timeline = _timeline(writer)

    # Shared World, "Create new scene": $NEW_SCENE$ data loaded with a reset
    data = new_scene_data(SceneInitialization(shared_context="world.json"))
    data["project_name"] = writer.project_name
    scene = await load_scene_from_data(new_scene(), data, reset=True, empty=True)

    assert _static_ages(scene) == [
        ("war", "10 Years ago"),
        ("lighthouse", "5 Years ago"),
    ]
    assert (scene.start_ts, scene.ts) == (10 * YEAR, 10 * YEAR)

    await _save(scene)

    shared = SharedContext(filepath=Path(writer.shared_context_dir) / "world.json")
    await shared.init_from_file()
    assert [(entry.text, entry.ts) for entry in shared.static_history] == [
        ("war", 0),
        ("lighthouse", 5 * YEAR),
    ]

    writer = await _load(new_scene, writer_data)
    assert _timeline(writer) == writer_timeline
    assert _static_ages(writer) == [
        ("war", "10 Years ago"),
        ("lighthouse", "5 Years ago"),
    ]


# a writer start of None is the released shape: neither the save nor the shared
# file has a `start_ts`
@pytest.mark.parametrize("writer_start", [10 * YEAR, None])
@pytest.mark.asyncio
async def test_a_new_linked_scene_reads_a_shared_file_without_a_start(
    new_scene, writer_start
):
    writer_data = _static_scene_data(
        writer_start, [("war", 0), ("lighthouse", 5 * YEAR)]
    )
    writer = await _load(new_scene, writer_data)
    writer_data["shared_context"] = await _write_shared_context(writer)

    # `start_ts` came with this version; every shared file written before it
    # gives the scene start with its newest static entry
    path = Path(writer.shared_context_dir) / "world.json"
    shared_data = json.loads(path.read_text())
    del shared_data["start_ts"]
    path.write_text(json.dumps(shared_data))

    # what the writer reads from that file, with no new scene involved
    writer_timeline = _timeline(await _load(new_scene, writer_data))

    # Shared World, "Create new scene"
    data = new_scene_data(SceneInitialization(shared_context="world.json"))
    data["project_name"] = writer.project_name
    scene = await load_scene_from_data(new_scene(), data, reset=True, empty=True)

    assert (scene.start_ts, scene.ts) == (5 * YEAR, 5 * YEAR)
    assert _static_ages(scene) == [("war", "5 Years ago"), ("lighthouse", "Recently")]

    await _save(scene)

    shared = SharedContext(filepath=path)
    await shared.init_from_file()
    assert shared.start_ts == 5 * YEAR
    assert [(entry.text, entry.ts) for entry in shared.static_history] == [
        ("war", 0),
        ("lighthouse", 5 * YEAR),
    ]

    # the new scene's first save costs the writer nothing
    assert _timeline(await _load(new_scene, writer_data)) == writer_timeline


@pytest.mark.asyncio
async def test_a_scene_that_loads_its_own_shared_file_changes_nothing(new_scene):
    data = _with_fact(
        _static_scene_data(10 * YEAR, [("war", 0), ("storm", 10 * YEAR + DAY)]),
        10 * YEAR + DAY,
    )
    writer = await _load(new_scene, data)
    data["shared_context"] = await _write_shared_context(writer)
    before = _timeline(writer)

    scene = await _load(new_scene, data)

    assert _timeline(scene) == before
    assert await scene.shared_context.update_to_scene(scene) is False
    assert _timeline(scene) == before


@pytest.mark.asyncio
async def test_linking_in_session_moves_the_history_in_memory(new_scene, monkeypatch):
    writer = await _load(
        new_scene,
        _static_scene_data(10 * YEAR, [("war", 0), ("lighthouse", 5 * YEAR)]),
    )
    filename = await _write_shared_context(writer)

    # a scene of this version with a summary, a layer and a fact
    data = _with_fact(_read_fixture(), 3 * MONTH + DAY)
    data["start_ts"] = 3 * MONTH
    scene = await _load(new_scene, data)
    rows = history_with_relative_time(scene.archived_history, scene.ts)
    layer = history_with_relative_time(scene.layered_history[0], scene.ts)
    summary_age = [row["time"] for row in rows if row["end"] is not None]
    fact_age = fact_time(scene, scene.world_state.facts["F1"])
    assert fact_age == "1 Hour ago"

    reimported = []

    async def reimport(scene, **kwargs):
        reimported.append(scene)

    monkeypatch.setattr(
        "talemate.server.world_state_manager.shared_context.reimport_history",
        reimport,
    )
    mixin = _SharedContextHandler(scene)

    await mixin.handle_select_shared_context({"filepath": filename})

    assert mixin.done
    assert reimported == [scene]
    assert _static_ages(scene) == [
        ("war", "10 Years ago"),
        ("lighthouse", "5 Years ago"),
    ]
    rows = history_with_relative_time(scene.archived_history, scene.ts)
    assert [row["time"] for row in rows if row["end"] is not None] == summary_age
    assert [
        row["time"]
        for row in history_with_relative_time(scene.layered_history[0], scene.ts)
    ] == [row["time"] for row in layer]
    assert fact_time(scene, scene.world_state.facts["F1"]) == fact_age


class _SharedContextHandler(SharedContextMixin):
    def __init__(self, scene):
        self.scene = scene
        self.websocket_handler = Mock()
        self.done = False

    async def signal_operation_done(self):
        self.done = True

    async def signal_operation_failed(self, message):
        raise AssertionError(message)


@pytest.mark.asyncio
async def test_an_older_shared_file_puts_its_newest_entry_at_the_scene_start():
    shared = SharedContext(
        filepath=Path(SHARED_CONTEXT_FIXTURE_DIR) / SHARED_CONTEXT_FILE
    )
    await shared.init_from_file()
    assert shared.start_ts is None
    scene = Scene()

    await shared.update_to_scene(scene)

    assert [entry["ts"] for entry in scene.archived_history] == [0, 2 * MONTH + HOUR]
    assert (scene.start_ts, scene.ts) == (2 * MONTH + HOUR, 2 * MONTH + HOUR)


@pytest.mark.asyncio
async def test_shared_context_read_leaves_fixture_file_untouched():
    before = _digests(SHARED_CONTEXT_FIXTURE_DIR)
    shared = SharedContext(
        filepath=Path(SHARED_CONTEXT_FIXTURE_DIR) / SHARED_CONTEXT_FILE
    )
    await shared.init_from_file()
    assert _digests(SHARED_CONTEXT_FIXTURE_DIR) == before


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconstruct_base_revision_migrates(changelog_scene):
    data = await reconstruct_scene_data(changelog_scene, to_rev=0)

    assert data["ts"] == 3 * MONTH + HOUR
    assert [m["ts"] for m in data["history"] if m["typ"] == "time"] == [HOUR]
    assert [e["ts"] for e in data["archived_history"]] == [MONTH, 3 * MONTH]


@pytest.mark.asyncio
async def test_reconstruct_delta_revision_migrates(changelog_scene):
    data = await reconstruct_scene_data(changelog_scene, to_rev=1)

    assert data["ts"] == 3 * MONTH + 25 * HOUR
    assert [m["ts"] for m in data["history"] if m["typ"] == "time"] == [HOUR, DAY]
    assert [e["ts"] for e in data["archived_history"]] == [
        MONTH,
        3 * MONTH,
        3 * MONTH + HOUR,
    ]
    layer_entry = data["layered_history"][0][0]
    assert (layer_entry["ts"], layer_entry["ts_start"], layer_entry["ts_end"]) == (
        MONTH,
        MONTH,
        3 * MONTH + HOUR,
    )


@pytest.mark.asyncio
async def test_reconstruct_leaves_changelog_files_untouched(changelog_scene):
    before = _digests(changelog_scene.save_dir)
    await reconstruct_scene_data(changelog_scene, to_rev=0)
    await reconstruct_scene_data(changelog_scene, to_rev=1)
    assert _digests(changelog_scene.save_dir) == before


@pytest.mark.asyncio
async def test_fork_writes_migrated_scene(changelog_scene):
    fork_path = await fork_scene_at_revision(changelog_scene, 0, "forked")

    with open(fork_path, "r") as f:
        forked = json.load(f)

    assert forked["ts"] == 3 * MONTH + HOUR
    assert [e["ts"] for e in forked["archived_history"]] == [MONTH, 3 * MONTH]
    assert forked["immutable_save"] is False


@pytest.mark.asyncio
async def test_legacy_latest_snapshot_does_not_diff_against_migrated_scene(
    changelog_scene,
):
    """A migrated scene must not diff against its pre-migration snapshot.

    The latest snapshot is the baseline new deltas are computed from. Left
    unmigrated, every scene time field would show up as a change on the first
    save after the migration.
    """
    changelog_scene.serialize = migrate_scene_time(_read_fixture())

    async with InMemoryChangelog(changelog_scene) as changelog:
        assert await changelog.append_delta({"action": "no_op"}) is None

    # ... while a real change still produces a delta that carries integers.
    changelog_scene.serialize = migrate_scene_time(_read_fixture())
    changelog_scene.serialize["ts"] = EXPECTED_SCENE_TS + DAY

    async with InMemoryChangelog(changelog_scene) as changelog:
        assert await changelog.append_delta({"action": "time_passage"}) == 1

    delta = changelog.pending_deltas[0]["delta"]
    assert delta["values_changed"]["root['ts']"]["new_value"] == EXPECTED_SCENE_TS + DAY


@pytest.mark.asyncio
async def test_delta_written_after_migration_reconstructs(changelog_scene):
    """A changelog may mix legacy and migrated revisions.

    Reconstruction only survives that because the migration runs after every
    delta has been applied: an integer delta written post-migration is
    applied on top of ISO8601 values, and the whole result is converted at
    the end.
    """
    scene_data = migrate_scene_time(_read_fixture())
    scene_data["history"].append(
        {
            "typ": "time",
            "message": "A day passes.",
            "ts": DAY,
            "source": "manual",
            "flags": 0,
            "id": 5,
        }
    )
    scene_data["ts"] = 3 * MONTH + 25 * HOUR + DAY
    changelog_scene.serialize = scene_data

    assert await persist_test_mutation(changelog_scene, {"action": "time_passage"}) == 2

    latest = await reconstruct_scene_data(changelog_scene)
    assert latest["ts"] == 3 * MONTH + 25 * HOUR + DAY
    assert [m["ts"] for m in latest["history"] if m["typ"] == "time"] == [
        HOUR,
        DAY,
        DAY,
    ]
    _assert_scene_time_is_int(latest)

    # the legacy revisions still reconstruct as integers
    for to_rev in (0, 1):
        _assert_scene_time_is_int(await reconstruct_scene_data(changelog_scene, to_rev))


@pytest.mark.asyncio
async def test_reconstruct_cleanup_repairs_damaged_scene_time():
    """Reconstruction repairs damaged time values instead of aborting.

    Deltas are applied with `force=True`, so a reconstructed revision can carry
    values no parser accepts. Fork and preview have no way to recover from an
    exception here, so the migration repairs alongside the other
    reconstruction repairs.
    """
    data = _read_fixture()
    data["ts"] = ""
    data["history"][1]["ts"] = "1 hour"
    data["archived_history"][0]["ts"] = ""
    data["layered_history"][0][0]["ts_end"] = "P"

    result = await reconstruct_cleanup(data)

    assert result["ts"] == 0
    assert result["history"][1]["ts"] == 0
    assert result["archived_history"][0]["ts"] == 0
    assert result["layered_history"][0][0]["ts_end"] is None

    # the rest of the timeline reconstructs untouched
    assert result["history"][3]["ts"] == DAY
    assert [e["ts"] for e in result["archived_history"][1:]] == [
        3 * MONTH,
        3 * MONTH + HOUR,
    ]
    assert result["layered_history"][0][0]["ts"] == MONTH
    assert result["name"] == "Legacy Time Scene"


@pytest.mark.asyncio
async def test_repaired_reconstruction_loads_and_commits(load_env, monkeypatch):
    """A repaired revision has to survive the load that follows a fork.

    A fork writes the reconstructed data to a new scene file, and the load
    that follows commits it to memory. `ArchiveEntry.ts` is not nullable, so
    an entry repaired to null would make the forked scene unloadable.
    """
    data = _read_fixture()
    data["archived_history"][0]["ts"] = ""

    repaired = await reconstruct_cleanup(data)
    assert repaired["archived_history"][0]["ts"] == 0

    committed = []

    async def _record(items):
        committed.extend(items)

    memory = instance.get_agent("memory")
    monkeypatch.setattr(memory, "drop_db", lambda: None, raising=False)
    monkeypatch.setattr(memory, "add_many", _record)

    scene = await load_scene_from_data(load_env, repaired, name=SCENE_FILE)
    await scene.commit_to_memory()

    assert scene.archived_history[0]["ts"] == 0
    for entry in scene.archived_history:
        assert isinstance(entry["ts"], int)

    assert [entry["meta"]["ts"] for entry in committed][:2] == [0, 3 * MONTH]


@pytest.mark.asyncio
async def test_reconstruct_survives_damaged_base_snapshot(changelog_scene):
    base_path = _base_path(changelog_scene)
    with open(base_path, "r") as f:
        base_data = json.load(f)
    base_data["archived_history"][0]["ts"] = ""
    with open(base_path, "w") as f:
        json.dump(base_data, f)

    data = await reconstruct_scene_data(changelog_scene, to_rev=0)

    assert data["archived_history"][0]["ts"] == 0
    assert data["archived_history"][1]["ts"] == 3 * MONTH
    assert data["ts"] == 3 * MONTH + HOUR


def test_load_latest_scene_data_survives_damaged_timestamp(changelog_scene):
    """The latest snapshot is a fallback-able optimization, not a hard input."""
    latest_path = _latest_path(changelog_scene)
    with open(latest_path, "r") as f:
        latest_data = json.load(f)
    latest_data["archived_history"][0]["ts"] = ""
    with open(latest_path, "w") as f:
        json.dump(latest_data, f)

    data = _load_latest_scene_data(changelog_scene)

    assert data is not None
    assert data["archived_history"][0]["ts"] == 0
    assert data["ts"] == 3 * MONTH + 25 * HOUR


def test_unmigrated_baseline_would_diff_every_timestamp():
    """Guards the premise of the migration above: the raw legacy snapshot and
    the migrated scene data differ on every scene time field."""
    delta = _compute_delta(_read_fixture(), migrate_scene_time(_read_fixture()))

    changed = set(delta["values_changed"])
    assert "root['ts']" in changed
    assert "root['archived_history'][0]['ts']" in changed
    assert "root['history'][1]['ts']" in changed
    assert "root['layered_history'][0][0]['ts_end']" in changed


def _with_pin(data: dict, ts, shared: bool = False) -> dict:
    data["world_state"] = {
        **data.get("world_state", {}),
        "manual_context": {
            "promise": {
                "id": "promise",
                "text": "Kaira promised to return",
                "meta": {
                    "ts": ts,
                    "pin_only": True,
                    "source": "manual",
                    "typ": "world_state",
                },
                "shared": shared,
            }
        },
    }
    return data


def _pin_ts(world_state) -> int | None:
    return world_state.manual_context["promise"].meta["ts"]


# a released version stored a chat pin with the scene time of that version,
# an ISO 8601 duration
@pytest.mark.parametrize("saved, loaded", [("P1DT2H", DAY + 2 * HOUR), ("soon", None)])
@pytest.mark.asyncio
async def test_a_released_chat_pin_loads_and_follows_a_history_shift(
    new_scene, saved, loaded
):
    scene = await _load(new_scene, _with_pin(_static_scene_data(None, []), saved))

    assert _pin_ts(scene.world_state) == loaded

    await add_history_entry(scene, "the flood", offset=scene.ts + YEAR)

    assert _pin_ts(scene.world_state) == (None if loaded is None else loaded + YEAR)


@pytest.mark.asyncio
async def test_a_released_shared_file_pin_is_read_as_seconds(tmp_path):
    path = tmp_path / "world.json"
    data = _with_pin({}, "P1D", shared=True)
    path.write_text(json.dumps({"character_data": {}, **data}))

    shared = await SharedContext(filepath=path).init_from_file()

    assert _pin_ts(shared.world_state) == DAY


def _shared_pin_writer_data():
    """Writer start W = 10 years, a static entry at 0, a shared pin at W + 1 day."""
    return _with_pin(
        _static_scene_data(10 * YEAR, [("war", 0)]), 10 * YEAR + DAY, shared=True
    )


async def _shared_file_pin_ts(writer) -> int:
    shared = SharedContext(filepath=Path(writer.shared_context_dir) / "world.json")
    await shared.init_from_file()
    return _pin_ts(shared.world_state)


@pytest.mark.asyncio
async def test_a_new_linked_scene_keeps_the_writers_shared_pin_time(new_scene):
    writer = await _load(new_scene, _shared_pin_writer_data())
    await _write_shared_context(writer)

    data = new_scene_data(SceneInitialization(shared_context="world.json"))
    data["project_name"] = writer.project_name
    scene = await load_scene_from_data(new_scene(), data, reset=True, empty=True)

    assert scene.start_ts == 10 * YEAR
    assert _pin_ts(scene.world_state) == 10 * YEAR + DAY

    await _save(scene)

    assert await _shared_file_pin_ts(writer) == 10 * YEAR + DAY


@pytest.mark.asyncio
async def test_linking_in_session_keeps_the_writers_shared_pin_time(
    new_scene, monkeypatch
):
    writer = await _load(new_scene, _shared_pin_writer_data())
    filename = await _write_shared_context(writer)
    reader_data = _static_scene_data(0, [])
    reader_data["world_state"] = {
        "manual_context": {
            "lamp": {
                "id": "lamp",
                "text": "The lamp was lit",
                "meta": {"ts": HOUR, "source": "manual", "typ": "world_state"},
            }
        }
    }
    scene = await _load(new_scene, reader_data)
    monkeypatch.setattr(scene, "load_active_pins", _noop)

    await _SharedContextHandler(scene).handle_select_shared_context(
        {"filepath": filename}
    )

    assert scene.start_ts == 10 * YEAR
    assert _pin_ts(scene.world_state) == 10 * YEAR + DAY
    assert scene.world_state.manual_context["lamp"].meta["ts"] == 10 * YEAR + HOUR
    assert _pin_ts(scene.shared_context.world_state) == 10 * YEAR + DAY

    await _save(scene)

    assert await _shared_file_pin_ts(writer) == 10 * YEAR + DAY


async def _shared_file(writer) -> SharedContext:
    shared = SharedContext(filepath=Path(writer.shared_context_dir) / "world.json")
    return await shared.init_from_file()


@pytest.mark.asyncio
async def test_a_normal_load_takes_the_entry_another_linked_scene_shared(new_scene):
    founder = await _load(new_scene, _static_scene_data(10 * YEAR, []))
    filename = await _write_shared_context(founder)
    reader_data = _static_scene_data(10 * YEAR, [], shared_context=filename)
    writer = await _load(
        new_scene,
        _with_pin(_static_scene_data(10 * YEAR, [], shared_context=filename), YEAR),
    )
    await writer.world_state_manager.set_world_entry_shared("promise", True)
    await _save(writer)

    assert "promise" in (await _shared_file(writer)).world_state.manual_context

    scene = await _load(new_scene, reader_data)

    assert scene.world_state.manual_context["promise"].shared
    assert _pin_ts(scene.world_state) == YEAR

    await _save(scene)

    assert "promise" in (await _shared_file(writer)).world_state.manual_context


@pytest.mark.asyncio
async def test_a_normal_load_keeps_the_writers_shared_pin_time(new_scene):
    writer = await _load(new_scene, _shared_pin_writer_data())
    filename = await _write_shared_context(writer)
    reader_data = _static_scene_data(0, [], shared_context=filename)
    reader_data["world_state"] = {
        "manual_context": {
            "lamp": {
                "id": "lamp",
                "text": "The lamp was lit",
                "meta": {"ts": HOUR, "source": "manual", "typ": "world_state"},
            }
        }
    }

    scene = await _load(new_scene, reader_data)

    assert scene.start_ts == 10 * YEAR
    assert _pin_ts(scene.world_state) == 10 * YEAR + DAY
    assert scene.world_state.manual_context["lamp"].meta["ts"] == 10 * YEAR + HOUR

    reloaded = await _load(new_scene, await _save(scene))

    assert await _shared_file_pin_ts(writer) == 10 * YEAR + DAY
    assert reloaded.start_ts == 10 * YEAR
    assert _pin_ts(reloaded.world_state) == 10 * YEAR + DAY
    assert reloaded.world_state.manual_context["lamp"].meta["ts"] == 10 * YEAR + HOUR


@pytest.mark.asyncio
async def test_a_normal_load_removes_an_entry_the_shared_file_no_longer_holds(
    new_scene,
):
    founder = await _load(new_scene, _static_scene_data(10 * YEAR, []))
    filename = await _write_shared_context(founder)
    data = _with_pin(
        _static_scene_data(10 * YEAR, [], shared_context=filename), YEAR, shared=True
    )
    data["world_state"]["manual_context"]["lamp"] = {
        "id": "lamp",
        "text": "The lamp was lit",
        "meta": {"ts": HOUR, "source": "manual", "typ": "world_state"},
    }

    scene = await _load(new_scene, data)

    assert list(scene.world_state.manual_context) == ["lamp"]

    await _save(scene)

    assert (await _shared_file(founder)).world_state.manual_context == {}


@pytest.mark.asyncio
async def test_a_normal_load_takes_the_character_another_linked_scene_shared(
    new_scene,
):
    founder = await _load(new_scene, _static_scene_data(10 * YEAR, []))
    filename = await _write_shared_context(founder)
    shared = await _shared_file(founder)
    shared.character_data["Mara"] = Character(
        name="Mara", description="A ferry pilot.", shared=True
    )
    await shared.write_to_file()

    scene = await _load(
        new_scene, _static_scene_data(10 * YEAR, [], shared_context=filename)
    )

    assert scene.character_data["Mara"].description == "A ferry pilot."

    await _save(scene)

    assert "Mara" in (await _shared_file(founder)).character_data


async def _shared_promise_file(new_scene) -> str:
    writer = await _load(
        new_scene, _with_pin(_static_scene_data(10 * YEAR, []), YEAR, shared=True)
    )
    return await _write_shared_context(writer)


@pytest.mark.asyncio
async def test_a_shared_entry_replaces_a_private_entry_with_the_same_id_on_a_normal_load(
    new_scene,
):
    filename = await _shared_promise_file(new_scene)
    data = _with_pin(_static_scene_data(10 * YEAR, [], shared_context=filename), HOUR)
    data["world_state"]["manual_context"]["promise"]["text"] = (
        "Kaira kept it to herself"
    )

    scene = await _load(new_scene, data)

    entry = scene.world_state.manual_context["promise"]
    assert (entry.text, entry.shared, entry.meta["ts"]) == (
        "Kaira promised to return",
        True,
        YEAR,
    )

    await _save(scene)

    shared = await _shared_file(scene)
    assert (
        shared.world_state.manual_context["promise"].text == "Kaira promised to return"
    )


@pytest.mark.parametrize(
    "saved_text, kept", [("Kaira promised to return", True), ("An older text", False)]
)
@pytest.mark.asyncio
async def test_a_normal_load_keeps_a_shared_entrys_reinforcement_only_for_the_same_text(
    new_scene, saved_text, kept
):
    filename = await _shared_promise_file(new_scene)
    data = _with_pin(
        _static_scene_data(10 * YEAR, [], shared_context=filename), YEAR, shared=True
    )
    promise = data["world_state"]["manual_context"]["promise"]
    promise["text"] = saved_text
    promise["reinforcement"] = {"source_id": None}

    scene = await _load(new_scene, data)

    reinforcement = scene.world_state.manual_context["promise"].reinforcement
    assert (reinforcement is not None) is kept


def _released_entry(id: str, text: str, shared: bool = True) -> dict:
    return {
        "id": id,
        "text": text,
        "meta": {"source": "manual", "typ": "world_state"},
        "shared": shared,
    }


def _released_linked_save(*entries: dict) -> dict:
    data = _static_scene_data(None, [], shared_context=RELEASED_LINKED_WORLD)
    data["world_state"] = {"manual_context": {entry["id"]: entry for entry in entries}}
    return data


async def _released_linked_world(scene) -> SharedContext:
    shared_dir = Path(scene.shared_context_dir)
    shared_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        os.path.join(SHARED_CONTEXT_FIXTURE_DIR, RELEASED_LINKED_WORLD), shared_dir
    )
    return SharedContext(filepath=shared_dir / RELEASED_LINKED_WORLD)


def _texts(world_state) -> dict[str, str]:
    return {id: entry.text for id, entry in world_state.manual_context.items()}


def _released_holding_save() -> dict:
    # a released save that holds "promise", which another linked scene's save
    # took out of the file, and an older "harbor" text than the file
    return _released_linked_save(
        _released_entry("harbor", "The harbor flooded."),
        _released_entry("promise", "Kaira promised to return."),
        _released_entry("lamp", "The lamp was lit.", shared=False),
    )


def _released_other_save() -> dict:
    return _released_linked_save(_released_entry("harbor", "The harbor was quiet."))


def _shared_texts(scene) -> dict[str, str]:
    return {
        id: entry.text
        for id, entry in scene.world_state.manual_context.items()
        if entry.shared
    }


@pytest.mark.parametrize(
    "other_scene_first, expected",
    [(None, RECOVERED), ("load", RECOVERED), ("save", FILE_TEXTS)],
)
@pytest.mark.asyncio
async def test_an_unmarked_shared_file_takes_the_shared_entries_it_lacks(
    new_scene, other_scene_first, expected
):
    shared = await _released_linked_world(new_scene())
    if other_scene_first:
        other = await _load(new_scene, _released_other_save())
        if other_scene_first == "save":
            await _save(other)

    scene = await _load(new_scene, _released_holding_save())

    await shared.init_from_file()
    assert _texts(shared.world_state) == expected
    assert shared.format_version == SharedContext.FORMAT_VERSION
    assert _shared_texts(scene) == expected
    assert scene.world_state.manual_context["lamp"].shared is False


async def _unshare_and_save(new_scene, entry_id: str):
    scene = await _load(new_scene, _released_other_save())
    scene.world_state.manual_context[entry_id].shared = False
    await _save(scene)


@pytest.mark.asyncio
async def test_a_marked_shared_file_does_not_take_back_an_entry_removed_on_this_version(
    new_scene,
):
    shared = await _released_linked_world(new_scene())
    await _unshare_and_save(new_scene, "tavern")

    scene = await _load(
        new_scene,
        _released_linked_save(
            _released_entry("tavern", "The tavern stays open all night.")
        ),
    )

    await shared.init_from_file()
    assert "tavern" not in shared.world_state.manual_context
    assert "tavern" not in scene.world_state.manual_context


@pytest.mark.asyncio
async def test_a_second_load_of_a_released_save_does_not_take_back_a_removed_entry(
    new_scene,
):
    shared = await _released_linked_world(new_scene())
    await _load(new_scene, _released_holding_save())
    await _unshare_and_save(new_scene, "promise")

    scene = await _load(new_scene, _released_holding_save())

    await shared.init_from_file()
    assert "promise" not in shared.world_state.manual_context
    assert "promise" not in scene.world_state.manual_context
