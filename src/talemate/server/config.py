import pydantic
import structlog
import os

from talemate import VERSION
from talemate.changelog import list_revision_entries
from talemate.client.model_prompts import model_prompt
from talemate.client.registry import CLIENT_CLASSES
from talemate.client.base import ClientBase
from talemate.config import Config as AppConfigData
from talemate.config import get_config, Config, update_config
from talemate.emit import emit
from talemate.instance import emit_clients_status, get_client

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


class DetermineLLMTemplatePayload(pydantic.BaseModel):
    model: str


class ToggleClientPayload(pydantic.BaseModel):
    name: str
    state: bool


class DeleteScenePayload(pydantic.BaseModel):
    path: str


class GetBackupFilesPayload(pydantic.BaseModel):
    scene_path: str


class ConfigPlugin:
    router = "config"

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler

    async def handle(self, data: dict):
        log.info("Config action", action=data.get("action"))

        fn = getattr(self, f"handle_{data.get('action')}", None)

        if fn is None:
            return

        await fn(data)

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
        config.game.default_player_character = payload.model_dump()

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

    async def handle_set_llm_template(self, data):
        payload = SetLLMTemplatePayload(**data["data"])

        copied_to = model_prompt.create_user_override(
            payload.template_file, payload.model
        )

        log.info(
            "Copied template",
            copied_to=copied_to,
            template=payload.template_file,
            model=payload.model,
        )

        prompt_template_example, prompt_template_file = model_prompt(
            payload.model, "sysmsg", "prompt<|BOT|>{LLM coercion}"
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
                },
            }
        )

    async def handle_determine_llm_template(self, data):
        payload = DetermineLLMTemplatePayload(**data["data"])

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

    async def handle_delete_scene(self, data):
        payload = DeleteScenePayload(**data)

        await self.handle_remove_scene_from_recents(data)

        log.info("Deleting scene", path=payload.path)

        # remove the file
        try:
            os.remove(payload.path)
        except FileNotFoundError:
            log.warning("File not found", path=payload.path)

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

    async def handle_get_backup_files(self, data):
        """Deprecated: replaced by changelog revisions. Kept for compatibility."""
        payload = GetBackupFilesPayload(**data)
        try:
            scene_dir = os.path.dirname(payload.scene_path)
            scene_filename = os.path.basename(payload.scene_path)
            scene = type(
                "Scene",
                (),
                {
                    "save_dir": scene_dir,
                    "filename": scene_filename,
                    "name": "temp",
                    "changelog_dir": os.path.join(scene_dir, "changelog"),
                },
            )()
            entries = list_revision_entries(scene)
            # Adapt to existing frontend expected structure minimally
            files = [
                {
                    "name": f"rev_{e['rev']}",
                    "path": payload.scene_path,
                    "timestamp": e["ts"],
                    "size": 0,
                    "rev": e["rev"],
                }
                for e in entries
            ]
            self.websocket_handler.queue_put(
                {"type": "backup", "action": "backup_files", "files": files}
            )
        except Exception as e:
            log.error(
                "Failed to list revisions", scene_path=payload.scene_path, error=e
            )
            self.websocket_handler.queue_put(
                {
                    "type": "backup",
                    "action": "backup_files",
                    "files": [],
                    "error": str(e),
                }
            )
