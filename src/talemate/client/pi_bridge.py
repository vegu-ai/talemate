import asyncio
import json
import os
import re
import shutil
import tempfile
import time
from typing import Literal

import pydantic
import structlog

from talemate.client.base import (
    ClientBase,
    CommonDefaults,
    ExtraField,
    FieldGroup,
    ReasoningDisplay,
)
from talemate.client.registry import register
from talemate.client.remote import (
    ConcurrentInference,
    ConcurrentInferenceMixin,
    concurrent_inference_extra_fields,
)
from talemate.config.schema import Client as BaseClientConfig
from talemate.config import get_config
from talemate.emit import emit
from talemate.emit.signals import handlers
import talemate.emit.async_signals as async_signals

__all__ = [
    "PiBridgeClient",
]

log = structlog.get_logger("talemate.client.pi_bridge")

PI_BINARY = "pi"

# pi event lines carry entire messages (message_end includes the full
# accumulated thinking block, agent_end the whole conversation), which
# easily exceeds asyncio's 64KB default StreamReader line limit and would
# fail readline() with a LimitOverrunError mid-generation.
PI_STDOUT_LIMIT = 2**26

DEFAULT_PROVIDER = "openrouter"

THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"]

# provider -> [model ids], populated from `pi --list-models` (which includes
# custom providers/models defined in pi's models.json)
AVAILABLE_MODELS: dict[str, list[str]] = {}

MODELS_FETCHED = False

_MODELS_LOCK = asyncio.Lock()

# Failed fetches stay unlatched so the retry triggers (client status
# refreshes) can recover; the cooldown keeps them from re-spawning pi
# while it keeps failing.
FETCH_RETRY_COOLDOWN = 30.0
_models_last_attempt: float | None = None


def resolve_pi_binary() -> str | None:
    """Absolute path to the pi executable, or None when pi is not installed.

    Spawns must use the resolved path: on Windows shutil.which finds npm's
    pi.cmd shim via PATHEXT, but CreateProcess only looks for pi.exe when
    given the bare name — spawning "pi" fails with WinError 2 even though
    the availability check passed.
    """
    return shutil.which(PI_BINARY)


def pi_subprocess_env() -> dict:
    """Environment for pi subprocesses: talemate-managed values layered over
    the process environment. The configured openrouter API key doubles as
    OPENROUTER_API_KEY (so a key set up in talemate works without container
    env setup), and the config env variable store is applied last so explicit
    entries always win. Used for generations and catalog fetches alike, so
    models.json providers gated on $VAR references resolve consistently.
    """
    config = get_config()
    env = os.environ.copy()
    if config.openrouter.api_key:
        env["OPENROUTER_API_KEY"] = config.openrouter.api_key
    env.update(config.env)
    return env


def models_for_provider(provider: str) -> list[str]:
    return AVAILABLE_MODELS.get(provider, [])


def available_providers() -> list[str]:
    return sorted(AVAILABLE_MODELS.keys())


async def fetch_available_models():
    """Fetch the model catalog from pi via `pi --list-models`.

    Runs offline (no catalog refresh) so it stays fast and deterministic;
    custom providers/models from pi's models.json are included.
    """
    global AVAILABLE_MODELS, MODELS_FETCHED, _models_last_attempt

    if MODELS_FETCHED:
        return AVAILABLE_MODELS

    async with _MODELS_LOCK:
        if MODELS_FETCHED:
            return AVAILABLE_MODELS

        now = time.monotonic()
        if (
            _models_last_attempt is not None
            and now - _models_last_attempt < FETCH_RETRY_COOLDOWN
        ):
            return AVAILABLE_MODELS
        _models_last_attempt = now

        pi_path = resolve_pi_binary()
        if not pi_path:
            # pi is optional — stay quiet until the user actually sets up a
            # pi_bridge client, whose status reports the missing binary
            log.debug("pi binary not found, skipping model fetch")
            return AVAILABLE_MODELS

        try:
            proc = await asyncio.create_subprocess_exec(
                pi_path,
                "--list-models",
                "--offline",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=pi_subprocess_env(),
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                log.error(
                    "pi --list-models failed",
                    returncode=proc.returncode,
                    stderr=stderr.decode(errors="replace")[:500],
                )
                return AVAILABLE_MODELS

            AVAILABLE_MODELS = parse_model_list(stdout.decode(errors="replace"))
            MODELS_FETCHED = True
            log.debug(
                "fetched models from pi",
                providers=len(AVAILABLE_MODELS),
                models=sum(len(models) for models in AVAILABLE_MODELS.values()),
            )
        except FileNotFoundError as e:
            # WinError 2 / ENOENT don't say which file — name the executable
            log.error(
                "error fetching models from pi - could not execute the pi binary",
                path=pi_path,
                error=str(e),
            )
        except Exception as e:
            log.error("error fetching models from pi", path=pi_path, error=str(e))

        return AVAILABLE_MODELS


def parse_model_list(output: str) -> dict[str, list[str]]:
    """Parse `pi --list-models` table output into {provider: [model ids]}.

    The first line is a header; data rows are whitespace-separated with
    provider and model id in the first two columns.
    """
    models: dict[str, list[str]] = {}
    lines = output.splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        provider, model_id = parts[0], parts[1]
        models.setdefault(provider, []).append(model_id)
    return {provider: sorted(ids) for provider, ids in models.items()}


def on_talemate_started(event):
    """Spawn a background task to fetch the pi model catalog."""
    loop = asyncio.get_event_loop()
    loop.create_task(fetch_available_models())


async def on_config_saved(config):
    """Refresh the catalog so pi-side changes (a new models.json provider,
    newly configured credentials) show up after saving settings, without
    restarting the server."""
    global MODELS_FETCHED, _models_last_attempt
    MODELS_FETCHED = False
    _models_last_attempt = None
    await fetch_available_models()


handlers["talemate_started"].connect(on_talemate_started)
async_signals.get("config.saved").connect(on_config_saved)


REASONING_FIELD_GROUP = FieldGroup(
    name="reasoning",
    label="Reasoning",
    description="",
    icon="mdi-brain",
)


class Defaults(CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = ""
    provider: str = DEFAULT_PROVIDER
    effort_level: str = "medium"


class ClientConfig(ConcurrentInference, BaseClientConfig):
    provider: str = DEFAULT_PROVIDER
    effort_level: Literal["minimal", "low", "medium", "high", "xhigh", "max"] = "medium"


class PiBridgeError(Exception):
    """Raised when the pi subprocess fails or reports a generation error.

    Provider API errors reported by pi are prefixed with the HTTP status
    (e.g. "400: ..."); the parsed code feeds the standard generation error
    dialog. Most pi failures carry no status code at all (missing key,
    process exit, retry exhaustion), so the message itself is exposed as
    `user_message` for the dialog — the status-code fallback text would
    misreport these as empty responses.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.user_message = message


def parse_error_status_code(error_message: str) -> int | None:
    status_match = re.match(r"(\d{3}):", error_message)
    return int(status_match.group(1)) if status_match else None


@register()
class PiBridgeClient(ConcurrentInferenceMixin, ClientBase):
    """
    Client that drives generations through the `pi` coding harness via its
    RPC mode. pi owns provider auth, model resolution and sampling
    parameters; talemate acts as a pure prompt/response bridge.
    """

    client_type = "pi_bridge"
    conversation_retries = 0
    decensor_enabled = False
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "Pi Bridge"
        title: str = "Pi Bridge"
        manual_model: bool = True
        manual_model_choices: list[str] = pydantic.Field(
            default_factory=lambda: models_for_provider(DEFAULT_PROVIDER)
        )
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

        @staticmethod
        def _build_extra_fields():
            """Build extra_fields dynamically so provider choices reflect the
            current pi model catalog."""
            fields = {
                "provider": ExtraField(
                    name="provider",
                    type="autocomplete" if available_providers() else "text",
                    label="Provider",
                    choices=available_providers() or None,
                    description=(
                        "The pi provider to route generations through. pi handles "
                        "authentication (environment API keys, pi's auth.json, "
                        "subscription auth) and model resolution, including custom "
                        "providers defined in pi's models.json. Variables from "
                        "Settings → Application → Environment Variables are passed "
                        "to pi, so models.json can reference them as $NAME."
                    ),
                    required=False,
                ),
                "effort_level": ExtraField(
                    name="effort_level",
                    type="text",
                    label="Thinking Level",
                    choices=THINKING_LEVELS,
                    description=(
                        "Thinking level passed to pi (--thinking) when reasoning is "
                        "enabled. Availability of the higher levels depends on the "
                        "selected model."
                    ),
                    group=REASONING_FIELD_GROUP,
                    required=False,
                ),
            }
            fields.update(concurrent_inference_extra_fields())
            return fields

        extra_fields: dict[str, ExtraField] = pydantic.Field(
            default_factory=_build_extra_fields
        )

    @property
    def provider(self) -> str:
        return self.client_config.provider or DEFAULT_PROVIDER

    @property
    def effort_level(self) -> str:
        return self.client_config.effort_level

    @property
    def can_be_coerced(self) -> bool:
        # pi's RPC prompt is a single user message; coercion happens
        # indirectly via instructions appended by the base class.
        return False

    @property
    def requires_reasoning_pattern(self) -> bool:
        # pi returns thinking blocks separately from response text
        return False

    @property
    def supported_parameters(self):
        # Sampling parameters are owned by pi / the provider; talemate
        # deliberately forwards none of them.
        return []

    @property
    def pi_available(self) -> bool:
        return resolve_pi_binary() is not None

    @property
    def reasoning_display(self) -> ReasoningDisplay | None:
        if not self.reason_enabled_configured:
            return None
        return ReasoningDisplay(
            indicator_value=self.effort_level,
            indicator_tooltip="Thinking level",
            show_token_slider=False,
            show_effort_selector=True,
            effort_level=self.effort_level,
            effort_choices=THINKING_LEVELS,
        )

    def emit_status(self, processing: bool = None):
        error_message = None
        if processing is not None:
            self.processing = processing

        if not self.pi_available:
            status = "error"
            error_message = "pi binary not found - install the pi coding agent"
        elif not self.model_name:
            status = "error"
            error_message = "No model loaded"
        else:
            status = "busy" if self.processing else "idle"

        self.current_status = status

        data = {
            "error_action": None,
            "meta": self.Meta().model_dump(),
            "enabled": self.enabled,
            "error_message": error_message,
        }
        data.update(self._common_status_data())
        data["manual_model_choices"] = models_for_provider(self.provider)

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=self.model_name,
            status=status if self.enabled else "disabled",
            data=data,
        )

    async def status(self):
        if not MODELS_FETCHED:
            await fetch_available_models()
        self.emit_status()

    def _build_command(
        self, kind: str, pi_path: str, system_prompt_path: str
    ) -> list[str]:
        """Assemble the pi RPC invocation for a single generation.

        The system prompt travels as a file (pi reads --system-prompt from a
        path when one exists) rather than inline: on Windows the resolved pi
        is npm's pi.cmd, which CreateProcess runs through cmd.exe, and cmd
        re-parses the argv — an embedded newline would end the command and
        the rest of the prompt would be interpreted as one.
        """
        thinking = self.effort_level if self.reason_enabled else "off"
        return [
            pi_path,
            "--mode",
            "rpc",
            "--no-session",
            "--provider",
            self.provider,
            "--model",
            self.model_name,
            "--thinking",
            thinking,
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-context-files",
            "--no-prompt-templates",
            "--system-prompt",
            system_prompt_path,
        ]

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text by spawning a pi RPC subprocess for this request.
        """

        pi_path = resolve_pi_binary()
        if not pi_path:
            raise PiBridgeError("pi binary not found")

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            model=self.model_name,
            provider=self.provider,
        )

        with tempfile.TemporaryDirectory(prefix="talemate-pi-") as prompt_dir:
            system_prompt_path = os.path.join(prompt_dir, "system-prompt.txt")
            with open(system_prompt_path, "w", encoding="utf-8") as f:
                f.write(self.get_system_message(kind))

            argv = self._build_command(kind, pi_path, system_prompt_path)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=pi_subprocess_env(),
                    limit=PI_STDOUT_LIMIT,
                )
            except FileNotFoundError as e:
                raise PiBridgeError(
                    f"could not execute the pi binary: {pi_path}"
                ) from e

            # drain stderr continuously so a chatty pi process can never fill
            # the OS pipe buffer and deadlock against our stdout readline loop;
            # the collected output feeds the unexpected-exit error message.
            stderr_task = asyncio.create_task(proc.stderr.read())

            try:
                rpc_command = {"id": "generate", "type": "prompt", "message": prompt}
                proc.stdin.write((json.dumps(rpc_command) + "\n").encode("utf-8"))
                await proc.stdin.drain()

                response_text, reasoning_text = await self._consume_events(
                    proc, stderr_task
                )

                self._reasoning_response = reasoning_text or None

                self.log.debug(
                    "generated response",
                    response=response_text[:128] + " ..."
                    if len(response_text) > 128
                    else response_text,
                    reasoning_length=len(reasoning_text),
                )

                return response_text
            finally:
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                await proc.wait()
                # the kill/exit above closes the pipe, so the drain finishes
                await stderr_task

    async def _consume_events(self, proc, stderr_task) -> tuple[str, str]:
        """Read the pi RPC event stream until the agent settles.

        Returns the accumulated assistant text and thinking content.
        """
        response_text = ""
        reasoning_text = ""

        while True:
            line = await proc.stdout.readline()
            if not line:
                stderr = (await stderr_task).decode(errors="replace")
                raise PiBridgeError(
                    f"pi process exited unexpectedly: {stderr[:500].strip() or 'no error output'}"
                )

            line = line.decode("utf-8").strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # pi may print non-protocol noise on stdout during startup
                continue

            event_type = event.get("type")

            if event_type == "response":
                if not event.get("success", True):
                    raise PiBridgeError(
                        f"pi rejected the prompt: {event.get('error', 'unknown error')}"
                    )
                continue

            if event_type == "message_update":
                delta = event.get("assistantMessageEvent", {})
                if delta.get("type") in ("text_delta", "thinking_delta"):
                    self.update_request_tokens(
                        self.count_tokens(delta.get("delta", ""))
                    )
                continue

            if event_type == "message_end":
                message = event.get("message", {})
                if message.get("role") != "assistant":
                    continue

                if message.get("stopReason") in ("error", "aborted"):
                    error_message = message.get("errorMessage") or "generation failed"
                    raise PiBridgeError(
                        f"pi generation error: {error_message}",
                        status_code=parse_error_status_code(error_message),
                    )

                for block in message.get("content", []):
                    if block.get("type") == "text":
                        response_text += block.get("text", "")
                    elif block.get("type") == "thinking":
                        reasoning_text += block.get("thinking", "")

                usage = message.get("usage", {})
                if usage.get("input"):
                    self._returned_prompt_tokens = usage["input"]
                if usage.get("output"):
                    self._returned_response_tokens = usage["output"]
                continue

            if event_type == "auto_retry_end" and not event.get("success", True):
                raise PiBridgeError(
                    f"pi generation failed: {event.get('finalError', 'max retries exceeded')}"
                )

            if event_type == "agent_settled":
                return response_text, reasoning_text
