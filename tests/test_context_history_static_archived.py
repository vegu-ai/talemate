"""
Regression tests for best-fit context history with static archived entries.

Background
----------
In best-fit mode the "archived level" used to be built from a *filtered*
subset of ``archived_history`` (only entries with an ``end``). But layered
history layer 0 stores ``start``/``end`` as indices into the *full*
``archived_history``. When ``archived_history`` contained static entries
(pre-established / manually added notes, which have no ``end``) the two index
spaces disagreed and the expansion algorithm could index past the end of the
archived level, raising ``IndexError: list index out of range`` while building
the conversation prompt.

The fix: static entries are always contiguous at the front of
``archived_history``, so the divergence is a fixed offset. When the layer-0
best-fit level is built, each entry's ``start``/``end`` is shifted down by that
offset (the count of leading static entries) to realign with the summary-only
archived level.
"""

from unittest.mock import patch

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.scene_message import CharacterMessage


def _char_count_tokens(source):
    """1 char == 1 token, for deterministic budget math."""
    if isinstance(source, list):
        return sum(_char_count_tokens(s) for s in source)
    return len(str(source))


def _pad(label: str, n: int) -> str:
    return label + "." * max(0, n - len(label))


@pytest.fixture(autouse=True)
def mock_count_tokens():
    with (
        patch(
            "talemate.agents.summarize.context_history.count_tokens",
            side_effect=_char_count_tokens,
        ),
        patch("talemate.util.count_tokens", side_effect=_char_count_tokens),
    ):
        yield


# Two static (no `end`) archive notes followed by four real summaries.
# The best-fit archived level previously only saw the four summaries.
STATIC_ENTRIES = [
    {"text": _pad("Static 0", 200), "ts": "PT0S"},
    {"text": _pad("Static 1", 200), "ts": "PT1M"},
]

SUMMARY_ENTRIES = [
    {"text": _pad("Summary 0", 200), "ts": "PT2M", "start": 0, "end": 5},
    {"text": _pad("Summary 1", 200), "ts": "PT3M", "start": 6, "end": 8},
    {"text": _pad("Summary 2", 200), "ts": "PT4M", "start": 9, "end": 11},
    {"text": _pad("Summary 3", 200), "ts": "PT5M", "start": 12, "end": 14},
]


def _layer0_entry(label, start, end):
    # start/end index into archived_history (layer 0 summarizes archived
    # entries) — distinct from SUMMARY_ENTRIES' message-index start/end.
    return {
        "text": _pad(label, 300),
        "ts": "PT3M",
        "ts_start": "PT2M",
        "ts_end": "PT5M",
        "start": start,
        "end": end,
    }


def _make_scene(archived_history, layer0) -> MockScene:
    scene = MockScene()
    scene.history = [
        CharacterMessage(message=_pad(f"C: M{i} ", 100), source="ai") for i in range(20)
    ]
    scene.archived_history = archived_history
    scene.layered_history = [layer0]
    scene.ts = "PT6M"

    agents = bootstrap_scene(scene)
    summarizer = agents["summarizer"]
    summarizer.actions["layered_history"].enabled = True
    summarizer.actions["manage_scene_history"].config["best_fit"].value = True
    return scene


def test_static_archived_entries_do_not_crash():
    """Layer-0 entries indexing past the summary-only subset must not crash.

    archived_history = [static, static, summary*4]. layer-0 entry start/end
    index the full 6-entry list; the 2nd entry (start=4, end=5) used to
    overrun the 4-entry archived level. Regression for the IndexError.
    """
    scene = _make_scene(
        STATIC_ENTRIES + SUMMARY_ENTRIES,
        [_layer0_entry("L0-0", 0, 3), _layer0_entry("L0-1", 4, 5)],
    )
    result = scene.context_history(budget=1500)

    assert isinstance(result, list)
    assert all(isinstance(s, str) for s in result)
    # Recent (unsummarized) dialogue should still be present.
    text = " ".join(result)
    assert "M19" in text
    # The summary hierarchy must actually render — proves the layered
    # best-fit path (where the IndexError occurred) executed, rather than a
    # dialogue-only fallback that would pass these checks vacuously.
    assert any("L0-" in s or "Summary" in s for s in result)
    # Static notes are not rendered as summarized content.
    assert "Static 0" not in text
    assert "Static 1" not in text


def test_single_layer0_entry_with_static():
    """A single layer-0 entry alongside static archived entries works."""
    scene = _make_scene(
        STATIC_ENTRIES + SUMMARY_ENTRIES,
        [_layer0_entry("L0-0", 0, 3)],
    )
    result = scene.context_history(budget=1500)
    assert isinstance(result, list)
    assert all(isinstance(s, str) for s in result)


def test_no_static_entries():
    """Summary-only archived history (no static entries) still works.

    Indices align natively here; this guards against regressions in the
    common case.
    """
    scene = _make_scene(
        list(SUMMARY_ENTRIES),
        [_layer0_entry("L0-0", 0, 1), _layer0_entry("L0-1", 2, 3)],
    )
    result = scene.context_history(budget=1500)
    assert isinstance(result, list)
    assert all(isinstance(s, str) for s in result)
