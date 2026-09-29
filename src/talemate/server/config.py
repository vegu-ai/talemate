import pydantic
import structlog
import os
import shutil
import talemate.instance as instance

from typing import get_args

from talemate import VERSION
from talemate.agents import observed_actions
from talemate.changelog import delete_scene_revisions, scene_ref_from_path
from talemate.client.model_prompts import model_prompt, PromptSpec
from talemate.client.registry import CLIENT_CLASSES
from talemate.client.system_prompts import RENDER_CACHE as SYSTEM_PROMPTS_CACHE
from talemate.client.base import (
    ClientBase,
    DEFAULT_REASONING_PATTERN,
    locked_model_template,
)
from talemate.config import Config as AppConfigData
from talemate.config.schema import (
    AgentActionOverride,
    DecisionModelConfig,
    GamePlayerCharacter,
    resolve_config_cls,
)
from talemate.config import get_config, Config, mark_apply_pending, update_config
from talemate.config.state import ApplySectionKey, PENDING_APPLY
from talemate.decisions.slot import configure_decision_service
from talemate.emit import emit
from talemate.files import scenes_directory, RESERVED_SCENES_DIRS
from talemate.instance import (
    configure_agents,
    emit_clients_status,
    ensure_agent_llm_client,
    get_client,
    instantiate_clients,
    purge_clients,
)
from talemate.scene_tools import SCENE_TOOL_ACTIONS
from talemate.world_state.templates.theme import resolve_theme

from .websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.config")


class ApplySection:
    """One config section's share of the ``config/save`` apply pipeline.

    `apply` brings the section's slice of the config into the running
    instance, `finalize` is the tail of that work another section's apply may
    already deliver (see `covers_finalize_of`).
    """

    key: ApplySectionKey
    # section keys whose finalize this section's apply delivers itself - a
    # section listed here needs no standalone finalize when this one follows it
    covers_finalize_of: tuple[ApplySectionKey, ...] = ()

    def changed(self, config_before: dict, config_after: dict) -> bool:
        return config_before[self.key] != config_after[self.key]

    async def apply(self):
        raise NotImplementedError()

    async def finalize(self):
        pass


class ClientsApplySection(ApplySection):
    key = "clients"

    async def apply(self):
        await instantiate_clients()
        await purge_clients()
        await emit_clients_status(wait_for_status=True)

    async def finalize(self):
        # repoint the agents at the (re)instantiated clients
        await ensure_agent_llm_client()


class AgentsApplySection(ApplySection):
    key = "agents"
    # configure_agents ends with ensure_agent_llm_client itself
    covers_finalize_of = ("clients",)

    async def apply(self):
        await configure_agents()


class DecisionModelApplySection(ApplySection):
    key = "decision_model"

    def changed(self, config_before: dict, config_after: dict) -> bool:
        # OpenRouter uses the shared client key outside the slot's own section.
        return (
            super().changed(config_before, config_after)
            or config_before["openrouter"] != config_after["openrouter"]
        )

    async def apply(self):
        configure_decision_service()


class ApplyOutcome(pydantic.BaseModel):
    """What one pipeline run tried, what got through, and what stopped it."""

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    applying: set[ApplySectionKey]
    applied: set[ApplySectionKey]
    error: Exception | None = None

    @property
    def unapplied(self) -> set[ApplySectionKey]:
        return self.applying - self.applied


class ConfigApplyPipeline:
    """The sections a saved config is applied through, in order."""

    def __init__(self):
        self.sections: tuple[ApplySection, ...] = (
            ClientsApplySection(),
            AgentsApplySection(),
            DecisionModelApplySection(),
        )

        # keys are unique and in-Literal, and a cover reaches backward only: a
        # section can only deliver the finalize of one that already ran, so a
        # forward, self-referencing or misspelled entry is a declaration bug -
        # and one that would otherwise no-op (or surface as a validation error
        # from inside run()) at save time. Raised from the module-level
        # singleton, so it fails at import rather than on somebody's save.
        ran: set[ApplySectionKey] = set()
        for section in self.sections:
            if section.key not in get_args(ApplySectionKey):
                raise ValueError(
                    f"{type(section).__name__}.key is '{section.key}', "
                    f"which is not an ApplySectionKey"
                )
            if section.key in ran:
                raise ValueError(
                    f"{type(section).__name__}.key is '{section.key}', "
                    f"which another section already claims"
                )
            for covered in section.covers_finalize_of:
                if covered not in ran:
                    raise ValueError(
                        f"{type(section).__name__}.covers_finalize_of names "
                        f"'{covered}', which is not a section applied before it"
                    )
            ran.add(section.key)

    @property
    def pending(self) -> set[ApplySectionKey]:
        return PENDING_APPLY

    async def run(self, config_before: dict, config_after: dict) -> ApplyOutcome:
        applying = [
            section
            for section in self.sections
            if section.changed(config_before, config_after)
            or section.key in self.pending
        ]
        applying_keys = {section.key for section in applying}

        if self.pending:
            log.warning(
                "config save: re-applying sections left unapplied by an earlier save",
                sections=sorted(self.pending),
            )

        # sections that made it all the way through their apply - only what is
        # missing from here is stale if a later step raises. Recording the whole
        # save instead would put the expensive half of the pipeline (tear down,
        # re-instantiate, block on wait_for_status) on every later save because
        # the agent half failed.
        applied: set[ApplySectionKey] = set()

        try:
            for index, section in enumerate(applying):
                await section.apply()
                covered = any(
                    section.key in later.covers_finalize_of
                    for later in applying[index + 1 :]
                )
                if not covered:
                    await section.finalize()
                applied.add(section.key)
        except Exception as exc:
            self.pending.difference_update(applied)
            mark_apply_pending(*(applying_keys - applied))
            return ApplyOutcome(applying=applying_keys, applied=applied, error=exc)

        self.pending.difference_update(applied)
        return ApplyOutcome(applying=applying_keys, applied=applied)


# Process state rather than per-connection state: plugins are built per
# websocket connection, but the stale runtime outlives the connection the
# failed save came in on (a frontend reload does not re-apply anything).
APPLY_PIPELINE = ConfigApplyPipeline()


class ConfigPayload(pydantic.BaseModel):
    config: AppConfigData
    # echoed back with the completion so a sender can tell its own save apart
    # from one made elsewhere (the settings view and the clients / agents
    # drawer both save through this action)
    request_id: str | None = None


class DefaultCharacterPayload(pydantic.BaseModel):
    name: str
    gender: str
    description: str
    color: str = "#3362bb"


class SetLLMTemplatePayload(pydantic.BaseModel):
    template_file: str
    model: str
    client_name: str | None = None


class DetermineLLMTemplatePayload(pydantic.BaseModel):
    model: str
    client_name: str | None = None


class SaveLLMTemplatePayload(pydantic.BaseModel):
    name: str
    content: str


class DeleteLLMTemplatePayload(pydantic.BaseModel):
    name: str


class ToggleClientPayload(pydantic.BaseModel):
    name: str
    state: bool


class DeleteScenePayload(pydantic.BaseModel):
    path: str


class DeleteSceneProjectPayload(pydantic.BaseModel):
    path: str


class TorchCudaDeviceInfo(pydantic.BaseModel):
    index: int
    name: str | None = None
    total_vram_bytes: int | None = None
    free_vram_bytes: int | None = None


class TorchCudaInfo(pydantic.BaseModel):
    available: bool = False
    device_count: int = 0
    devices: list[TorchCudaDeviceInfo] = []
    torch_version: str | None = None
    torch_cuda_version: str | None = None
    cuda_built: bool | None = None
    error: str | None = None


class SystemCapabilitiesPayload(pydantic.BaseModel):
    torch_cuda: TorchCudaInfo = TorchCudaInfo()


class SetAgentActionOverridePayload(pydantic.BaseModel):
    key: str
    disable_reasoning: bool = False


class ClearAgentActionOverridePayload(pydantic.BaseModel):
    key: str


def app_config_message(config: Config) -> dict:
    """The `app_config` push, built the same way `config.changed` builds it.

    The frontend repaints from the resolved theme this carries, so a payload
    without it reads as "no theme" and drops the app back to the defaults.

    Runtime apply state stays outside the saved configuration.
    """

    data = config.model_dump()
    data.update(system_prompt_defaults=SYSTEM_PROMPTS_CACHE)
    data.update(theme=resolve_theme(config))
    data.update(
        decision_model_defaults=DecisionModelConfig().model_dump(include={"model"})
    )

    return {
        "type": "app_config",
        "data": data,
        "version": VERSION,
        "agent_apply_pending": any(
            agent.config_apply_failed for agent in instance.AGENTS.values()
        ),
    }


def client_model_defaults(client_type: str) -> dict:
    """Field defaults of the config model a client of `client_type` saves to.

    Instantiated and dumped rather than read off `model_fields` so that
    default_factory fields and nested models serialize exactly as they would
    in a saved config.
    """
    config_cls = resolve_config_cls(CLIENT_CLASSES[client_type])
    return config_cls(type=client_type, name="").model_dump(exclude={"type", "name"})


class ConfigPlugin(Plugin):
    router = "config"

    async def handle_save(self, data):
        app_config_data = ConfigPayload(**data)

        config_before = get_config().model_dump()
        # signal=False: config.changed receivers broadcast app_config, and the
        # frontend must only adopt a config that is already applied - the
        # broadcast is fired below, after the apply pipeline
        await update_config(app_config_data.config.model_dump(), signal=False)
        config_after = get_config().model_dump()

        outcome = await APPLY_PIPELINE.run(config_before, config_after)

        if outcome.error is not None:
            # the config is already stored and will be committed to disk, so
            # the frontend gets it either way - what failed is the apply, and
            # saying "save failed" would send the user looking for a config
            # that is not coming back
            log.error(
                "config save: apply failed",
                error=outcome.error,
                clients_changed="clients" in outcome.applying,
                agents_changed="agents" in outcome.applying,
                unapplied=sorted(outcome.unapplied),
            )
            await get_config().set_dirty()
            # `stage` lets the sender tell an apply failure (payload accepted
            # and stored) from a refused payload (nothing stored) - the two
            # call for opposite handling of whatever was stacked on the save
            await self.signal_operation_failed(
                f"Configuration was saved, but applying it failed: {outcome.error}",
                request_id=app_config_data.request_id,
                failed_action="save",
                extra={"stage": "apply"},
            )
            return

        # broadcasts app_config to every connected frontend (see
        # WebsocketHandler.on_config_changed)
        failures = await get_config().set_dirty()

        if failures:
            message = (
                f"Configuration was saved, but applying it failed: {failures[0][1]}"
            )
            if len(failures) > 1:
                message += f" (+{len(failures) - 1} more, see backend log)"
            await self.signal_operation_failed(
                message,
                request_id=app_config_data.request_id,
                failed_action="save",
                extra={"stage": "apply"},
            )
            return

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "save_complete",
                "request_id": app_config_data.request_id,
            }
        )

    async def handle_save_default_character(self, data):
        log.info("Saving default character", data=data["data"])

        payload = DefaultCharacterPayload(**data["data"])

        config: Config = get_config()
        config.game.default_player_character = GamePlayerCharacter(
            **payload.model_dump()
        )

        log.info(
            "Saving default character",
            character=config.game.default_player_character,
        )

        await config.set_dirty()

        self.websocket_handler.queue_put(app_config_message(config))
        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "save_default_character_complete",
            }
        )

    async def handle_request_std_llm_templates(self, data):
        log.info("Requesting standard LLM templates")

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "std_llm_templates",
                "data": {
                    "templates": model_prompt.std_templates,
                },
            }
        )

    async def handle_list_llm_templates(self, data):
        """List all std/ built-in and std/user/ templates with content."""
        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "llm_templates_list",
                "data": {
                    "builtin": model_prompt.list_std_builtin_templates(),
                    "user": model_prompt.list_std_user_templates(),
                },
            }
        )

    async def handle_save_llm_template(self, data):
        """Save/create a user-supplied LLM prompt template in std/user/."""
        payload = SaveLLMTemplatePayload(**data["data"])

        try:
            model_prompt.save_std_user_template(payload.name, payload.content)
            log.info("Saved LLM template", name=payload.name)
            self.websocket_handler.queue_put(
                {
                    "type": "config",
                    "action": "save_llm_template_complete",
                    "data": {"success": True, "name": payload.name},
                }
            )
        except Exception as e:
            log.error("Failed to save LLM template", name=payload.name, error=str(e))
            self.websocket_handler.queue_put(
                {
                    "type": "config",
                    "action": "save_llm_template_complete",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def handle_delete_llm_template(self, data):
        """Delete a user-supplied LLM prompt template from std/user/."""
        payload = DeleteLLMTemplatePayload(**data["data"])

        deleted = model_prompt.delete_std_user_template(payload.name)
        log.info("Deleted LLM template", name=payload.name, deleted=deleted)
        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "delete_llm_template_complete",
                "data": {"success": deleted, "name": payload.name},
            }
        )

    async def handle_set_llm_template(self, data):
        payload = SetLLMTemplatePayload(**data["data"])

        model_name = payload.model
        if payload.client_name:
            model_name = locked_model_template(payload.client_name, payload.model)

        copied_to = model_prompt.create_user_override(payload.template_file, model_name)

        log.info(
            "Copied template",
            copied_to=copied_to,
            template=payload.template_file,
            model=payload.model,
            client_name=payload.client_name,
        )

        spec = PromptSpec()
        client = None
        if payload.client_name:
            try:
                client = get_client(payload.client_name)
            except KeyError:
                client = None
        reasoning_tokens = 0
        if client is not None and getattr(client, "reason_enabled", False):
            reasoning_tokens = getattr(client, "validated_reason_tokens", 0) or 0

        prompt_template_example, prompt_template_file = model_prompt(
            model_name,
            "sysmsg",
            "prompt<|BOT|>{LLM coercion}",
            reasoning_tokens=reasoning_tokens,
            spec=spec,
        )

        log.info(
            "Prompt template example",
            prompt_template_example=prompt_template_example,
            prompt_template_file=prompt_template_file,
        )

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "set_llm_template_complete",
                "request_id": data.get("request_id"),
                "data": {
                    "prompt_template_example": prompt_template_example,
                    "has_prompt_template": True if prompt_template_example else False,
                    "template_file": prompt_template_file,
                    "reason_response_pattern_default": (
                        spec.reasoning_pattern or DEFAULT_REASONING_PATTERN
                    ),
                    "reason_response_pattern_from_template": bool(
                        spec.reasoning_pattern
                    ),
                    "reason_validation_pattern_default": (
                        spec.reasoning_validation_pattern
                    ),
                    "reason_validation_pattern_from_template": bool(
                        spec.reasoning_validation_pattern
                    ),
                },
            }
        )

    async def handle_determine_llm_template(self, data):
        payload = DetermineLLMTemplatePayload(**data["data"])

        if not payload.model:
            log.info("No model provided, skipping template determination")
            return

        log.info("Determining LLM template", model=payload.model)

        template = model_prompt.query_hf_for_prompt_template_suggestion(payload.model)

        log.info("Template suggestion", template=template)

        if not template:
            emit("status", message="No template found for model", status="warning")
        else:
            await self.handle_set_llm_template(
                {
                    "request_id": data.get("request_id"),
                    "data": {
                        "template_file": template,
                        "model": payload.model,
                        "client_name": payload.client_name,
                    },
                }
            )

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "determine_llm_template_complete",
                "request_id": data.get("request_id"),
                "data": {
                    "template": template,
                },
            }
        )

    async def handle_request_client_types(self, data):
        log.info("Requesting client types")

        clients = {
            client_type: {
                **CLIENT_CLASSES[client_type].Meta().model_dump(),
                "model_defaults": client_model_defaults(client_type),
            }
            for client_type in CLIENT_CLASSES
        }

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "client_types",
                "data": clients,
            }
        )

    async def handle_request_agent_actions(self, data):
        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "agent_actions",
                "data": {"actions": observed_actions.snapshot()},
            }
        )

    async def handle_request_scene_tool_actions(self, data):
        log.info("Requesting scene tool actions")

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "scene_tool_actions",
                "data": {
                    "actions": [action.model_dump() for action in SCENE_TOOL_ACTIONS],
                },
            }
        )

    async def handle_request_system_capabilities(self, data):
        """
        Lightweight runtime capability probe used by the frontend to provide better UX hints.
        Currently includes torch CUDA availability and VRAM info.
        """
        log.info("Requesting system capabilities")

        cuda_info = TorchCudaInfo()
        try:
            import torch  # lazy import; avoids import cost unless requested

            cuda_info.torch_version = torch.__version__
            cuda_info.torch_cuda_version = torch.version.cuda
            cuda_info.cuda_built = bool(torch.backends.cuda.is_built())

            cuda_available = False
            try:
                cuda_available = bool(torch.cuda.is_available())
            except Exception as e:
                cuda_info.error = f"torch.cuda.is_available() failed: {e}"
                cuda_available = False

            cuda_info.available = cuda_available
            if cuda_available:
                cuda_info.device_count = int(torch.cuda.device_count())

                devices: list[TorchCudaDeviceInfo] = []
                for i in range(cuda_info.device_count):
                    dev = TorchCudaDeviceInfo(index=i)
                    try:
                        props = torch.cuda.get_device_properties(i)
                        dev.name = props.name
                        dev.total_vram_bytes = int(props.total_memory) or None
                    except Exception:
                        pass

                    try:
                        free_b, total_b = torch.cuda.mem_get_info(i)
                        dev.free_vram_bytes = int(free_b)
                        dev.total_vram_bytes = int(total_b)
                    except Exception:
                        pass

                    devices.append(dev)

                cuda_info.devices = devices

        except Exception as e:
            cuda_info.available = False
            cuda_info.error = f"torch probe failed: {e}"

        payload = SystemCapabilitiesPayload(torch_cuda=cuda_info)
        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "system_capabilities",
                "data": payload.model_dump(),
            }
        )

    async def handle_toggle_client(self, data):
        payload = ToggleClientPayload(**data)

        log.info("Toggling client", name=payload.name, state=payload.state)
        client: ClientBase = get_client(payload.name)

        current_state = client.enabled

        if current_state != payload.state:
            if not payload.state:
                await client.disable()
            else:
                await client.enable()

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "toggle_client_complete",
                "data": {
                    "name": payload.name,
                    "state": payload.state,
                },
            }
        )

        await emit_clients_status()

    async def handle_remove_scene_from_recents(self, data):
        payload = DeleteScenePayload(**data)

        log.info("Removing scene from recents", path=payload.path)

        config: Config = get_config()

        for recent_scene in list(config.recent_scenes.scenes):
            if recent_scene.path == payload.path:
                config.recent_scenes.scenes.remove(recent_scene)

        await config.set_dirty()

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "remove_scene_from_recents_complete",
                "data": {
                    "path": payload.path,
                },
            }
        )

        self.websocket_handler.queue_put(app_config_message(config))

    def _active_scene_realpath(self) -> str | None:
        scene = self.scene
        if scene and scene.full_path:
            return os.path.realpath(scene.full_path)
        return None

    async def handle_delete_scene(self, data):
        payload = DeleteScenePayload(**data)

        file_path = os.path.realpath(payload.path)
        scenes_root = os.path.realpath(scenes_directory())
        if not file_path.startswith(scenes_root + os.sep):
            raise ValueError(f"Not a scene file: {payload.path}")

        # the next save of the loaded scene would silently recreate the file
        # (with its changelog history gone), so refuse instead
        if self._active_scene_realpath() == file_path:
            raise ValueError(
                "Cannot delete the save file of the currently loaded scene - load a different scene first"
            )

        await self.handle_remove_scene_from_recents(data)

        log.info("Deleting scene", path=payload.path)

        # remove the file
        try:
            os.remove(payload.path)
        except FileNotFoundError:
            log.warning("File not found", path=payload.path)

        result = await delete_scene_revisions(scene_ref_from_path(payload.path))
        log.info("Deleted scene revisions", **result)

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "delete_scene_complete",
                "data": {
                    "path": payload.path,
                },
            }
        )

        config: Config = get_config()

        self.websocket_handler.queue_put(app_config_message(config))

    async def handle_delete_scene_project(self, data):
        payload = DeleteSceneProjectPayload(**data)

        project_path = os.path.realpath(payload.path)
        scenes_root = os.path.realpath(scenes_directory())
        project_name = os.path.basename(project_path)

        # only direct children of the scenes directory are scene projects
        if (
            os.path.dirname(project_path) != scenes_root
            or project_name in RESERVED_SCENES_DIRS
        ):
            raise ValueError(f"Not a scene project directory: {payload.path}")

        if not os.path.isdir(project_path):
            raise ValueError(f"Scene project not found: {payload.path}")

        prefix = project_path + os.sep

        # the next save of a loaded scene would silently recreate a skeleton
        # project with broken asset references, so refuse instead
        active_scene_path = self._active_scene_realpath()
        if active_scene_path and active_scene_path.startswith(prefix):
            raise ValueError(
                f"Cannot delete the project of the currently loaded scene: {project_name}"
            )

        log.info("Deleting scene project", path=project_path)

        config: Config = get_config()

        for recent_scene in list(config.recent_scenes.scenes):
            if os.path.realpath(recent_scene.path).startswith(prefix):
                config.recent_scenes.scenes.remove(recent_scene)

        await config.set_dirty()

        shutil.rmtree(project_path)

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "delete_scene_project_complete",
                "data": {
                    "path": payload.path,
                    "name": project_name,
                },
            }
        )

        self.websocket_handler.queue_put(app_config_message(config))

    async def handle_set_agent_action_override(self, data):
        payload = SetAgentActionOverridePayload(**data["data"])

        config: Config = get_config()
        config.agent_actions.overrides[payload.key] = AgentActionOverride(
            disable_reasoning=payload.disable_reasoning
        )

        await config.set_dirty()

    async def handle_clear_agent_action_override(self, data):
        payload = ClearAgentActionOverridePayload(**data["data"])

        config: Config = get_config()
        if config.agent_actions.overrides.pop(payload.key, None) is None:
            return

        await config.set_dirty()
