"""OpenAI-compatible TTS endpoints — multi-backend.

This mixin exposes a single management section in the TTS agent settings
("OpenAI Compatible") that lets the user register any number of named backends.
Each registered backend renders as its own expansion panel below the management
section and carries its own URL/key/model/voice list.

The mixin's per-backend helpers follow the dynamic-registry naming convention
(``_<registry_key>_<name>(slug, ...)``) so the TTSAgent's ``api_attr`` /
``api_method`` resolvers can reach them directly through the framework.
"""

from typing import Union
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from openai import APIError, AsyncOpenAI

from talemate.emit import emit
from talemate.ux.schema import Action
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentDetail,
    DYNAMIC_CHILDREN_FIELD,
)
from .schema import Voice, VoiceLibrary, Chunk, GenerationContext, INFO_CHUNK_SIZE

log = structlog.get_logger("talemate.agents.tts.openai_compatible")

REGISTRY_KEY = "openai_compatible"

# Always sent: servers differ in their default, and Fish Audio's default is
# headerless pcm, which the browser's decodeAudioData cannot play.
DEFAULT_RESPONSE_FORMAT = "mp3"

OPENAI_COMPATIBLE_INFO = """
Connect to any TTS service that exposes an OpenAI-compatible `/v1/audio/speech` endpoint (e.g. vLLM, LocalAI, Speaches, etc.).

Add a backend below — voices are auto-fetched when your server supports listing them, otherwise add them manually in the Voice Library.
"""

# Probe paths used when the backend doesn't specify a custom voices_endpoint.
# These are *relative* to the configured base URL — the convention is that the
# user's base URL already includes the API version segment (e.g. ".../v1"), so
# we resolve the probes underneath it.
#
# Known servers and their listing paths:
#   - KoboldCPP:        /v1/audio/voices            -> "audio/voices"
#                       (returns {"status":"ok","voices":[...]})
#   - Speaches:         /v1/audio/speech/voices     -> "audio/speech/voices"
#   - openedai-speech:  /v1/voices                  -> "voices"
#   - OpenAI proper:    no listing endpoint         (voices are documented values)
DEFAULT_VOICE_LISTING_PATHS = (
    "audio/voices",
    "audio/speech/voices",
    "voices",
)

MAX_VOICE_LISTING_PAGES = 50


def _resolve_voices_url(api_url: str, candidate: str) -> str:
    """Resolve a voice-listing path against the user's API base URL.

    Three idioms are supported:

    - Full URL (``http(s)://...``) — used as-is.
    - Absolute path starting with ``/`` — anchored to the base URL's host
      root, replacing any path component the base URL had.
    - Relative path — appended underneath the base URL (so a base URL of
      ``https://host/v1`` plus ``audio/speech/voices`` yields
      ``https://host/v1/audio/speech/voices``).
    """
    if candidate.startswith(("http://", "https://")):
        return candidate
    if candidate.startswith("/"):
        parsed = urlparse(api_url)
        return f"{parsed.scheme}://{parsed.netloc}{candidate}"
    return urljoin(api_url.rstrip("/") + "/", candidate)


class OpenAICompatibleMixin:
    """OpenAI-compatible TTS endpoint mixin (multi-backend)."""

    # ------------------------------------------------------------------
    # Action setup
    # ------------------------------------------------------------------

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        # The static management section. No generation config — it only carries
        # the dynamic-children registry blob.
        actions[REGISTRY_KEY] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="OpenAI Compatible",
            description=(
                "Manage OpenAI-compatible TTS backends. Each backend you add "
                "appears as its own section below."
            ),
            dynamic_registry_component="TTSOpenAICompatibleBackends",
            config={
                DYNAMIC_CHILDREN_FIELD: AgentActionConfig(
                    type="blob",
                    value="[]",
                    label="Registered backends",
                    description=(
                        "Internal — managed by the Add Backend UI in this section."
                    ),
                    scene_overridable=False,
                ),
            },
        )
        return actions

    @classmethod
    def add_voices(cls, voices: dict[str, VoiceLibrary]):
        # No-op — voices are produced per backend at runtime via auto-fetch.
        return voices

    # ------------------------------------------------------------------
    # Per-backend factory (called by Agent.install_dynamic_children)
    # ------------------------------------------------------------------

    @staticmethod
    def build_backend_action(slug: str, label: str) -> AgentAction:
        return AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-network",
            label=label,
            parent_key=REGISTRY_KEY,
            description=(
                "OpenAI-compatible TTS backend. Voices auto-fetch on save when "
                "the server supports listing them."
            ),
            config={
                "api_url": AgentActionConfig(
                    type="text",
                    value="http://localhost:8000/v1",
                    label="API Base URL",
                    description=(
                        "Base URL of the OpenAI-compatible TTS server "
                        "(e.g. http://localhost:8000/v1)"
                    ),
                    scene_overridable=False,
                ),
                "api_key": AgentActionConfig(
                    type="password",
                    value="",
                    label="API Key",
                    description="API key for the server (leave empty if not required)",
                ),
                "model": AgentActionConfig(
                    type="text",
                    value="tts-1",
                    label="Model",
                    description="Model identifier to send in requests",
                    scene_overridable=False,
                ),
                "response_format": AgentActionConfig(
                    type="text",
                    value=DEFAULT_RESPONSE_FORMAT,
                    label="Response format",
                    description=(
                        "Audio format to request from the server (e.g. mp3, wav, "
                        "opus). The browser must be able to play it, so raw pcm "
                        "does not work. Leave empty for mp3."
                    ),
                    scene_overridable=False,
                ),
                "voices_endpoint": AgentActionConfig(
                    type="text",
                    value="",
                    label="Voices endpoint (optional)",
                    description=(
                        "Override path or absolute URL for the voice-listing "
                        "endpoint. Leave empty to probe common defaults."
                    ),
                    scene_overridable=False,
                ),
                "chunk_size": AgentActionConfig(
                    type="number",
                    min=0,
                    step=64,
                    max=2048,
                    value=512,
                    label="Chunk size",
                    note=INFO_CHUNK_SIZE,
                    scene_overridable=False,
                ),
            },
        )

    # ------------------------------------------------------------------
    # Per-backend property helpers (resolved via dynamic_attr / dynamic_method)
    # ------------------------------------------------------------------

    def _backend_config(self, backend: str) -> dict:
        action = self.actions.get(backend)
        if not action or not action.config:
            return {}
        return {k: v.value for k, v in action.config.items()}

    def _openai_compatible_api_url(self, backend: str) -> str:
        return self._backend_config(backend).get("api_url", "") or ""

    def _openai_compatible_api_key(self, backend: str) -> str:
        return self._backend_config(backend).get("api_key", "") or ""

    def _openai_compatible_model(self, backend: str) -> str:
        return self._backend_config(backend).get("model", "") or "tts-1"

    def _openai_compatible_response_format(self, backend: str) -> str:
        value = self._backend_config(backend).get("response_format") or ""
        return value.strip() or DEFAULT_RESPONSE_FORMAT

    def _openai_compatible_voices_endpoint(self, backend: str) -> str:
        return self._backend_config(backend).get("voices_endpoint", "") or ""

    def _openai_compatible_chunk_size(self, backend: str) -> int:
        value = self._backend_config(backend).get("chunk_size", 0)
        return int(value or 0)

    def _openai_compatible_max_generation_length(self, backend: str) -> int:
        return 1024

    def _openai_compatible_configured(self, backend: str) -> bool:
        return bool(self._openai_compatible_api_url(backend))

    def _openai_compatible_info(self, backend: str) -> str:
        return OPENAI_COMPATIBLE_INFO

    def _openai_compatible_not_configured_reason(self, backend: str) -> str | None:
        if not self._openai_compatible_api_url(backend):
            return "API base URL not set"
        return None

    def _openai_compatible_not_configured_action(self, backend: str) -> Action | None:
        if not self._openai_compatible_api_url(backend):
            return Action(
                action_name="openAgentSettings",
                arguments=["tts", backend],
                label="Set API URL",
                icon="mdi-link",
            )
        return None

    def _openai_compatible_supports_mixing(self, backend: str) -> bool:
        return False

    def _openai_compatible_supports_audio_tags(self, backend: str) -> bool:
        return False

    def _openai_compatible_model_choices(self, backend: str) -> list[dict]:
        return []

    def _openai_compatible_agent_details(self, backend: str) -> dict:
        details: dict = {}
        api_url = self._openai_compatible_api_url(backend)
        if not api_url:
            details[f"{backend}_url"] = AgentDetail(
                icon="mdi-link",
                value="API URL not set",
                description=(
                    f"Set the base URL of the '{backend}' OpenAI-compatible TTS server."
                ),
                color="error",
            ).model_dump()
        else:
            details[f"{backend}_url"] = AgentDetail(
                icon="mdi-link",
                value=api_url,
                description="OpenAI-compatible TTS endpoint",
            ).model_dump()
            details[f"{backend}_model"] = AgentDetail(
                icon="mdi-brain",
                value=self._openai_compatible_model(backend),
                description="Model identifier",
            ).model_dump()
        return details

    async def _openai_compatible_generate(
        self,
        backend: str,
        chunk: Chunk,
        context: GenerationContext,
    ) -> Union[bytes, None]:
        api_key = self._openai_compatible_api_key(backend) or "no-key"
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=self._openai_compatible_api_url(backend),
        )
        model = chunk.model or self._openai_compatible_model(backend)
        try:
            response = await client.audio.speech.create(
                model=model,
                voice=chunk.voice.provider_id,
                input=chunk.cleaned_text,
                # free text: the SDK types response_format as OpenAI's own formats
                extra_body={
                    "response_format": self._openai_compatible_response_format(backend)
                },
            )
        except APIError as exc:
            action = self.actions.get(backend)
            label = action.label if action else backend
            emit("status", message=f"{label}: {exc.message}", status="error")
            raise
        return response.content

    # ------------------------------------------------------------------
    # Voice auto-fetch
    # ------------------------------------------------------------------

    async def _openai_compatible_fetch_voices(self, backend: str) -> list[Voice] | None:
        """Fetch the list of voices the configured backend exposes.

        Tries the user-supplied ``voices_endpoint`` first; falls back to a
        small set of well-known paths. Tolerates the most common response
        shapes and reads every page of a paged listing. Returns the voices of
        the first listing that has any, an empty list when a listing answered
        with no voices, and None when no endpoint gave a complete listing: a
        failure must not read as a server without voices. A listing that
        cannot be read in full also gives None, whatever the other paths
        answered.
        """
        api_url = self._openai_compatible_api_url(backend)
        if not api_url:
            return None

        api_key = self._openai_compatible_api_key(backend)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        custom = self._openai_compatible_voices_endpoint(backend)
        candidates = [custom] if custom else list(DEFAULT_VOICE_LISTING_PATHS)

        attempted: list[str] = []
        empty_listing = False
        async with httpx.AsyncClient(timeout=10.0) as http:
            for candidate in candidates:
                url = _resolve_voices_url(api_url, candidate)
                attempted.append(url)
                try:
                    voices = await _read_voice_listing(http, url, headers, backend)
                except IncompleteVoiceListing as exc:
                    log.warning(
                        "voice listing could not be read in full",
                        backend=backend,
                        url=url,
                        reason=str(exc),
                    )
                    return None
                if voices:
                    log.info(
                        "voice fetch succeeded",
                        backend=backend,
                        url=url,
                        count=len(voices),
                    )
                    return voices
                empty_listing = empty_listing or voices is not None
        if empty_listing:
            log.info("voice listing is empty", backend=backend, attempted=attempted)
            return []
        log.info(
            "voice fetch found no listing endpoint",
            backend=backend,
            attempted=attempted,
            hint=(
                "this server does not expose a voice-listing API (OpenAI proper "
                "does not; Speaches and openedai-speech do). Add voices manually "
                "via the Voice Library, or set a custom voices_endpoint on the "
                "backend if your server uses a non-standard path."
            ),
        )
        return None


async def _get_listing_page(
    http: httpx.AsyncClient, url: httpx.URL, headers: dict, backend: str
):
    """The JSON payload at *url*; None when the request fails."""
    try:
        response = await http.get(url, headers=headers)
    except httpx.HTTPError as exc:
        log.debug("voice fetch failed", backend=backend, url=str(url), error=str(exc))
        return None
    if response.status_code != 200:
        log.debug(
            "voice fetch non-200",
            backend=backend,
            url=str(url),
            status=response.status_code,
        )
        return None
    try:
        return response.json()
    except ValueError:
        log.debug("voice fetch: not json", backend=backend, url=str(url))
        return None


class IncompleteVoiceListing(Exception):
    """A voice listing answered, but not every page of it could be read."""


async def _read_voice_listing(
    http: httpx.AsyncClient, url: str, headers: dict, backend: str
) -> list[Voice] | None:
    """Every voice of the listing at *url*, following the pages of a paged
    listing with ``page_number`` (Fish Audio's). None when *url* gives no voice
    listing; IncompleteVoiceListing when a later page cannot be read."""
    voices: dict[str, Voice] = {}
    entries_read = 0
    page_url = httpx.URL(url)
    for page_number in range(1, MAX_VOICE_LISTING_PAGES + 1):
        payload = await _get_listing_page(http, page_url, headers, backend)
        page_voices = _parse_voices_payload(payload, backend)
        if page_voices is None:
            if page_number == 1:
                return None
            raise IncompleteVoiceListing(f"page {page_number} could not be read")
        new_voices = [voice for voice in page_voices if voice.id not in voices]
        if page_number > 1 and not new_voices:
            # a server that ignores page_number sends the first page again
            raise IncompleteVoiceListing(f"page {page_number} brought no new voices")
        voices.update((voice.id, voice) for voice in new_voices)
        entries_read += len(_voice_entries(payload))
        if not _has_more_pages(payload, entries_read):
            return list(voices.values())
        page_url = page_url.copy_set_param("page_number", page_number + 1)
    raise IncompleteVoiceListing(
        f"the listing has more than {MAX_VOICE_LISTING_PAGES} pages"
    )


def _has_more_pages(payload, entries_read: int) -> bool:
    """Whether a paged listing holds entries beyond the *entries_read* so far:
    its ``has_more`` when it gives one, else a ``total`` above the count."""
    if not isinstance(payload, dict):
        return False
    has_more = payload.get("has_more")
    if isinstance(has_more, bool):
        return has_more
    total = payload.get("total")
    return isinstance(total, int) and total > entries_read


def _voice_entries(payload) -> list | None:
    """The entries of a voice listing: a flat list, or the list under
    ``voices``, ``data``, ``results`` or ``items``. None for other payloads."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("voices", "data", "results", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return None


def _parse_voices_payload(payload, backend: str) -> list[Voice] | None:
    """Extract Voice objects from a tolerant set of response shapes.

    Accepts:
    - ``{"voices": [...]}``, ``{"data": [...]}``, ``{"results": [...]}`` and
      ``{"items": [...]}`` containers
    - flat ``[...]`` arrays
    - elements that are strings, or dicts with ``id``/``voice_id``/``_id``/
      ``name``/``voice`` and optional ``label``/``display_name``/``title``

    Returns an empty list for a listing without entries, and None when
    *payload* is no voice listing or none of its entries is a voice: entries
    of an unknown shape do not show that the server has no voices.
    """
    entries = _voice_entries(payload)
    if entries is None:
        return None

    voices: list[Voice] = []
    for entry in entries:
        if isinstance(entry, str):
            provider_id = entry.strip()
            label = provider_id
        elif isinstance(entry, dict):
            provider_id = (
                entry.get("id")
                or entry.get("voice_id")
                or entry.get("_id")
                or entry.get("name")
                or entry.get("voice")
            )
            label = (
                entry.get("label")
                or entry.get("display_name")
                or entry.get("title")
                or entry.get("name")
                or provider_id
            )
        else:
            continue
        if not provider_id:
            continue
        try:
            voices.append(
                Voice(
                    label=str(label),
                    provider=backend,
                    provider_id=str(provider_id),
                )
            )
        except Exception as exc:
            log.debug(
                "skipping invalid voice payload entry",
                backend=backend,
                entry=entry,
                error=str(exc),
            )
    if entries and not voices:
        return None
    return voices
