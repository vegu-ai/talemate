"""OpenAI-compatible TTS endpoints — multi-backend.

This mixin exposes a single management tab in the TTS agent settings ("OpenAI
Compatible") that lets the user register any number of named backends. Each
registered backend renders as its own sub-tab below the management tab and
carries its own URL/key/model/voice list.

The mixin's per-backend helpers follow the dynamic-registry naming convention
(``_<registry_key>_<name>(slug, ...)``) so the TTSAgent's ``api_attr`` /
``api_method`` resolvers can reach them directly through the framework.
"""

from typing import Union
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from openai import AsyncOpenAI

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
        # The static management tab. No generation config — it only carries
        # the dynamic-children registry blob.
        actions[REGISTRY_KEY] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-server-outline",
            label="OpenAI Compatible",
            description=(
                "Manage OpenAI-compatible TTS backends. Each backend you add "
                "appears as its own tab below."
            ),
            dynamic_registry_component="TTSOpenAICompatibleBackends",
            config={
                DYNAMIC_CHILDREN_FIELD: AgentActionConfig(
                    type="blob",
                    value="[]",
                    label="Registered backends",
                    description=(
                        "Internal — managed by the Add Backend UI on this tab."
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
                    # Persist on blur so the user can immediately click
                    # Refresh voices without closing the agent settings.
                    save_on_change=True,
                    scene_overridable=False,
                ),
                "api_key": AgentActionConfig(
                    type="password",
                    value="",
                    label="API Key",
                    description="API key for the server (leave empty if not required)",
                    save_on_change=True,
                    scene_overridable=False,
                ),
                "model": AgentActionConfig(
                    type="text",
                    value="tts-1",
                    label="Model",
                    description="Model identifier to send in requests",
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
                    save_on_change=True,
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
        response = await client.audio.speech.create(
            model=model,
            voice=chunk.voice.provider_id,
            input=chunk.cleaned_text,
        )
        return response.content

    # ------------------------------------------------------------------
    # Voice auto-fetch
    # ------------------------------------------------------------------

    async def _openai_compatible_fetch_voices(self, backend: str) -> list[Voice]:
        """Fetch the list of voices the configured backend exposes.

        Tries the user-supplied ``voices_endpoint`` first; falls back to a
        small set of well-known paths. Tolerates the most common response
        shapes. Returns an empty list on any failure.
        """
        api_url = self._openai_compatible_api_url(backend)
        if not api_url:
            return []

        api_key = self._openai_compatible_api_key(backend)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        custom = self._openai_compatible_voices_endpoint(backend)
        candidates = [custom] if custom else list(DEFAULT_VOICE_LISTING_PATHS)

        attempted: list[str] = []
        async with httpx.AsyncClient(timeout=10.0) as http:
            for candidate in candidates:
                url = _resolve_voices_url(api_url, candidate)
                attempted.append(url)
                try:
                    response = await http.get(url, headers=headers)
                except httpx.HTTPError as exc:
                    log.debug(
                        "voice fetch failed", backend=backend, url=url, error=str(exc)
                    )
                    continue
                if response.status_code != 200:
                    log.debug(
                        "voice fetch non-200",
                        backend=backend,
                        url=url,
                        status=response.status_code,
                    )
                    continue
                try:
                    payload = response.json()
                except ValueError:
                    log.debug("voice fetch: not json", backend=backend, url=url)
                    continue
                voices = _parse_voices_payload(payload, backend)
                if voices:
                    log.info(
                        "voice fetch succeeded",
                        backend=backend,
                        url=url,
                        count=len(voices),
                    )
                    return voices
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
        return []


def _parse_voices_payload(payload, backend: str) -> list[Voice]:
    """Extract Voice objects from a tolerant set of response shapes.

    Accepts:
    - ``{"voices": [...], "data": [...]}`` containers
    - flat ``[...]`` arrays
    - elements that are strings, or dicts with ``id``/``name``/``voice_id``
      and optional ``label``/``display_name``
    """
    items = None
    if isinstance(payload, dict):
        for key in ("voices", "data", "results"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
    elif isinstance(payload, list):
        items = payload
    if items is None:
        return []

    voices: list[Voice] = []
    for entry in items:
        if isinstance(entry, str):
            provider_id = entry.strip()
            label = provider_id
        elif isinstance(entry, dict):
            provider_id = (
                entry.get("id")
                or entry.get("voice_id")
                or entry.get("name")
                or entry.get("voice")
            )
            label = (
                entry.get("label")
                or entry.get("display_name")
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
    return voices
