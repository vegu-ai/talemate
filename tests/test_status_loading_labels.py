"""
Unit tests for `talemate.status` — the loading label a status carries, the
label a `set_loading` call builds from its own arguments, and the label a
handler sets once it knows what it works on.
"""

from __future__ import annotations

import asyncio
import unittest.mock

import pytest

from talemate.exceptions import GenerationCancelled
from talemate.status import (
    LoadingLabel,
    set_loading,
    set_loading_label,
)


@pytest.fixture
def emissions():
    """Every `emit("status", ...)` of a test, oldest first."""
    seen = []

    def record(typ, message=None, **kwargs):
        assert typ == "status"
        seen.append({"message": message, **kwargs})

    with unittest.mock.patch("talemate.status.emit", side_effect=record):
        yield seen


def busy(emissions: list[dict]) -> list[dict]:
    return [item for item in emissions if item.get("status") == "busy"]


class TestLoadingLabel:
    def test_keeps_the_names_apart_from_the_words_around_them(self):
        label = LoadingLabel("Looking at {}", "Mara")
        assert label.text == "Looking at Mara"
        assert label.parts == [
            {"text": "Looking at ", "name": False},
            {"text": "Mara", "name": True},
        ]

    def test_carries_a_name_that_repeats_the_letters_of_its_own_label(self):
        # a substring search would paint the "Ana" of "Analyzing"
        label = LoadingLabel("Analyzing {}'s development", "Ana")
        assert label.text == "Analyzing Ana's development"
        assert label.parts == [
            {"text": "Analyzing ", "name": False},
            {"text": "Ana", "name": True},
            {"text": "'s development", "name": False},
        ]

    def test_takes_more_than_one_name(self):
        label = LoadingLabel("Generating {} for {}", "resolve", "Mara")
        assert label.text == "Generating resolve for Mara"
        assert [part["text"] for part in label.parts if part["name"]] == [
            "resolve",
            "Mara",
        ]

    def test_a_label_without_names_is_one_chunk(self):
        label = LoadingLabel("Looking at the scene")
        assert label.text == "Looking at the scene"
        assert label.parts == [{"text": "Looking at the scene", "name": False}]

    def test_refuses_a_template_that_does_not_take_the_names_given(self):
        with pytest.raises(ValueError):
            LoadingLabel("Looking at {}")
        with pytest.raises(ValueError):
            LoadingLabel("Looking at the scene", "Mara")

    def test_reads_a_message_with_braces_in_it_as_the_message(self):
        # a status is not a template unless a name is passed for its slot
        label = LoadingLabel.plain("Applying {} template")
        assert label.text == "Applying {} template"
        assert label.parts == [{"text": "Applying {} template", "name": False}]

    def test_takes_a_name_that_is_not_a_string(self):
        assert (
            LoadingLabel("Summarizing {} messages", 5).text == "Summarizing 5 messages"
        )


class TestSetLoading:
    @pytest.mark.asyncio
    async def test_emits_a_static_message_as_before(self, emissions):
        @set_loading("Looking at the scene")
        async def handler():
            return "done"

        assert await handler() == "done"
        assert busy(emissions) == [
            {"message": "Looking at the scene", "status": "busy", "data": {}}
        ]
        assert emissions[-1] == {"message": "", "status": "idle"}

    @pytest.mark.asyncio
    async def test_builds_the_label_from_the_arguments_of_the_call(self, emissions):
        def label(handler, data: dict) -> LoadingLabel:
            return LoadingLabel("Looking at {}", data["character"])

        @set_loading(label, cancellable=True)
        async def handler(self, data: dict):
            return None

        await handler("handler", {"character": "Mara"})
        assert busy(emissions) == [
            {
                "message": "Looking at Mara",
                "status": "busy",
                "data": {
                    "cancellable": True,
                    "label": [
                        {"text": "Looking at ", "name": False},
                        {"text": "Mara", "name": True},
                    ],
                },
            }
        ]

    @pytest.mark.asyncio
    async def test_a_label_without_names_carries_no_parts(self, emissions):
        @set_loading(LoadingLabel("Examining the scene"))
        async def handler():
            return None

        await handler()
        assert busy(emissions)[0]["data"] == {}

    @pytest.mark.asyncio
    async def test_names_the_work_in_the_success_and_failure_messages(self, emissions):
        @set_loading(
            lambda name: LoadingLabel("Generating {}", name),
            set_success=True,
            set_error=True,
        )
        async def handler(name: str):
            if name == "boom":
                raise ValueError("no")
            return None

        await handler("resolve")
        assert emissions[-1] == {
            "message": "Generating resolve",
            "status": "success",
            "data": {
                "label": [
                    {"text": "Generating ", "name": False},
                    {"text": "resolve", "name": True},
                ]
            },
        }

        with pytest.raises(ValueError):
            await handler("boom")
        assert emissions[-1] == {
            "message": "Generating boom: Failed",
            "status": "error",
            "data": {
                "label": [
                    {"text": "Generating ", "name": False},
                    {"text": "boom", "name": True},
                    {"text": ": Failed", "name": False},
                ]
            },
        }

    @pytest.mark.asyncio
    async def test_names_the_work_when_the_generation_is_cancelled(self, emissions):
        @set_loading(LoadingLabel("Looking at {}", "Mara"), set_error=True)
        async def handler():
            raise GenerationCancelled("stopped")

        with pytest.raises(GenerationCancelled):
            await handler()
        assert emissions[-1] == {
            "message": "Looking at Mara: Cancelled",
            "status": "idle",
            "data": {
                "label": [
                    {"text": "Looking at ", "name": False},
                    {"text": "Mara", "name": True},
                    {"text": ": Cancelled", "name": False},
                ]
            },
        }

    @pytest.mark.asyncio
    async def test_the_label_of_a_call_does_not_leak_into_the_next_one(self, emissions):
        @set_loading(lambda name: LoadingLabel("Looking at {}", name))
        async def handler(name: str):
            return None

        await handler("Mara")
        await handler("Elmer")
        assert [item["message"] for item in busy(emissions)] == [
            "Looking at Mara",
            "Looking at Elmer",
        ]


class TestNestedLoading:
    @pytest.mark.asyncio
    async def test_the_inner_call_hands_the_status_back_when_it_ends(self, emissions):
        # the character development chain: an analysis that runs generations
        @set_loading(LoadingLabel("Analyzing {}", "Mara"), set_success=True)
        async def outer():
            await inner()
            set_loading_label(LoadingLabel("Analyzed {}", "Mara"))

        @set_loading(LoadingLabel("Generating {} for {}", "resolve", "Mara"))
        async def inner():
            return None

        await outer()
        assert [item["message"] for item in busy(emissions)] == [
            "Analyzing Mara",
            "Generating resolve for Mara",
            "Analyzed Mara",
        ]
        assert emissions[-1]["message"] == "Analyzed Mara"
        assert emissions[-1]["status"] == "success"


class TestSetLoadingLabel:
    @pytest.mark.asyncio
    async def test_renames_the_status_a_handler_is_showing(self, emissions):
        @set_loading("Generating actor action", cancellable=True)
        async def handler():
            set_loading_label(LoadingLabel("Generating {}'s next action", "Mara"))

        await handler()
        assert [item["message"] for item in busy(emissions)] == [
            "Generating actor action",
            "Generating Mara's next action",
        ]
        assert busy(emissions)[-1]["data"]["cancellable"] is True
        assert busy(emissions)[-1]["data"]["label"][1] == {
            "text": "Mara",
            "name": True,
        }

    @pytest.mark.asyncio
    async def test_names_the_work_that_failed_after_the_rename(self, emissions):
        @set_loading("Generating actor action", set_error=True)
        async def handler():
            set_loading_label(LoadingLabel("Generating {}'s next action", "Mara"))
            raise ValueError("no")

        with pytest.raises(ValueError):
            await handler()
        assert emissions[-1]["message"] == "Generating Mara's next action: Failed"
        assert emissions[-1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_emits_nothing_while_the_status_is_not_shown(self, emissions):
        @set_loading("Preparing", set_busy=False)
        async def handler():
            set_loading_label("Preparing something else")

        await handler()
        assert busy(emissions) == []

    def test_reports_that_there_is_no_status_to_rename(self):
        assert set_loading_label("Looking at Mara") is False

    @pytest.mark.asyncio
    async def test_refuses_a_rename_from_a_task_that_outlived_the_call(self, emissions):
        renamed = asyncio.Event()
        started = asyncio.Event()

        async def late():
            await started.wait()
            renamed.set()
            return set_loading_label(LoadingLabel("Looking at {}", "Mara"))

        @set_loading("Looking at a character")
        async def handler():
            return asyncio.create_task(late())

        task = await handler()
        started.set()
        assert await task is False
        await renamed.wait()
        assert [item["message"] for item in busy(emissions)] == [
            "Looking at a character"
        ]

    @pytest.mark.asyncio
    async def test_renames_with_a_message_that_carries_braces(self, emissions):
        @set_loading("Applying")
        async def handler():
            set_loading_label("Applying {} template")

        await handler()
        assert [item["message"] for item in busy(emissions)] == [
            "Applying",
            "Applying {} template",
        ]


class TestHandlerLabels:
    """The labels the websocket handlers build from their own payloads."""

    def test_the_narrator_names_the_character_it_looks_at(self):
        from talemate.agents.narrator.websocket_handler import (
            _look_at_character_label,
        )

        label = _look_at_character_label(None, {"character": "Mara"})
        assert label.text == "Looking at Mara"
        assert label.names == ["Mara"]
        assert _look_at_character_label(None, {}) == "Looking at a character"

    def test_the_narrator_shows_the_query_it_investigates(self):
        from talemate.agents.narrator.websocket_handler import (
            QUERY_STATUS_MAX_LENGTH,
            _query_label,
        )

        label = _query_label(None, {"query": "What is behind the lamp room door?"})
        assert label.text == "Investigating: What is behind the lamp room door?"

        long = _query_label(
            None, {"query": "Why does " + "the light keep turning " * 8}
        )
        assert len(long.text) <= len("Investigating: ") + QUERY_STATUS_MAX_LENGTH
        assert long.text.endswith("...")

    def test_the_world_state_names_the_entity_and_counts_the_messages(self):
        from talemate.agents.world_state.websocket_handler import (
            _examine_label,
            _summarize_and_pin_label,
        )

        label = _examine_label(
            None,
            {
                "entity_name": "the oil store",
                "entity_kind": "item",
                "snapshot_text": "",
            },
        )
        assert label.text == "Examining the oil store"
        assert label.names == ["the oil store"]

        assert (
            _summarize_and_pin_label(None, {"num_messages": 12}).text
            == "Summarizing 12 messages and pinning"
        )

    def test_the_director_names_the_character_it_generates_actions_for(self):
        from talemate.agents.director.websocket_handler import _dynamic_choices_label

        label = _dynamic_choices_label(None, {"character": "Elmer"})
        assert label.text == "Generating actions for Elmer"
        assert _dynamic_choices_label(None, {}) == "Generating dynamic actions"


class TestLabelFailure:
    @pytest.mark.asyncio
    async def test_runs_the_call_even_when_its_label_cannot_be_built(self, emissions):
        from talemate.status import FALLBACK_LABEL

        def label(data: dict) -> LoadingLabel:
            return LoadingLabel("Looking at {}", data["character"])

        @set_loading(label)
        async def handler(data: dict):
            return "done"

        assert await handler({}) == "done"
        assert busy(emissions) == [
            {"message": FALLBACK_LABEL, "status": "busy", "data": {}}
        ]
