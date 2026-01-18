import structlog
from pathlib import Path  #
import pydantic
from collections import defaultdict

import talemate.emit.async_signals as async_signals

from .schema import VoiceLibrary, Voice
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "load_voice_library",
    "save_voice_library",
    "get_instance",
    "add_default_voices",
    "DEFAULT_VOICES",
    "VOICE_LIBRARY_PATH",
    "require_instance",
    "load_scene_voice_library",
    "save_scene_voice_library",
    "scoped_voice_library",
]

log = structlog.get_logger("talemate.agents.tts.voice_library")

async_signals.register(
    "voice_library.update.before",
    "voice_library.update.after",
)

VOICE_LIBRARY_PATH = (
    Path(__file__).parent.parent.parent.parent.parent
    / "tts"
    / "voice"
    / "voice-library.json"
)


DEFAULT_VOICES = {}

# TODO: does this need to be made thread safe?
VOICE_LIBRARY = None


class ScopedVoiceLibrary(pydantic.BaseModel):
    voice_library: VoiceLibrary
    fn_save: Callable[[VoiceLibrary], None]

    async def save(self):
        await self.fn_save(self.voice_library)


def scoped_voice_library(
    scope: Literal["global", "scene"], scene: "Scene | None" = None
) -> ScopedVoiceLibrary:
    if scope == "global":
        return ScopedVoiceLibrary(
            voice_library=get_instance(), fn_save=save_voice_library
        )
    else:
        if not scene:
            raise ValueError("Scene is required for scoped voice library")

        async def _save(library: VoiceLibrary):
            await save_scene_voice_library(scene, library)

        return ScopedVoiceLibrary(voice_library=scene.voice_library, fn_save=_save)


async def require_instance():
    global VOICE_LIBRARY
    if not VOICE_LIBRARY:
        VOICE_LIBRARY = await load_voice_library()
    return VOICE_LIBRARY


async def load_voice_library() -> VoiceLibrary:
    """
    Load the voice library from the file.
    """
    try:
        with open(VOICE_LIBRARY_PATH, "r") as f:
            library = VoiceLibrary.model_validate_json(f.read())
    except FileNotFoundError:
        library = VoiceLibrary(voices=DEFAULT_VOICES)
        await save_voice_library(library)
        return library
    else:
        # Migration: if a provider has zero voices in an existing library file,
        # populate it with that provider's bundled defaults.
        if _apply_default_voice_migration(library):
            await save_voice_library(library)
        return library
    finally:
        log.debug("loaded voice library", path=str(VOICE_LIBRARY_PATH))


async def save_voice_library(voice_library: VoiceLibrary):
    """
    Save the voice library to the file.
    """
    await async_signals.get("voice_library.update.before").send(voice_library)
    with open(VOICE_LIBRARY_PATH, "w") as f:
        f.write(voice_library.model_dump_json(indent=2))
    await async_signals.get("voice_library.update.after").send(voice_library)


def get_instance() -> VoiceLibrary:
    """
    Get the shared voice library instance.
    """
    if not VOICE_LIBRARY:
        raise RuntimeError("Voice library not loaded yet.")
    return VOICE_LIBRARY


def add_default_voices(voices: list[Voice]):
    """
    Add default voices to the voice library.
    """
    global DEFAULT_VOICES
    for voice in voices:
        DEFAULT_VOICES[voice.id] = voice


def _apply_default_voice_migration(voice_library: VoiceLibrary) -> bool:
    """Ensure providers with no existing voices get their bundled defaults.

    This is a small "migration" to handle upgrades where new providers (or new
    default-voice bundles) are introduced after the user already has an existing
    `voice-library.json` on disk.

    Rule:
    - If **any** voice exists for a provider, we do **not** add defaults for that provider.
    - If **no** voices exist for a provider, we add *all* default voices for that provider.
    """

    existing_providers = {v.provider for v in voice_library.voices.values()}

    defaults_by_provider: dict[str, list[Voice]] = defaultdict(list)
    for v in DEFAULT_VOICES.values():
        defaults_by_provider[v.provider].append(v)

    changed = False
    for provider_name, default_voices in defaults_by_provider.items():
        if provider_name in existing_providers:
            continue
        for v in default_voices:
            if v.id not in voice_library.voices:
                voice_library.voices[v.id] = v
                changed = True

    return changed


def voices_for_apis(apis: list[str], voice_library: VoiceLibrary) -> list[Voice]:
    """
    Get the voices for the given apis.
    """
    return [voice for voice in voice_library.voices.values() if voice.provider in apis]


def _scene_library_path(scene: "Scene") -> Path:
    """Return the path to the *scene* voice-library.json file."""

    return Path(scene.info_dir) / "voice-library.json"


async def load_scene_voice_library(scene: "Scene") -> VoiceLibrary:
    """Load and return the voice library for *scene*.

    If the file does not exist an empty ``VoiceLibrary`` instance is returned.
    The returned instance is *not* stored on the scene – caller decides.
    """

    path = _scene_library_path(scene)

    try:
        if path.exists():
            with open(path, "r") as f:
                library = VoiceLibrary.model_validate_json(f.read())
        else:
            library = VoiceLibrary()
    except Exception as e:
        log.error("load_scene_voice_library", error=e, path=str(path))
        library = VoiceLibrary()

    return library


async def save_scene_voice_library(scene: "Scene", library: VoiceLibrary):
    """Persist *library* to the scene's ``voice-library.json``.

    The directory ``scene/{name}/info`` is created if necessary.
    """

    path = _scene_library_path(scene)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(library.model_dump_json(indent=2))
    except Exception as e:
        log.error("save_scene_voice_library", error=e, path=str(path))
