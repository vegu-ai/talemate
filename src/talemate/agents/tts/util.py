import re
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from nltk.tokenize import sent_tokenize

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
    "split_long_chunk",
    "parse_chunks",
    "rejoin_chunks",
]


def split_long_chunk(text: str, chunk_size: int) -> list[str]:
    """
    Split a single chunk that exceeds chunk_size into smaller pieces.

    Tries to split on natural boundaries (commas, spaces) to avoid
    cutting words in half.

    Args:
        text: The text to split.
        chunk_size: Maximum size for each chunk.

    Returns:
        A list of text chunks, each at most chunk_size characters.
    """
    if len(text) <= chunk_size:
        return [text]

    result = []
    remaining = text

    while len(remaining) > chunk_size:
        # Find the best split point within chunk_size
        split_point = chunk_size

        # Try to split at a comma first (with space after)
        comma_pos = remaining.rfind(", ", 0, chunk_size)
        if comma_pos > chunk_size // 2:  # Only use if reasonably far into the chunk
            split_point = comma_pos + 2  # Include the comma and space
        else:
            # Fall back to splitting at a space
            space_pos = remaining.rfind(" ", 0, chunk_size)
            if space_pos > chunk_size // 2:
                split_point = space_pos + 1  # Include the space
            # else: hard split at chunk_size (no good boundary found)

        result.append(remaining[:split_point].strip())
        remaining = remaining[split_point:].strip()

    if remaining:
        result.append(remaining)

    return result


def parse_chunks(text: str) -> list[str]:
    """
    Takes a string and splits it into chunks based on punctuation.

    Uses NLTK's sent_tokenize to split text into sentences, with special
    handling for quoted dialogue to ensure proper sentence boundaries.

    Args:
        text: The text to split into chunks.

    Returns:
        A list of sentence chunks. In case of an error, returns the original
        text as a single chunk.
    """

    try:
        text = text.replace("*", "")

        # ensure sentence terminators are before quotes
        # otherwise the beginning of dialog will bleed into narration
        # Match a word followed by space and opening quote (where no punctuation precedes)
        text = re.sub(r'(\w) "', r'\1. "', text)

        # ensure sentence terminators after quotes when quote lacks one
        # e.g., "Hello world" he said -> "Hello world." he said
        text = re.sub(
            r'"([^"]+)"(\s+)([a-zA-Z])',
            lambda m: (
                f'"{m.group(1)}."{m.group(2)}{m.group(3)}'
                if m.group(1).rstrip()[-1:] not in ".!?"
                else f'"{m.group(1)}"{m.group(2)}{m.group(3)}'
            ),
            text,
        )

        text = text.replace("...", "__ellipsis__")
        chunks = sent_tokenize(text)
        cleaned_chunks = []

        for chunk in chunks:
            if not chunk.strip():
                continue
            cleaned_chunks.append(chunk)

        for i, chunk in enumerate(cleaned_chunks):
            chunk = chunk.replace("__ellipsis__", "...")
            cleaned_chunks[i] = chunk

        return cleaned_chunks
    except Exception as e:
        log.error("chunking error", error=e, text=text)
        return [text.replace("__ellipsis__", "...").replace("*", "")]


def rejoin_chunks(chunks: list[str], chunk_size: int = 250) -> list[str]:
    """
    Combine chunks split by punctuation into larger chunks up to chunk_size.

    Also handles splitting individual chunks that exceed chunk_size using
    split_long_chunk.

    Args:
        chunks: List of text chunks to potentially combine.
        chunk_size: Maximum size for each resulting chunk.

    Returns:
        A list of chunks where each is at most chunk_size characters.
    """

    joined_chunks = []
    current_chunk = ""

    for chunk in chunks:
        # If this single chunk exceeds chunk_size, split it first
        if len(chunk) > chunk_size:
            # Flush current chunk before adding the split pieces
            if current_chunk:
                joined_chunks.append(current_chunk)
                current_chunk = ""
            joined_chunks.extend(split_long_chunk(chunk, chunk_size))
            continue

        # Check if adding this chunk would exceed the limit (+ 1 for space)
        if current_chunk and len(current_chunk) + len(chunk) + 1 > chunk_size:
            joined_chunks.append(current_chunk)
            current_chunk = ""

        if current_chunk:
            current_chunk += " " + chunk
        else:
            current_chunk = chunk

    if current_chunk:
        joined_chunks.append(current_chunk)
    return joined_chunks


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
