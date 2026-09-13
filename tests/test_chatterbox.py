import asyncio
import threading
import wave
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import jinja2
import numpy as np
import pydantic
import pytest

from talemate.agents.tts import TTSAgent
from talemate.agents.tts import chatterbox
from talemate.agents.tts import voice_library
from talemate.agents.tts.providers import provider
from talemate.agents.tts.schema import Chunk, GenerationContext, Voice, VoiceLibrary
import talemate.instance as instance


@pytest.fixture
def reference(tmp_path):
    def make(name="voice", seconds=6):
        path = tmp_path / f"{name}.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\0\0" * int(seconds * 16000))
        return str(path)

    return make


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(voice_library, "VOICE_LIBRARY", VoiceLibrary())
    return TTSAgent()


@pytest.fixture
def chunk(reference):
    return Chunk(
        text=["Hello [laugh] there."],
        type="dialogue",
        api="chatterbox_turbo",
        voice=Voice(label="Test", provider="chatterbox_turbo", provider_id=reference()),
    )


@pytest.fixture
def model_loader(monkeypatch):
    import torchaudio

    events = []
    references = []

    class Model:
        sr = 24000

        def __init__(self, variant, device):
            self.variant = variant
            self.device = device

        def generate(self, **kwargs):
            events.append((self.variant, self.device, kwargs))
            return b"waveform"

    def load(variant, device):
        assert all(ref() is None for ref in references), "Previous model still resident"
        model = Model(variant, device)
        references.append(weakref.ref(model))
        return model

    loader = Mock(side_effect=load)
    monkeypatch.setattr(chatterbox, "_load_chatterbox_model", loader)
    monkeypatch.setattr(
        torchaudio, "save", lambda path, wav, sr: Path(path).write_bytes(wav)
    )
    return SimpleNamespace(
        load=loader, events=events, references=references, model=Model
    )


def test_provider_is_opt_in_and_controls_are_model_specific(agent):
    assert "chatterbox_turbo" not in agent.actions["_config"].config["apis"].value
    assert "chatterbox_turbo" in {
        choice["value"] for choice in agent.actions["_config"].config["apis"].choices
    }
    standard = provider("chatterbox")
    turbo = provider("chatterbox_turbo")
    assert set(standard.default_parameters) == {
        "exaggeration",
        "cfg_weight",
        "temperature",
    }
    assert turbo.default_parameters == chatterbox.TurboParameters().model_dump()
    assert not turbo.allow_model_override
    assert turbo.allow_file_upload
    assert turbo.default_voice_dir.name == "chatterbox_turbo"
    agent.actions["chatterbox_turbo"].config["chunk_size"].value = 128
    assert agent.chatterbox_chunk_size == 256
    assert agent.chatterbox_turbo_chunk_size == 128


def test_real_upstream_loudness_normalization_preserves_float32(monkeypatch):
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    monkeypatch.setattr(
        ChatterboxTurboTTS,
        "from_pretrained",
        classmethod(lambda cls, device: object.__new__(cls)),
    )
    model = chatterbox._load_chatterbox_model("chatterbox_turbo", "cpu")
    samples = (0.1 * np.sin(np.arange(24000, dtype=np.float32) * 0.1)).astype(
        np.float32
    )
    upstream = ChatterboxTurboTTS.norm_loudness(model, samples, 24000)
    normalized = model.norm_loudness(samples, 24000)
    assert normalized.dtype == np.float32
    np.testing.assert_allclose(normalized, upstream, rtol=1e-6)
    assert not np.allclose(normalized, samples)


async def test_existing_library_migrates_and_roundtrips_without_altering_standard(
    tmp_path, monkeypatch
):
    path = tmp_path / "library.json"
    standard = Voice(
        label="Old",
        provider="chatterbox",
        provider_id="old.wav",
        parameters={"exaggeration": 1.3, "cfg_weight": 0.2, "temperature": 0.7},
    )
    path.write_text(VoiceLibrary(voices={standard.id: standard}).model_dump_json())
    monkeypatch.setattr(voice_library, "VOICE_LIBRARY_PATH", path)
    library = await voice_library.load_voice_library()
    assert library.voices[standard.id] == standard
    turbo = [v for v in library.voices.values() if v.provider == "chatterbox_turbo"]
    assert len(turbo) == 7
    turbo[0].parameters = {"norm_loudness": False, "top_k": 20}
    await voice_library.save_voice_library(library)
    reloaded = await voice_library.load_voice_library()
    assert reloaded.voices[turbo[0].id].parameters == turbo[0].parameters
    assert reloaded.voices[standard.id] == standard


@pytest.mark.parametrize("seconds", [0, 1, 5])
async def test_short_reference_fails_before_model_load(
    agent, chunk, reference, seconds, model_loader, monkeypatch
):
    chunk.voice.provider_id = reference(seconds=seconds)
    emitted = Mock()
    monkeypatch.setattr(chatterbox, "emit", emitted)
    with pytest.raises(ValueError, match="longer than 5 seconds"):
        await agent.chatterbox_turbo_generate(chunk, GenerationContext())
    model_loader.load.assert_not_called()
    assert emitted.call_args.kwargs["status"] == "error"
    assert "longer than 5 seconds" in emitted.call_args.kwargs["message"]


def test_reference_boundary_and_unreadable(reference, tmp_path):
    chatterbox.validate_turbo_reference(reference(seconds=5.001))
    with pytest.raises(
        ValueError, match="Cannot read Chatterbox Turbo voice reference"
    ):
        chatterbox.validate_turbo_reference(str(tmp_path / "missing.wav"))
    invalid = tmp_path / "bad.wav"
    invalid.write_text("not audio")
    with pytest.raises(ValueError, match="Cannot read"):
        chatterbox.validate_turbo_reference(str(invalid))


@pytest.mark.parametrize("api", ["chatterbox", "chatterbox_turbo"])
def test_removing_bundled_voice_preserves_shared_reference(
    agent, reference, monkeypatch, tmp_path, api
):
    path = Path(reference("bundled"))
    default = Voice(label="Bundled", provider="chatterbox", provider_id=path.name)
    monkeypatch.setattr(chatterbox, "TALEMATE_ROOT", tmp_path)
    monkeypatch.setattr(chatterbox, "DEFAULT_VOICES", {default.id: default})
    monkeypatch.setattr(
        chatterbox, "voice_is_talemate_asset", lambda *args: (True, path)
    )
    agent.api_method(api, "delete_voice")(
        Voice(label="Bundled", provider=api, provider_id=str(path))
    )
    assert path.is_file()


def test_removing_uploaded_turbo_voice_cleans_owned_file(agent, reference, monkeypatch):
    path = Path(reference("uploaded"))
    monkeypatch.setattr(
        chatterbox, "voice_is_talemate_asset", lambda *args: (True, path)
    )
    agent.chatterbox_turbo_delete_voice(
        Voice(label="Uploaded", provider="chatterbox_turbo", provider_id=str(path))
    )
    assert not path.exists()


@pytest.mark.parametrize(
    "parameters",
    [
        {"temperature": 0},
        {"temperature": float("nan")},
        {"top_p": 1.1},
        {"top_k": -1},
        {"top_k": 1.5},
        {"repetition_penalty": 0},
        {"norm_loudness": "invalid"},
    ],
)
async def test_invalid_controls_fail_before_loading(
    agent, chunk, model_loader, parameters
):
    chunk.voice.parameters = parameters
    with pytest.raises(pydantic.ValidationError):
        await agent.chatterbox_turbo_generate(chunk, GenerationContext())
    model_loader.load.assert_not_called()


async def test_turbo_filters_stale_controls_without_mutating_saved_voice(
    agent, chunk, model_loader
):
    parameters = {
        "exaggeration": 1.5,
        "cfg_weight": 0.9,
        "min_p": 0.1,
        "temperature": 0.65,
        "top_k": 40,
        "top_p": 0.8,
        "repetition_penalty": 1.4,
        "norm_loudness": False,
    }
    chunk.voice.parameters = parameters.copy()
    result = await agent.chatterbox_turbo_generate(chunk, GenerationContext())
    assert result == b"waveform"
    kwargs = model_loader.events[0][2]
    assert kwargs == {
        "text": "Hello [laugh] there.",
        "audio_prompt_path": chunk.voice.provider_id,
        "temperature": 0.65,
        "top_k": 40,
        "top_p": 0.8,
        "repetition_penalty": 1.4,
        "norm_loudness": False,
    }
    assert chunk.voice.parameters == parameters


async def test_model_device_switch_releases_previous_and_voice_refreshes_each_chunk(
    agent, chunk, model_loader, reference
):
    agent.actions["chatterbox_turbo"].config["device"].value = "cpu"
    await agent.chatterbox_turbo_generate(chunk, GenerationContext())
    chunk.voice.provider_id = reference("other")
    chunk.voice.parameters["norm_loudness"] = False
    await agent.chatterbox_turbo_generate(chunk, GenerationContext())
    assert model_loader.load.call_count == 1
    assert model_loader.events[-1][2]["audio_prompt_path"].endswith("other.wav")
    assert model_loader.events[-1][2]["norm_loudness"] is False
    agent.actions["chatterbox_turbo"].config["device"].value = "cuda"
    await agent.chatterbox_turbo_generate(chunk, GenerationContext())
    chunk.voice.provider = "chatterbox"
    chunk.voice.parameters = {"exaggeration": 1.2, "cfg_weight": 0.3}
    await agent.chatterbox_prepare_chunk(chunk)
    await agent.chatterbox_generate(chunk, GenerationContext())
    assert model_loader.events[-1][0] == "chatterbox"
    assert model_loader.events[-1][2]["exaggeration"] == 1.2
    assert model_loader.events[-1][2]["cfg_weight"] == 0.3
    await agent.chatterbox_turbo_generate(chunk, GenerationContext())
    assert model_loader.load.call_count == 4
    assert sum(ref() is not None for ref in model_loader.references) == 1


async def test_failed_load_does_not_poison_cache(agent, chunk, model_loader):
    original_load = model_loader.load.side_effect
    model_loader.load.side_effect = RuntimeError("load failed")
    with pytest.raises(RuntimeError, match="load failed"):
        await agent.chatterbox_turbo_generate(chunk, GenerationContext())
    assert agent.chatterbox_instance is None
    model_loader.load.side_effect = original_load
    assert (
        await agent.chatterbox_turbo_generate(chunk, GenerationContext()) == b"waveform"
    )


async def test_cancellation_keeps_worker_serialized_and_output_alive(
    agent, chunk, model_loader, monkeypatch
):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original = model_loader.model.generate

    def generate(model, **kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(10)
            result = original(model, **kwargs)
            finished.set()
            return result
        assert finished.is_set()
        return original(model, **kwargs)

    monkeypatch.setattr(model_loader.model, "generate", generate)
    first = asyncio.create_task(
        agent.chatterbox_turbo_generate(chunk, GenerationContext())
    )
    try:
        assert await asyncio.to_thread(started.wait, 10)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(
            agent.chatterbox_generate(chunk, GenerationContext())
        )
        await asyncio.sleep(0.05)
        assert model_loader.load.call_count == 1
        assert not second.done()
        release.set()
        assert await asyncio.wait_for(second, 10) == b"waveform"
        assert len(model_loader.events) == 2
    finally:
        release.set()


async def test_cancelled_waiter_skips_model_work(
    agent, chunk, model_loader, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    waiting = [threading.Event() for _ in range(3)]

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.count = 0

        def __enter__(self):
            index = self.count
            self.count += 1
            waiting[index].set()
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()

    agent._chatterbox_lock = ObservedLock()
    original = model_loader.model.generate

    def generate(model, **kwargs):
        if kwargs["text"] == "A running.":
            started.set()
            assert release.wait(10)
        return original(model, **kwargs)

    monkeypatch.setattr(model_loader.model, "generate", generate)

    def request(text, variant):
        request_chunk = chunk.model_copy(deep=True, update={"text": [text]})
        return asyncio.create_task(agent._chatterbox_generate(variant, request_chunk))

    first = request("A running", "chatterbox")
    try:
        assert await asyncio.to_thread(started.wait, 10)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = request("B discarded", "chatterbox_turbo")
        assert await asyncio.to_thread(waiting[1].wait, 10)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        third = request("C current", "chatterbox")
        assert await asyncio.to_thread(waiting[2].wait, 10)
        release.set()
        assert await asyncio.wait_for(third, 10) == b"waveform"
        assert [event[2]["text"] for event in model_loader.events] == [
            "A running.",
            "C current.",
        ]
        model_loader.load.assert_called_once()
        assert agent.chatterbox_instance.variant == "chatterbox"
    finally:
        release.set()


async def test_audio_tag_injection_remains_opt_in_and_model_specific(agent, chunk):
    summarizer = SimpleNamespace(inject_audio_tags_for_tts=AsyncMock())
    await agent._inject_audio_tags([chunk], summarizer)
    summarizer.inject_audio_tags_for_tts.assert_not_called()

    assert agent.chunk_supports_audio_tags(chunk)
    chunk.api = "chatterbox"
    chunk.model = "name-containing-turbo"
    assert not agent.chunk_supports_audio_tags(chunk)
    agent.actions["_config"].config["audio_tags"].value = True
    await agent._inject_audio_tags([chunk], summarizer)
    summarizer.inject_audio_tags_for_tts.assert_not_called()


async def test_turbo_routes_and_chunks_without_llm_requests(agent, chunk, monkeypatch):
    summarizer = SimpleNamespace(
        markup_context_for_tts=AsyncMock(), inject_audio_tags_for_tts=AsyncMock()
    )
    monkeypatch.setitem(instance.AGENTS, "summarizer", summarizer)
    agent.is_enabled = True
    agent.actions["_config"].config["apis"].value = ["chatterbox_turbo"]
    agent.actions["_config"].config["speaker_separation"].value = "none"
    agent.actions["_config"].config["narrator_voice_id"].value = chunk.voice.id
    agent.actions["chatterbox_turbo"].config["chunk_size"].value = 128
    agent.voice_library.voices[chunk.voice.id] = chunk.voice
    agent.scene = SimpleNamespace(
        environment="scene", voice_library=VoiceLibrary(), agent_state={}
    )
    agent.emit_status = AsyncMock()
    agent.set_background_processing = AsyncMock()
    agent._generate_chunk = AsyncMock()
    text = (
        "We followed the path through the garden. The river flowed quietly past the houses. "
        * 5
    )
    await agent.generate(text)
    if agent._queue_task:
        await asyncio.wait_for(agent._queue_task, 5)
    generated = [
        sub_chunk
        for call in agent._generate_chunk.call_args_list
        for sub_chunk in call.args[0].sub_chunks
    ]
    assert len(generated) > 1
    assert all(c.api == "chatterbox_turbo" for c in generated)
    assert all(c.generate_fn == agent.chatterbox_turbo_generate for c in generated)
    assert all(c.prepare_fn is None for c in generated)
    assert all(len(c.text[0]) <= 128 for c in generated)
    summarizer.markup_context_for_tts.assert_not_called()
    summarizer.inject_audio_tags_for_tts.assert_not_called()


@pytest.mark.parametrize("injected", [False, True])
async def test_native_tag_survives_default_scene_chunk_boundary(
    agent, chunk, model_loader, monkeypatch, injected
):
    tagged = "word " * 49 + "[clear throat] Hello."
    summarizer = SimpleNamespace(
        markup_context_for_tts=AsyncMock(),
        inject_audio_tags_for_tts=AsyncMock(return_value={0: tagged}),
    )
    monkeypatch.setitem(instance.AGENTS, "summarizer", summarizer)
    agent.is_enabled = True
    agent.actions["_config"].config["apis"].value = ["chatterbox_turbo"]
    agent.actions["_config"].config["speaker_separation"].value = "none"
    agent.actions["_config"].config["narrator_voice_id"].value = chunk.voice.id
    agent.actions["_config"].config["audio_tags"].value = injected
    assert agent.chatterbox_turbo_chunk_size == 256
    agent.voice_library.voices[chunk.voice.id] = chunk.voice
    agent.scene = SimpleNamespace(
        environment="scene", voice_library=VoiceLibrary(), agent_state={}
    )
    agent.emit_status = AsyncMock()
    agent.set_background_processing = AsyncMock()
    agent.get_audio_tags_cache = AsyncMock(return_value=None)
    agent.set_audio_tags_cache = AsyncMock()
    agent.play_audio = Mock()
    await agent.generate(
        tagged.replace("[clear throat] ", "") if injected else tagged,
        character=SimpleNamespace(name="Eva", voice=chunk.voice),
    )
    if agent._queue_task:
        await asyncio.wait_for(agent._queue_task, 10)
    texts = [event[2]["text"] for event in model_loader.events]
    assert len(texts) == 2
    assert all(len(text) <= 256 for text in texts)
    assert texts[0] == ("word " * 49).strip() + "."
    assert texts[1] == "[clear throat] Hello."
    summarizer.markup_context_for_tts.assert_not_called()
    assert summarizer.inject_audio_tags_for_tts.await_count == int(injected)


@pytest.mark.parametrize("turbo_first", [True, False])
async def test_mixed_provider_prompt_preserves_each_format(agent, chunk, turbo_first):
    agent.actions["_config"].config["audio_tags"].value = True
    agent.actions["elevenlabs"].config["audio_tag_format"].value = "<{{ tag }}>"
    agent.get_audio_tags_cache = AsyncMock(return_value=None)
    agent.set_audio_tags_cache = AsyncMock()
    eleven = chunk.model_copy(
        deep=True, update={"api": "elevenlabs", "model": "eleven_v3"}
    )
    chunks = [chunk, eleven] if turbo_first else [eleven, chunk]
    rendered = []

    async def render(**kwargs):
        env = jinja2.Environment(
            loader=jinja2.DictLoader(
                {
                    "prompt": Path(
                        "src/talemate/prompts/templates/summarizer/inject-audio-tags-for-tts.jinja2"
                    ).read_text(),
                    "content-classification.jinja2": "",
                }
            )
        )
        rendered.append(
            env.get_template("prompt").render(
                **kwargs,
                scene=SimpleNamespace(characters=[]),
                set_anchor_extractor=lambda *args: "",
                set_prepared_response=lambda *args: "",
            )
        )
        return {}

    summarizer = SimpleNamespace(
        inject_audio_tags_for_tts=AsyncMock(side_effect=render)
    )
    await agent._inject_audio_tags(chunks, summarizer)
    summarizer.inject_audio_tags_for_tts.assert_awaited_once()
    turbo_idx = 0 if turbo_first else 1
    eleven_idx = 1 - turbo_idx
    assert f"CHUNK_{turbo_idx} audio-tag format: [{{{{ tag }}}}]" in rendered[0]
    assert f"CHUNK_{turbo_idx} allowed tags: [clear throat]" in rendered[0]
    assert f"CHUNK_{eleven_idx} audio-tag format: <{{{{ tag }}}}>" in rendered[0]
    assert f"CHUNK_{eleven_idx} policy: completely free-form" in rendered[0]
    assert "<whispering>" in rendered[0]
    assert "[whispering]" not in rendered[0]


async def test_finite_tags_and_cache_identity(agent, chunk):
    agent.actions["_config"].config["audio_tags"].value = True
    agent.get_audio_tags_cache = AsyncMock(return_value=None)
    agent.set_audio_tags_cache = AsyncMock()
    chunk.text = ["Hello [authored] there."]
    summarizer = SimpleNamespace(
        inject_audio_tags_for_tts=AsyncMock(
            return_value={0: "Hello [authored] [whispering] [laugh] there."}
        )
    )
    await agent._inject_audio_tags([chunk], summarizer)
    assert "[authored]" in chunk.text[0]
    assert "[laugh]" in chunk.text[0]
    assert "[whispering]" not in chunk.text[0]
    entries = summarizer.inject_audio_tags_for_tts.call_args.kwargs["chunk_entries"]
    assert entries[0]["allowed_tags"] == chatterbox.TURBO_AUDIO_TAGS
    turbo_key = agent.get_audio_tags_cache.call_args.args[0]
    chunk.api, chunk.model = "elevenlabs", "eleven_v3"
    chunk.text = ["Hello [authored] there."]
    await agent._inject_audio_tags([chunk], summarizer)
    assert agent.get_audio_tags_cache.call_args.args[0] != turbo_key
    assert "[whispering]" in chunk.text[0]


@pytest.mark.parametrize("restricted", [True, False])
def test_tag_prompt_honors_finite_vocabulary(restricted):
    path = Path(
        "src/talemate/prompts/templates/summarizer/inject-audio-tags-for-tts.jinja2"
    )
    env = jinja2.Environment(
        loader=jinja2.DictLoader(
            {
                "prompt": path.read_text(),
                "content-classification.jinja2": "",
            }
        )
    )
    rendered = env.get_template("prompt").render(
        scene=SimpleNamespace(characters=[]),
        tag_format="[{{ tag }}]",
        set_anchor_extractor=lambda *args: "",
        set_prepared_response=lambda *args: "",
        chunk_entries=[
            dict(
                index=0,
                text="Hello",
                character_name=None,
                eligible=True,
                allowed_tags=chatterbox.TURBO_AUDIO_TAGS if restricted else None,
            )
        ],
    )
    if restricted:
        assert "CHUNK_0 allowed tags:" in rendered
        assert "[laugh]" in rendered
        assert "completely free-form" not in rendered
        assert "[whispering]" not in rendered
    else:
        assert "completely free-form" in rendered
        assert "[whispering]" in rendered
