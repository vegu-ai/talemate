"""Tests for the TTS node-graph nodes.

The generation-emission nodes never touch the TTS agent instance, so they are
instantiated and run directly through the shared node-test harness. The
end-to-end tests wire a real Listen node to the real
`agent.tts.generate.before` signal to prove a graph can rewrite the spoken
text before the audio is generated - once against the raw signal, once
against `TTSAgent._generate_chunk`, which is what sends it in production.
"""

from __future__ import annotations

import pytest

import talemate.agents.tts.voice_library as voice_library
import talemate.emit.async_signals as async_signals
from _node_test_helpers import build_graph, run_node
from talemate.agents.tts import TTSAgent
from talemate.agents.tts.nodes import SetChunkText, UnpackGenerationEmission
from talemate.agents.tts.schema import (
    Chunk,
    GenerationContext,
    Voice,
    VoiceGenerationEmission,
    VoiceLibrary,
)
from talemate.game.engine.nodes.core import (
    GraphContext,
    GraphState,
    InputValueError,
    Listen,
)
from talemate.game.engine.nodes.event import (
    State as EventState,
    connect_listeners,
    disconnect_listeners,
)
from talemate.game.engine.nodes.logic import MakeBool
from talemate.game.engine.nodes.string import Replace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_voice(
    label: str = "Test Voice",
    provider: str = "kokoro",
    provider_id: str = "vid",
    **kwargs,
) -> Voice:
    return Voice(label=label, provider=provider, provider_id=provider_id, **kwargs)


def _make_emission(text: list[str] | None = None) -> VoiceGenerationEmission:
    """Build the emission shape `_generate_chunk` sends - a sub-chunk with a
    single text entry."""
    chunk = Chunk(
        text=["Hello *world*"] if text is None else text,
        type="dialogue",
        character_name="Alice",
        api="kokoro",
        message_id=123,
        voice=_make_voice(),
    )
    return VoiceGenerationEmission(chunk=chunk, context=GenerationContext())


def _build_rewrite_graph(old: str = "world", new: str = "there"):
    """Build the graph from the text-manipulation docs: unpack the emission,
    replace a word in its text and write the result back to the chunk."""
    listen = Listen()
    listen.set_property("event_name", "agent.tts.generate.before")

    event_node = EventState()
    unpack = UnpackGenerationEmission()
    replace = Replace()
    replace.set_property("old", old)
    replace.set_property("new", new)
    # `Set Chunk Text` gates on `state`, so it needs a state source - the
    # docs feed it an explicit Make Bool (default True).
    make_bool = MakeBool()
    set_chunk_text = SetChunkText()

    for node in (event_node, unpack, replace, make_bool, set_chunk_text):
        listen.add_node(node)

    listen.connect(
        event_node.get_output_socket("event"), unpack.get_input_socket("emission")
    )
    listen.connect(unpack.get_output_socket("text"), replace.get_input_socket("string"))
    listen.connect(
        unpack.get_output_socket("emission"),
        set_chunk_text.get_input_socket("emission"),
    )
    listen.connect(
        replace.get_output_socket("result"), set_chunk_text.get_input_socket("text")
    )
    listen.connect(
        make_bool.get_output_socket("value"), set_chunk_text.get_input_socket("state")
    )

    return build_graph(listen)


@pytest.fixture
def fresh_voice_library():
    """Replace the global voice library with a fresh empty instance."""
    original = voice_library.VOICE_LIBRARY
    voice_library.VOICE_LIBRARY = VoiceLibrary(voices={})
    try:
        yield voice_library.VOICE_LIBRARY
    finally:
        voice_library.VOICE_LIBRARY = original


@pytest.fixture
def tts_agent(fresh_voice_library):
    """Provide a fresh TTSAgent with an empty global voice library."""
    return TTSAgent()


# ---------------------------------------------------------------------------
# UnpackGenerationEmission
# ---------------------------------------------------------------------------


class TestUnpackGenerationEmission:
    def test_text_socket_connects_to_str_sockets(self):
        """The editor refuses `text` -> `str` links (litegraph only matches
        comma-list members), so the documented graph needs `str` on both
        text sockets — the backend `Graph.connect` never checks this."""
        unpack = UnpackGenerationEmission()
        set_chunk_text = SetChunkText()

        assert "str" in unpack.get_output_socket("text").socket_type.split(",")
        assert "str" in set_chunk_text.get_input_socket("text").socket_type.split(",")

    @pytest.mark.asyncio
    async def test_unpacks_chunk_fields(self):
        emission = _make_emission()

        out = await run_node(UnpackGenerationEmission(), inputs={"emission": emission})

        assert out["emission"] is emission
        assert out["text"] == "Hello *world*"
        assert out["character_name"] == "Alice"
        assert out["type"] == "dialogue"
        assert out["api"] == "kokoro"
        assert out["message_id"] == 123
        assert out["voice"] is emission.chunk.voice


# ---------------------------------------------------------------------------
# SetChunkText
# ---------------------------------------------------------------------------


class TestSetChunkText:
    def test_state_input_is_required(self):
        """As a write operation the node must be gated on `state` - an
        unconnected state socket keeps it from running at all."""
        assert SetChunkText().get_input_socket("state").optional is False

    @pytest.mark.asyncio
    async def test_replaces_chunk_text(self):
        emission = _make_emission()

        out = await run_node(
            SetChunkText(),
            inputs={"state": True, "emission": emission, "text": "Hello there"},
        )

        assert out["state"] is True
        assert out["emission"] is emission
        assert emission.chunk.text == ["Hello there"]
        assert emission.chunk.cleaned_text == "Hello there."

    @pytest.mark.asyncio
    async def test_missing_text_raises(self):
        emission = _make_emission()

        with pytest.raises(InputValueError, match="Value is not set"):
            await run_node(SetChunkText(), inputs={"state": True, "emission": emission})


# ---------------------------------------------------------------------------
# End to end - rewriting the text from an event graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listen_graph_rewrites_chunk_text_before_generation():
    graph = _build_rewrite_graph()
    state = GraphState()
    emission = _make_emission(text=["Hello world"])

    connect_listeners(graph, state)
    try:
        with GraphContext():
            failures = await async_signals.get("agent.tts.generate.before").send(
                emission
            )
    finally:
        disconnect_listeners(graph, state)

    assert failures == []
    assert emission.chunk.text == ["Hello there"]
    assert emission.chunk.cleaned_text == "Hello there."


@pytest.mark.asyncio
async def test_generate_chunk_sends_signal_before_generating(tts_agent, monkeypatch):
    """`_generate_chunk` must await `agent.tts.generate.before` on the same
    chunk object it then hands to `generate_fn`, or the rewrite never reaches
    the backend."""
    graph = _build_rewrite_graph()
    state = GraphState()

    generated_text: list[str] = []
    played: list[tuple] = []

    async def fake_generate(chunk: Chunk, context: GenerationContext) -> bytes:
        generated_text.append(chunk.cleaned_text)
        return b"RIFF....WAVE"

    monkeypatch.setattr(
        tts_agent,
        "play_audio",
        lambda audio_data, message_id=None: played.append((audio_data, message_id)),
    )

    chunk = Chunk(
        text=["Hello world"],
        type="dialogue",
        character_name="Alice",
        api="kokoro",
        message_id=123,
        voice=_make_voice(),
        generate_fn=fake_generate,
    )

    connect_listeners(graph, state)
    try:
        with GraphContext():
            await tts_agent._generate_chunk(chunk, GenerationContext())
    finally:
        disconnect_listeners(graph, state)

    assert generated_text == ["Hello there."]
    assert played == [(b"RIFF....WAVE", 123)]
