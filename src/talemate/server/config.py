import pydantic
import structlog
import os
import shutil

from talemate import VERSION
from talemate.changelog import delete_changelog_files, scene_ref_from_path
from talemate.client.model_prompts import model_prompt, PromptSpec
from talemate.client.registry import CLIENT_CLASSES
from talemate.client.base import (
    ClientBase,
    DEFAULT_REASONING_PATTERN,
    locked_model_template,
)
from talemate.config import Config as AppConfigData
from talemate.config.schema import (
    AgentActionOverride,
    GamePlayerCharacter,
)
from talemate.config import get_config, Config, update_config
from talemate.emit import emit
from talemate.files import scenes_directory, RESERVED_SCENES_DIRS
from talemate.instance import emit_clients_status, get_client

from .websocket_plugin import Plugin

log = structlog.get_logger("talemate.server.config")


class ConfigPayload(pydantic.BaseModel):
    config: AppConfigData


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


class SaveUnifiedAPIKeyPayload(pydantic.BaseModel):
    config_path: str
    api_key: str | None


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


class ConfigPlugin(Plugin):
    router = "config"

    async def handle_save(self, data):
        app_config_data = ConfigPayload(**data)
        await update_config(app_config_data.config.model_dump())
        self.websocket_handler.queue_put(
            {
                "type": "app_config",
                "data": get_config().model_dump(),
                "version": VERSION,
            }
        )
        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "save_complete",
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

        self.websocket_handler.queue_put(
            {"type": "app_config", "data": config.model_dump(), "version": VERSION}
        )
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
                    "data": {
                        "template_file": template,
                        "model": payload.model,
                        "client_name": payload.client_name,
                    }
                }
            )

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "determine_llm_template_complete",
                "data": {
                    "template": template,
                },
            }
        )

    async def handle_request_client_types(self, data):
        log.info("Requesting client types")

        clients = {
            client_type: CLIENT_CLASSES[client_type].Meta().model_dump()
            for client_type in CLIENT_CLASSES
        }

        self.websocket_handler.queue_put(
            {
                "type": "config",
                "action": "client_types",
                "data": clients,
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

        self.websocket_handler.queue_put(
            {"type": "app_config", "data": config.model_dump(), "version": VERSION}
        )

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

        # remove associated changelog files (base, latest, and segmented changelog files)
        try:
            scene_ref = scene_ref_from_path(payload.path)
            result = delete_changelog_files(scene_ref)
            log.info(
                "Deleted scene changelog artifacts",
                deleted_files=len(result.get("deleted", [])),
                dir_removed=result.get("dir_removed"),
            )
        except Exception as e:
            log.warning(
                "Failed to delete associated changelog files",
                scene_path=payload.path,
                error=e,
            )

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

        self.websocket_handler.queue_put(
            {"type": "app_config", "data": config.model_dump(), "version": VERSION}
        )

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

        self.websocket_handler.queue_put(
            {"type": "app_config", "data": config.model_dump(), "version": VERSION}
        )

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

    async def handle_save_unified_api_key(self, data):
        """Save a unified API key to app config."""
        payload = SaveUnifiedAPIKeyPayload(**data["data"])

        log.info("Saving unified API key", config_path=payload.config_path)

        config: Config = get_config()

        # Parse the config path (e.g., "anthropic.api_key")
        path_parts = payload.config_path.split(".")
        if len(path_parts) != 2:
            log.error("Invalid config path", config_path=payload.config_path)
            return

        section_name, key_name = path_parts

        # Get the section (e.g., config.anthropic)
        section = getattr(config, section_name, None)
        if section is None:
            log.error("Config section not found", section=section_name)
            return

        # Set the API key
        setattr(section, key_name, payload.api_key)

        await config.set_dirty()

        # Send updated config back
        self.websocket_handler.queue_put(
            {"type": "app_config", "data": config.model_dump(), "version": VERSION}
        )
