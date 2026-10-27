import copy

import pytest

from talemate.changelog import (
    capture_snapshot,
    counts_for_span,
    list_revision_groups,
    scene_ref_from_path,
)
from talemate.storage.changelog import SnapshotStore
from talemate.storage.revision_groups import RevisionGroupQuery, revision_groups


def narrator(id, text=None, **extra):
    return {"id": id, "typ": "narrator", "message": text or f"Line {id}", **extra}


def character(id, text):
    return {"id": id, "typ": "character", "message": f"Mira: {text}"}


def director(id):
    return {"id": id, "typ": "director", "message": f"Direction {id}"}


async def record(tmp_path, histories, filename="scene.json"):
    """One revision per history; `turn` makes every state distinct."""
    store = SnapshotStore(tmp_path)
    head, cache = None, None
    for turn, history in enumerate(histories):
        snapshot = capture_snapshot(
            {"intro": "At the lighthouse", "turn": turn, "history": history}, cache
        )
        cache = snapshot.cache
        head = await store.append(
            filename,
            snapshot.manifest,
            snapshot.changed,
            expected_head=head.id if head else None,
        )
    return store


async def page(store, filename="scene.json", **query):
    return await revision_groups(
        store, filename, RevisionGroupQuery(**query), counts_for_span
    )


def revs(result):
    return [[entry.rev for entry in group.revisions] for group in result.groups]


def grow(*steps):
    history, histories = [], []
    for step in steps:
        if step is not None:
            history = history + [step]
        histories.append(copy.deepcopy(history))
    return histories


def test_span_rule_counts_character_and_narrator_only():
    assert counts_for_span({"typ": "character"})
    assert counts_for_span({"typ": "narrator"})
    for typ in ["director", "time", "context_investigation", "reinforcement", "scene"]:
        assert not counts_for_span({"typ": typ})


async def test_span_one_folds_state_changes_and_skipped_types(tmp_path):
    store = await record(
        tmp_path,
        grow(None, narrator(1), None, character(2, "Hello"), director(3), narrator(4)),
    )
    result = await page(store)

    assert revs(result) == [[5], [4, 3], [2, 1], [0]]
    assert result.total_revisions == 6
    assert result.latest_rev == 5
    assert result.next_before_rev is None
    newest, second, first, intro = result.groups
    assert (newest.first_message, newest.last_message) == (3, 3)
    assert newest.message.id == 4
    assert second.message.model_dump() == {
        "id": 2,
        "typ": "character",
        "text": "Mira: Hello",
        "hidden": False,
    }
    assert [e.message_count for e in second.revisions] == [3, 2]
    assert (intro.first_message, intro.last_message, intro.message) == (0, 0, None)
    assert intro.revisions[0].is_base


async def test_span_three_groups_every_third_message(tmp_path):
    store = await record(tmp_path, grow(*[narrator(i) for i in range(1, 8)]))
    result = await page(store, span=3)

    assert revs(result) == [[6], [5, 4, 3], [2, 1, 0]]
    assert [(g.first_message, g.last_message) for g in result.groups] == [
        (7, 7),
        (4, 6),
        (1, 3),
    ]
    assert result.groups[1].message.id == 6


@pytest.mark.parametrize(
    "change, new_row",
    [
        ("regenerate", True),
        ("rewind", True),
        ("edit_older", True),
        ("hide", False),
        ("knowledge", False),
    ],
)
async def test_changed_story_starts_a_new_row(tmp_path, change, new_row):
    base = [narrator(1), narrator(2), narrator(3)]
    changed = copy.deepcopy(base)
    if change == "regenerate":
        changed[-1]["message"] = "Line 3, told again"
    elif change == "rewind":
        changed = changed[:2]
    elif change == "edit_older":
        changed[0]["message"] = "Line 1, edited"
    elif change == "hide":
        changed[-1]["flags"] = 1
    else:
        changed[-1]["knowledge"] = {"views": ["seen"]}
    store = await record(tmp_path, [base, changed])

    for span in (1, 3):
        result = await page(store, span=span)
        assert revs(result) == ([[1], [0]] if new_row else [[1, 0]]), span


async def test_rewind_at_same_bucket_is_a_new_row_with_the_earlier_message(tmp_path):
    store = await record(
        tmp_path, grow(narrator(1), narrator(2)) + [[narrator(1)], [narrator(1)]]
    )
    result = await page(store)

    assert revs(result) == [[3, 2], [1], [0]]
    assert result.groups[0].message.id == 1


async def test_paging_resumes_at_the_next_group(tmp_path):
    store = await record(tmp_path, grow(*[narrator(i) for i in range(1, 6)], None))
    full = await page(store)
    first = await page(store, limit=2)
    second = await page(store, limit=2, before_rev=first.next_before_rev)
    third = await page(store, limit=2, before_rev=second.next_before_rev)

    assert revs(first) == [[5, 4], [3]]
    assert first.next_before_rev == 3
    assert revs(first) + revs(second) + revs(third) == revs(full)
    assert third.next_before_rev is None


async def test_include_rev_extends_the_page_to_its_group(tmp_path):
    store = await record(tmp_path, grow(*[narrator(i) for i in range(1, 8)]))
    result = await page(store, limit=1, include_rev=2)

    assert revs(result) == [[6], [5], [4], [3], [2]]
    assert result.next_before_rev == 2


async def test_include_rev_hidden_by_the_search_keeps_the_page_limit(tmp_path):
    messages = [
        narrator(i, "At the harbor" if i == 5 else f"the bell {i}")
        for i in range(1, 61)
    ]
    store = await record(tmp_path, grow(*messages))

    hidden = await page(store, limit=10, search="bell", include_rev=4)
    assert len(hidden.groups) == 10
    assert revs(hidden)[0] == [59] and revs(hidden)[-1] == [50]
    assert hidden.next_before_rev == 50

    shown = await page(store, limit=10, search="bell", include_rev=10)
    assert revs(shown)[-1] == [10]
    assert len(shown.groups) == 50


async def test_date_range_limits_revisions_before_grouping(tmp_path):
    store = await record(tmp_path, grow(narrator(1), None, narrator(2), None))
    await store.db.write(
        lambda c: c.execute("UPDATE changelog_revisions SET ts = 1000 + rev * 100")
    )
    result = await page(store, since_ts=1100, until_ts=1200)

    assert revs(result) == [[2], [1]]
    assert (result.total_revisions, result.latest_rev) == (4, 3)
    assert revs(await page(store, since_ts=5000)) == []


async def test_search_matches_any_counted_message_in_the_span(tmp_path):
    store = await record(
        tmp_path,
        grow(
            character(1, "The LANTERN is lit"),
            narrator(2),
            director(3),
            narrator(4),
        ),
    )
    assert revs(await page(store, search="lantern")) == [[0]]
    assert revs(await page(store, span=2, search=" lantern ")) == [[2, 1, 0]]
    assert revs(await page(store, search="Direction 3")) == []
    assert revs(await page(store, search="mira")) == []


async def test_search_matches_message_content_not_the_speaker(tmp_path):
    store = await record(
        tmp_path,
        grow(
            character(1, "Hello there"),
            narrator(2, "Mira waves from the gallery."),
            character(3, "Nice day"),
            character(4, "Ask Mira: she knows the stairs."),
        ),
    )
    assert revs(await page(store, search="mira")) == [[3], [1]]
    assert revs(await page(store, search="mira:")) == [[3]]
    assert revs(await page(store, search="hello")) == [[0]]


async def test_damaged_message_marks_only_the_row_that_shows_it(tmp_path):
    store = await record(tmp_path, grow(narrator(1), narrator(2), narrator(3)))
    snapshot = capture_snapshot({"history": [narrator(2)]})
    digest = snapshot.manifest.history_chunks[0]
    message_digest = next(
        blob.digest for blob in snapshot.changed if blob.digest != digest
    )
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"broken", message_digest),
        )
    )
    result = await page(store)

    assert revs(result) == [[2], [1], [0]]
    assert [g.damaged for g in result.groups] == [False, True, False]
    assert result.groups[1].message is None
    numbers = [(g.first_message, g.last_message) for g in result.groups]
    assert numbers == [(0, 0), (0, 0), (1, 1)]
    assert [g.message.id for g in (result.groups[0], result.groups[2])] == [3, 1]


async def test_damaged_message_keeps_the_later_runs(tmp_path):
    histories = grow(narrator(1), narrator(2)) + [[narrator(1), narrator(2)]] * 5
    store = await record(tmp_path, histories)
    message_digest = next(
        blob.digest
        for blob in capture_snapshot({"history": [narrator(1)]}).changed
        if blob.digest
        != capture_snapshot({"history": [narrator(1)]}).manifest.history_chunks[0]
    )
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?",
            (b"broken", message_digest),
        )
    )
    for span in (1, 3):
        result = await page(store, span=span)
        expected = [[6, 5, 4, 3, 2, 1], [0]] if span == 1 else [[6, 5, 4, 3, 2, 1, 0]]
        assert revs(result) == expected, span
        assert not result.groups[0].damaged
        assert result.groups[0].message.id == 2
    first = (await page(store)).groups[-1]
    assert first.damaged and first.message is None
    assert (first.first_message, first.last_message) == (0, 0)


async def test_damaged_chunk_keeps_runs_that_share_it(tmp_path):
    store = await record(tmp_path, [[narrator(1)]] * 3)
    chunk = capture_snapshot({"history": [narrator(1)]}).manifest.history_chunks[0]
    await store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?", (b"broken", chunk)
        )
    )
    result = await page(store)

    assert revs(result) == [[2, 1, 0]]
    assert result.groups[0].damaged


def damage(store, digest):
    return store.db.write(
        lambda c: c.execute(
            "UPDATE storage_blobs SET data=? WHERE digest=?", (b"broken", digest)
        )
    )


async def test_damaged_sealed_chunk_hides_the_message_numbers(tmp_path):
    sealed = [narrator(i) for i in range(1, 257)]
    store = await record(
        tmp_path,
        [sealed, sealed + [narrator(257)], sealed + [narrator(257), narrator(258)]],
    )
    await damage(
        store, capture_snapshot({"history": sealed}).manifest.history_chunks[0]
    )

    for span in (1, 2):
        result = await page(store, span=span)
        assert all((g.first_message, g.last_message) == (0, 0) for g in result.groups)
    result = await page(store)
    assert revs(result) == [[2], [1], [0]]
    assert [g.message.id if g.message else None for g in result.groups] == [
        258,
        257,
        None,
    ]
    assert [g.damaged for g in result.groups] == [False, False, True]
    assert revs(await page(store, search="line 257")) == [[1]]


async def test_damaged_director_message_hides_the_message_numbers(tmp_path):
    store = await record(
        tmp_path, grow(narrator(1), director(2), narrator(3), narrator(4))
    )
    snapshot = capture_snapshot({"history": [director(2)]})
    chunk = snapshot.manifest.history_chunks[0]
    await damage(store, next(b.digest for b in snapshot.changed if b.digest != chunk))
    result = await page(store)

    assert [(g.first_message, g.last_message) for g in result.groups] == [
        (0, 0),
        (0, 0),
        (0, 0),
        (1, 1),
    ]
    assert [g.message.id for g in result.groups if g.message] == [4, 3, 1]
    assert [g.damaged for g in result.groups] == [False, False, True, False]


async def test_rewind_then_the_same_messages_again_is_a_new_run(tmp_path):
    store = await record(
        tmp_path,
        [
            [narrator(1), narrator(2)],
            [narrator(1)],
            [narrator(1), narrator(2), narrator(3)],
        ],
    )
    assert revs(await page(store, span=3)) == [[2, 1], [0]]
    assert revs(await page(store)) == [[2], [1], [0]]


async def test_include_rev_outside_the_date_range_does_not_extend_the_page(tmp_path):
    store = await record(tmp_path, grow(*[narrator(i) for i in range(1, 13)]))
    await store.db.write(
        lambda c: c.execute("UPDATE changelog_revisions SET ts = 1000 + rev * 100")
    )
    result = await page(store, limit=2, include_rev=1, since_ts=1500)

    assert revs(result) == [[11], [10]]
    assert result.next_before_rev == 10
    assert revs(await page(store, limit=2, include_rev=7, since_ts=1500)) == [
        [11],
        [10],
        [9],
        [8],
        [7],
    ]


async def test_fork_rows_mark_inherited_base_and_fork(tmp_path):
    store = await record(tmp_path, grow(narrator(1), narrator(2)))
    await store.fork("scene.json", 1, "branch.json")
    snapshot = capture_snapshot(
        {"intro": "At the lighthouse", "turn": 9, "history": [narrator(1), narrator(5)]}
    )
    head = await store.head("branch.json")
    await store.append(
        "branch.json", snapshot.manifest, snapshot.changed, expected_head=head.id
    )
    result = await page(store, filename="branch.json")

    assert revs(result) == [[2], [1], [0]]
    assert [
        (e.origin, e.message_count, e.inherited, e.is_base, e.is_fork)
        for group in result.groups
        for e in group.revisions
    ] == [
        ("branch.json", 2, False, False, False),
        ("scene.json", 2, True, False, True),
        ("scene.json", 1, True, True, False),
    ]

    source = capture_snapshot(
        {
            "intro": "At the lighthouse",
            "turn": 10,
            "history": [narrator(1), narrator(2), narrator(3)],
        }
    )
    head = await store.head("scene.json")
    await store.append(
        "scene.json", source.manifest, source.changed, expected_head=head.id
    )
    result = await page(store)

    assert revs(result) == [[2], [1], [0]]
    assert not any(e.is_fork for group in result.groups for e in group.revisions)


async def test_missing_database_and_unknown_save_are_empty(tmp_path):
    assert (await page(SnapshotStore(tmp_path / "none"))).total_revisions == 0
    store = await record(tmp_path, grow(narrator(1)))
    assert (await page(store, filename="other.json")).groups == []


async def test_list_revision_groups_dumps_the_page(tmp_path):
    await record(tmp_path, grow(narrator(1)))
    scene = scene_ref_from_path(str(tmp_path / "scene.json"))
    data = await list_revision_groups(scene, RevisionGroupQuery())

    assert data["total_revisions"] == 1
    assert data["groups"][0]["message"]["id"] == 1
