"""Unit tests for the manually triggered scene intent evaluation.

Covers:
- ``auto_direct_set_scene_intent``: the phase is only returned when the
  focal flow actually executed ``set_scene_intention``; a ``do_nothing``
  call is the one true no-op, while an errored call and a response that
  carried no decision at all raise under ``raise_on_error`` (and still
  return ``None`` without it). Optional user instructions reach the
  template vars. ``Prompt.request`` is stood in for (the template renders
  against a full scene/agent stack the mock scene doesn't have) while the
  real focal extraction and callback dispatch run.
- ``DirectorWebsocketHandler.handle_determine_scene_intent``: the success
  status names the scene type and intent, the no-op status says the intent
  was left unchanged (and touches nothing), a failed evaluation reports an
  error, and the payload's instructions are forwarded.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from _director_test_helpers import patch_prompt_request_in

from talemate.agents.director.websocket_handler import DirectorWebsocketHandler
from talemate.exceptions import GenerationProcessingError
from talemate.scene.schema import ScenePhase, SceneType

TEMPLATE = "director.direct-determine-scene-intent"


@pytest.fixture
def focal_responses(monkeypatch):
    """Queue raw focal responses for the scene intent template."""
    install = patch_prompt_request_in(monkeypatch)

    def _install(*responses: str):
        return install({TEMPLATE: [(response, {}) for response in responses]})

    return _install


def focal_call_block(function: str, **arguments) -> str:
    """A focal-driven response: fenced JSON call block invoking one of the
    registered callbacks."""
    call = json.dumps({"function": function, "arguments": arguments})
    return f"```json\n{call}\n```"


# ---------------------------------------------------------------------------
# auto_direct_set_scene_intent
# ---------------------------------------------------------------------------


class TestAutoDirectSetSceneIntent:
    @pytest.mark.asyncio
    async def test_returns_phase_when_intention_set(
        self, scene, director, focal_responses
    ):
        focal_responses(
            focal_call_block(
                "set_scene_intention",
                type="roleplay",
                intention="The two of them finally talk it out.",
            )
        )

        phase = await director.auto_direct_set_scene_intent()

        assert phase is scene.intent_state.phase
        assert phase.scene_type == "roleplay"
        assert phase.intent == "The two of them finally talk it out."

    @pytest.mark.asyncio
    async def test_returns_none_when_do_nothing(self, scene, director, focal_responses):
        focal_responses(focal_call_block("do_nothing"))

        phase = await director.auto_direct_set_scene_intent()

        assert phase is None
        # the untouched default phase is still in place
        assert scene.intent_state.phase.intent is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_calls_made(
        self, scene, director, focal_responses
    ):
        # retries=1, so the callless response is requested twice
        focal_responses(
            "Nothing needs to change here.", "Nothing needs to change here."
        )

        phase = await director.auto_direct_set_scene_intent()

        assert phase is None

    @pytest.mark.asyncio
    async def test_raises_when_no_calls_made_and_raise_on_error(
        self, scene, director, focal_responses
    ):
        # prose the extractor can make nothing of - no decision was reached,
        # which must not read as the director leaving the intent alone
        focal_responses(
            "Nothing needs to change here.", "Nothing needs to change here."
        )

        with pytest.raises(GenerationProcessingError) as exc_info:
            await director.auto_direct_set_scene_intent(raise_on_error=True)

        assert "no decision" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_when_response_empty_and_raise_on_error(
        self, scene, director, focal_responses
    ):
        # the client swallows generation errors and returns "" - both the
        # initial request and the retry come back empty
        focal_responses("", "")

        with pytest.raises(GenerationProcessingError) as exc_info:
            await director.auto_direct_set_scene_intent(raise_on_error=True)

        assert "no decision" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_returns_none_when_response_empty(
        self, scene, director, focal_responses
    ):
        focal_responses("", "")

        phase = await director.auto_direct_set_scene_intent()

        assert phase is None

    @pytest.mark.asyncio
    async def test_returns_none_when_intention_call_failed(
        self, scene, director, focal_responses
    ):
        # invalid scene type - set_scene_phase raises, focal records the call
        # with called=False
        focal_responses(
            focal_call_block(
                "set_scene_intention",
                type="not_a_scene_type",
                intention="Should never be applied.",
            )
        )

        phase = await director.auto_direct_set_scene_intent()

        assert phase is None
        assert scene.intent_state.phase.intent is None

    @pytest.mark.asyncio
    async def test_raises_when_intention_call_failed_and_raise_on_error(
        self, scene, director, focal_responses
    ):
        focal_responses(
            focal_call_block(
                "set_scene_intention",
                type="not_a_scene_type",
                intention="Should never be applied.",
            )
        )

        with pytest.raises(GenerationProcessingError) as exc_info:
            await director.auto_direct_set_scene_intent(raise_on_error=True)

        # the underlying failure is preserved for the user-facing message
        assert "not_a_scene_type" in str(exc_info.value)
        assert scene.intent_state.phase.intent is None

    @pytest.mark.asyncio
    async def test_no_raise_on_deliberate_no_op_with_raise_on_error(
        self, scene, director, focal_responses
    ):
        focal_responses(focal_call_block("do_nothing"))

        phase = await director.auto_direct_set_scene_intent(raise_on_error=True)

        assert phase is None

    @pytest.mark.asyncio
    async def test_instructions_reach_the_template(
        self, scene, director, focal_responses
    ):
        stub = focal_responses(focal_call_block("do_nothing"))

        await director.auto_direct_set_scene_intent(
            instructions="Focus on the storm outside."
        )

        assert stub.calls[0]["vars"]["instructions"] == "Focus on the storm outside."

    @pytest.mark.asyncio
    async def test_instructions_default_to_empty(
        self, scene, director, focal_responses
    ):
        stub = focal_responses(focal_call_block("do_nothing"))

        await director.auto_direct_set_scene_intent()

        assert stub.calls[0]["vars"]["instructions"] == ""


# ---------------------------------------------------------------------------
# handle_determine_scene_intent
# ---------------------------------------------------------------------------


class TestDetermineSceneIntentWebsocketHandler:
    async def _run(
        self, scene, director, data: dict | None = None, **stub_kwargs
    ) -> SimpleNamespace:
        """Run handle_determine_scene_intent with the director method
        replaced by an autospec'd stand-in; returns the emit / queue_put /
        auto-save recorders and the stand-in itself."""
        ws = SimpleNamespace(scene=scene, queue_put=Mock())
        handler = DirectorWebsocketHandler(websocket_handler=ws)

        with (
            patch("talemate.server.websocket_plugin.emit") as mock_emit,
            patch.object(scene, "save", AsyncMock()) as mock_save,
            patch.object(
                director,
                "auto_direct_set_scene_intent",
                autospec=True,
                **stub_kwargs,
            ) as mock_determine,
        ):
            task = await handler.handle_determine_scene_intent(data or {})
            await task

        return SimpleNamespace(
            emit=mock_emit,
            queue_put=ws.queue_put,
            save=mock_save,
            determine=mock_determine,
        )

    async def _emitted_status(self, scene, director, phase: ScenePhase | None) -> dict:
        """The status emitted for a run that returned ``phase``."""
        result = await self._run(scene, director, return_value=phase)
        assert result.emit.call_count == 1
        return result.emit.call_args.kwargs

    @pytest.mark.asyncio
    async def test_success_status_names_the_scene_type(self, scene, director):
        scene.intent_state.scene_types["combat"] = SceneType(
            id="combat", name="Combat", description="Blades out."
        )

        status = await self._emitted_status(
            scene,
            director,
            ScenePhase(scene_type="combat", intent="The ambush is sprung."),
        )
        assert status["status"] == "success"
        assert status["message"] == "Scene intent set: Combat - The ambush is sprung."

    @pytest.mark.asyncio
    async def test_success_status_falls_back_to_scene_type_id(self, scene, director):
        status = await self._emitted_status(
            scene,
            director,
            ScenePhase(scene_type="combat", intent="The ambush is sprung."),
        )
        assert status["message"] == "Scene intent set: combat - The ambush is sprung."

    @pytest.mark.asyncio
    async def test_determination_kwargs(self, scene, director):
        result = await self._run(
            scene, director, return_value=ScenePhase(scene_type="roleplay")
        )
        kwargs = result.determine.await_args.kwargs
        assert kwargs["require"] is False
        assert kwargs["raise_on_error"] is True

    @pytest.mark.asyncio
    async def test_forwards_instructions(self, scene, director):
        result = await self._run(
            scene,
            director,
            data={"instructions": "Focus on the storm outside."},
            return_value=ScenePhase(scene_type="roleplay"),
        )
        assert (
            result.determine.await_args.kwargs["instructions"]
            == "Focus on the storm outside."
        )

    @pytest.mark.asyncio
    async def test_instructions_default_to_empty(self, scene, director):
        result = await self._run(
            scene, director, return_value=ScenePhase(scene_type="roleplay")
        )
        assert result.determine.await_args.kwargs["instructions"] == ""

    @pytest.mark.asyncio
    async def test_failure_status_when_intention_call_errored(self, scene, director):
        result = await self._run(
            scene,
            director,
            side_effect=GenerationProcessingError(
                "set_scene_intention failed: Invalid scene type: not_a_scene_type"
            ),
        )

        assert result.emit.call_count == 1
        status = result.emit.call_args.kwargs
        assert status["status"] == "error"
        assert status["message"] == (
            "Scene intent evaluation failed: set_scene_intention failed: "
            "Invalid scene type: not_a_scene_type"
        )

        payload = result.queue_put.call_args.args[0]
        assert payload["action"] == "operation_done"
        assert payload["error"]["message"] == status["message"]

    @pytest.mark.asyncio
    async def test_success_status_truncates_long_intent(self, scene, director):
        status = await self._emitted_status(
            scene,
            director,
            ScenePhase(scene_type="combat", intent="word " * 100),
        )
        assert status["status"] == "success"
        assert status["message"].endswith("...")
        assert len(status["message"]) < 150

    @pytest.mark.asyncio
    async def test_success_status_without_intent_text(self, scene, director):
        status = await self._emitted_status(
            scene, director, ScenePhase(scene_type="roleplay")
        )
        assert status["message"] == "Scene intent set: Roleplay"

    @pytest.mark.asyncio
    async def test_success_status_with_blank_intent_text(self, scene, director):
        status = await self._emitted_status(
            scene, director, ScenePhase(scene_type="roleplay", intent="   \n ")
        )
        assert status["message"] == "Scene intent set: Roleplay"

    @pytest.mark.asyncio
    async def test_unchanged_status_when_no_intent_set(self, scene, director):
        status = await self._emitted_status(scene, director, None)
        assert status["status"] == "info"
        assert status["message"] == "Director left the scene intent unchanged"

    @pytest.mark.asyncio
    async def test_unchanged_path_does_not_touch_the_scene(self, scene, director):
        # signal_only=True - nothing changed, so no auto-save and no
        # unsaved-changes flag
        saved = scene.saved
        result = await self._run(scene, director, return_value=None)

        result.save.assert_not_called()
        assert scene.saved is saved

    @pytest.mark.asyncio
    async def test_success_path_saves_the_scene(self, scene, director):
        result = await self._run(
            scene, director, return_value=ScenePhase(scene_type="roleplay")
        )

        result.save.assert_awaited_once()
