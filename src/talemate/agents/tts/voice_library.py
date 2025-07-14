import structlog
from pathlib import Path

from .schema import VoiceLibrary, Voice

__all__ = [
    "load_voice_library",
    "save_voice_library",
    "save_instance",
    "get_instance",
    "add_default_voices",
    "DEFAULT_VOICES",
    "VOICE_LIBRARY_PATH",
]

log = structlog.get_logger("talemate.agents.tts.voice_library")

VOICE_LIBRARY_PATH = (
    Path(__file__).parent.parent.parent.parent.parent
    / "templates"
    / "voice"
    / "voice-library.json"
)

DEFAULT_VOICES = {}

# TODO: does this need to be made thread safe?
VOICE_LIBRARY = None


def load_voice_library() -> VoiceLibrary:
    """
    Load the voice library from the file.
    """
    try:
        with open(VOICE_LIBRARY_PATH, "r") as f:
            return VoiceLibrary.model_validate_json(f.read())
    except FileNotFoundError:
        library = VoiceLibrary(voices=DEFAULT_VOICES)
        save_voice_library(library)
        return library
    finally:
        log.debug("loaded voice library", path=str(VOICE_LIBRARY_PATH))


def save_voice_library(voice_library: VoiceLibrary):
    """
    Save the voice library to the file.
    """
    with open(VOICE_LIBRARY_PATH, "w") as f:
        f.write(voice_library.model_dump_json(indent=2))


def get_instance() -> VoiceLibrary:
    """
    Get the shared voice library instance.
    """
    global VOICE_LIBRARY
    if not VOICE_LIBRARY:
        VOICE_LIBRARY = load_voice_library()
    return VOICE_LIBRARY


def save_instance():
    """
    Save the shared voice library instance.
    """
    global VOICE_LIBRARY
    if VOICE_LIBRARY:
        save_voice_library(VOICE_LIBRARY)


def add_default_voices(voices: list[Voice]):
    """
    Add default voices to the voice library.
    """
    global DEFAULT_VOICES
    for voice in voices:
        DEFAULT_VOICES[voice.id] = voice


def voices_for_apis(apis: list[str], voice_library: VoiceLibrary) -> list[Voice]:
    """
    Get the voices for the given apis.
    """
    return [voice for voice in voice_library.voices.values() if voice.provider in apis]
