from pathlib import Path
from typing import TYPE_CHECKING
import structlog

from .schema import TALEMATE_ROOT, Voice, VoiceProvider

from .voice_library import get_instance

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.agents.tts.util")

__all__ = [
    "voice_parameter",
    "voice_is_talemate_asset",
    "voice_is_scene_asset",
    "get_voice",
]


def voice_parameter(
    voice: Voice, provider: VoiceProvider, name: str
) -> str | float | int | bool | None:
    """
    Get a parameter from the voice.
    """
    if name in voice.parameters:
        return voice.parameters[name]
    return provider.default_parameters.get(name)


def voice_is_talemate_asset(
    voice: Voice, provider: VoiceProvider
) -> tuple[bool, Path | None]:
    """
    Check if the voice is a Talemate asset.
    """

    if not provider.allow_file_upload:
        return False, None

    path = Path(voice.provider_id)
    if not path.is_absolute():
        path = TALEMATE_ROOT / path
    try:
        resolved = path.resolve(strict=False)
    except Exception as e:
        log.error(
            "voice_is_talemate_asset - invalid path",
            error=e,
            voice_id=voice.provider_id,
        )
        return False, None

    root = TALEMATE_ROOT.resolve()
    log.debug(
        "voice_is_talemate_asset - resolved", resolved=str(resolved), root=str(root)
    )
    if not str(resolved).startswith(str(root)):
        return False, None

    return True, resolved


def voice_is_scene_asset(voice: Voice, provider: VoiceProvider) -> bool:
    """
    Check if the voice is a scene asset.

    Scene assets are stored in the the scene's assets directory.

    This function does NOT check .is_scene_asset but does path resolution to
    determine if the voice is a scene asset.
    """

    is_talemate_asset, resolved = voice_is_talemate_asset(voice, provider)
    if not is_talemate_asset:
        return False

    SCENES_DIR = TALEMATE_ROOT / "scenes"

    if str(resolved).startswith(str(SCENES_DIR.resolve())):
        return True

    return False


def get_voice(scene: "Scene", voice_id: str) -> Voice | None:
    """Return a Voice by *voice_id* preferring the scene's library (if any).

    Args:
        scene: Scene instance or ``None``.
        voice_id: The fully-qualified voice identifier (``provider:provider_id``).

    The function first checks *scene.voice_library* (if present) and falls back
    to the global voice library instance.
    """

    try:
        if scene and getattr(scene, "voice_library", None):
            voice = scene.voice_library.get_voice(voice_id)
            if voice:
                return voice
    except Exception as e:
        log.error("get_voice - scene lookup failed", error=e)

    try:
        return get_instance().get_voice(voice_id)
    except Exception as e:
        log.error("get_voice - global lookup failed", error=e)
        return None
