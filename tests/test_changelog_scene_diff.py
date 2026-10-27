import copy
import json

import pytest

from talemate.changelog import capture_snapshot
from talemate.storage.blobs import Blob


@pytest.mark.parametrize("size", [500, 2500, 5000])
def test_append_hashes_only_new_message_and_changed_sections(size, monkeypatch):
    data = {
        "history": [
            {"id": i, "message": f"passage {i}", "meta": {"present": ["Mara"]}}
            for i in range(size)
        ],
        "world_state": {"characters": {"Mara": {"state": "waiting"}}},
        "future_field": [1, True],
    }
    initial = capture_snapshot(data)
    calls = []
    original = Blob.from_bytes
    monkeypatch.setattr(
        Blob, "from_bytes", lambda value: (calls.append(value), original(value))[1]
    )
    data["history"].append({"id": size, "message": "the lamp lights"})
    changed = capture_snapshot(data, initial.cache)
    assert len(calls) == 2
    assert changed.manifest.history_chunks[:-1] == initial.manifest.history_chunks[:-1]
    calls.clear()
    data["world_state"]["characters"]["Mara"]["state"] = "awake"
    data["history"][-1]["meta"] = {"nested": [1, False]}
    edited = capture_snapshot(data, changed.cache)
    assert len(calls) == 3
    calls.clear()
    data["history"].reverse()
    reordered = capture_snapshot(data, edited.cache)
    assert all("messages" in json.loads(value) for value in calls)
    assert reordered.data["history"] == list(reversed(edited.data["history"]))
    assert initial.data["world_state"]["characters"]["Mara"]["state"] == "waiting"


@pytest.mark.parametrize(
    "before,after", [(1, True), (1, 1.0), ([], {}), ("", []), (None, False)]
)
def test_json_type_changes_have_different_content_addresses(before, after):
    first = capture_snapshot({"value": before})
    second = capture_snapshot({"value": after}, first.cache)
    assert first.manifest != second.manifest
    assert len(second.changed) == 1


def test_unknown_sections_and_nested_changes_need_no_classification():
    data = {"history": [], "new_feature": {"one": [1, 2]}, "gone": "old"}
    first = capture_snapshot(data)
    updated = copy.deepcopy(data)
    updated["new_feature"]["one"][0] = 9
    del updated["gone"]
    second = capture_snapshot(updated, first.cache)
    assert second.data == updated
    assert first.data == data
    assert "gone" not in second.manifest.sections


def test_mixed_json_object_keys_follow_save_encoder_policy():
    data = {"history": [], "new_feature": {1: "one", "two": 2, None: False}}
    capture = capture_snapshot(data)
    assert capture.data["new_feature"] == {"1": "one", "two": 2, "null": False}
