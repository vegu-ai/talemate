"""
Audio Tag Support, the model output of Unpack Generation Emission, and the
reasoning inputs of Generate Response.
"""

from types import SimpleNamespace

import pytest

from _node_test_helpers import run_node
from talemate.agents.tts.nodes import AudioTagSupport, UnpackGenerationEmission
from talemate.agents.tts.schema import Chunk, VoiceGenerationEmission
from talemate.client.context import ClientContext, client_context_attribute
from talemate.client.reasoning_effort import ReasoningEffortMixin
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.nodes.prompt import GenerateResponse
from talemate.instance import get_agent


def emission(api, model=None):
    chunk = Chunk(text=["Hello."], type="dialogue", api=api, model=model)
    return VoiceGenerationEmission.model_construct(chunk=chunk, context=None)


class TestAudioTagSupport:
    @pytest.mark.asyncio
    async def test_backend_with_a_tag_list(self, scene):
        out = await run_node(
            AudioTagSupport(),
            scene=scene,
            inputs={"emission": emission("chatterbox_turbo"), "tag": "laugh"},
        )
        assert out["supported"] is True
        assert "sigh" in out["allowed_tags"]
        assert out["tag_format"] == "[{{ tag }}]"
        assert out["formatted_tag"] == "[laugh]"

    @pytest.mark.asyncio
    async def test_tag_outside_the_list_is_not_formatted(self, scene):
        out = await run_node(
            AudioTagSupport(),
            scene=scene,
            inputs={"emission": emission("chatterbox_turbo"), "tag": "whistle"},
        )
        assert out["supported"] is True
        assert out["formatted_tag"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "model, supported", [("eleven_v3", True), ("eleven_flash_v2_5", False)]
    )
    async def test_support_follows_the_voice_model(self, scene, model, supported):
        out = await run_node(
            AudioTagSupport(),
            scene=scene,
            inputs={"emission": emission("elevenlabs", model), "tag": "whisper"},
        )
        assert out["supported"] is supported
        assert out["allowed_tags"] is None
        assert out["formatted_tag"] == ("[whisper]" if supported else None)

    @pytest.mark.asyncio
    async def test_unpack_outputs_the_model(self, scene):
        out = await run_node(
            UnpackGenerationEmission(),
            scene=scene,
            inputs={"emission": emission("elevenlabs", "eleven_v3")},
        )
        assert out["model"] == "eleven_v3"
        assert out["api"] == "elevenlabs"


class EffortClient(ReasoningEffortMixin):
    def __init__(self, effort="low", reasoning=True, fmt="reasoning_effort"):
        self.client_config = SimpleNamespace(effort_level=effort)
        self.reason_enabled_configured = reasoning
        self._format = fmt

    @property
    def reasoning_effort_format(self):
        return self._format

    @property
    def reasoning_disabled_for_action(self):
        return bool(client_context_attribute("disable_reasoning"))


class TestReasoningEffortOverride:
    def test_request_effort_replaces_the_client_setting(self):
        client = EffortClient(effort="low")
        assert client.reasoning_effort == "low"
        with ClientContext(reasoning_effort="high"):
            assert client.reasoning_effort == "high"
        assert client.reasoning_effort == "low"

    def test_default_lets_the_model_choose(self):
        with ClientContext(reasoning_effort="default"):
            assert EffortClient(effort="low").reasoning_effort is None

    @pytest.mark.parametrize(
        "client", [EffortClient(reasoning=False), EffortClient(fmt="none")]
    )
    def test_no_effort_without_reasoning_or_effort_support(self, client):
        with ClientContext(reasoning_effort="high"):
            assert client.reasoning_effort is None

    def test_disabled_reasoning_wins(self):
        with ClientContext(reasoning_effort="high", disable_reasoning=True):
            assert EffortClient().reasoning_effort is None


class TestGenerateResponseReasoning:
    @pytest.fixture
    def seen(self, scene, monkeypatch):
        agent = get_agent("director")
        contexts = []

        async def delegate(fn, *args, **kwargs):
            contexts.append(
                (
                    client_context_attribute("reasoning_effort"),
                    client_context_attribute("disable_reasoning"),
                )
            )
            return "An answer."

        monkeypatch.setattr(agent, "delegate", delegate)
        prompt = SimpleNamespace(vars={}, prompt="p", captured_context="")
        return SimpleNamespace(agent=agent, prompt=prompt, contexts=contexts)

    @pytest.mark.asyncio
    async def test_inputs_reach_the_client_context(self, scene, seen):
        out = await run_node(
            GenerateResponse(),
            scene=scene,
            inputs={
                "agent": seen.agent,
                "prompt": seen.prompt,
                "reasoning_effort": "minimal",
                "disable_reasoning": False,
            },
        )
        assert out["response"] == "An answer."
        assert seen.contexts == [("minimal", False)]

    @pytest.mark.asyncio
    async def test_defaults_leave_the_client_setting(self, scene, seen):
        await run_node(
            GenerateResponse(),
            scene=scene,
            inputs={"agent": seen.agent, "prompt": seen.prompt},
        )
        assert seen.contexts == [(None, False)]

    @pytest.mark.asyncio
    async def test_disable_reasoning(self, scene, seen):
        await run_node(
            GenerateResponse(),
            scene=scene,
            inputs={
                "agent": seen.agent,
                "prompt": seen.prompt,
                "disable_reasoning": True,
            },
        )
        assert seen.contexts == [(None, True)]

    @pytest.mark.asyncio
    async def test_unknown_effort_is_refused(self, scene, seen):
        with pytest.raises(InputValueError):
            await run_node(
                GenerateResponse(),
                scene=scene,
                inputs={
                    "agent": seen.agent,
                    "prompt": seen.prompt,
                    "reasoning_effort": "extreme",
                },
            )
        assert seen.contexts == []
