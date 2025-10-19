import pydantic
import structlog
import os
from datetime import datetime
from pathlib import Path

from talemate import VERSION
from talemate.changelog import list_revision_entries, delete_changelog_files
from talemate.client.model_prompts import model_prompt
from talemate.client.registry import CLIENT_CLASSES
from talemate.client.base import ClientBase, locked_model_template
from talemate.config import Config as AppConfigData
from talemate.config.schema import GamePlayerCharacter
from talemate.config import get_config, Config, update_config
from talemate.emit import emit
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


class ToggleClientPayload(pydantic.BaseModel):
    name: str
    state: bool


class DeleteScenePayload(pydantic.BaseModel):
    path: str


class GetBackupFilesPayload(pydantic.BaseModel):
    scene_path: str
    filter_date: str | None = None


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

        prompt_template_example, prompt_template_file = model_prompt(
            model_name, "sysmsg", "prompt<|BOT|>{LLM coercion}"
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

        # remove associated changelog files (base, latest, and segmented changelog files)
        try:
            # Construct a proper scene reference from the deleted file path
            scene_dir = os.path.dirname(payload.path)
            scene_filename = os.path.basename(payload.path)
            scene_ref = type('Scene', (), {
                'save_dir': scene_dir,
                'filename': scene_filename,
                'changelog_dir': os.path.join(scene_dir, 'changelog'),
            })()

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

    async def handle_get_backup_files(self, data):
        """Get the most appropriate revision for the scene."""
        payload = GetBackupFilesPayload(**data)
        try:
            # we dont actually have the scene loaded at this point so we need
            # to scaffold a temporary scene object that has the necessary paths
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

            # Get base and latest snapshot file info
            changelog_dir = Path(scene.changelog_dir)
            base_path = changelog_dir / f"{scene.filename}.base.json"
            latest_path = changelog_dir / f"{scene.filename}.latest.json"

            base_mtime = base_path.stat().st_mtime if base_path.exists() else None
            latest_mtime = latest_path.stat().st_mtime if latest_path.exists() else None

            files = []
            if payload.filter_date:
                # Find the revision closest to the filter date (before or after)
                # Only show specific revision when filtering by date

                filter_ts = int(
                    datetime.fromisoformat(
                        payload.filter_date.replace("Z", "+00:00")
                    ).timestamp()
                )

                entries = list_revision_entries(scene)
                candidate = None
                best_distance = None
                for entry in entries:
                    distance = abs(entry["ts"] - filter_ts)
                    if (
                        best_distance is None
                        or distance < best_distance
                        or (distance == best_distance and candidate)
                    ):
                        candidate = entry
                        best_distance = distance

                if candidate:
                    files.append(
                        {
                            "name": f"rev_{candidate['rev']}",
                            "path": payload.scene_path,
                            "timestamp": candidate["ts"],
                            "size": 0,
                            "rev": candidate["rev"],
                        }
                    )

            # Always include base and latest snapshots as restore options
            entries = list_revision_entries(scene)
            if base_mtime:
                files.append(
                    {
                        "name": "base",
                        "path": payload.scene_path,
                        "timestamp": int(base_mtime),
                        "size": 0,
                        "rev": 0,
                        "is_base": True,
                    }
                )

            if latest_mtime:
                latest_rev = entries[0]["rev"] if entries else 0
                files.append(
                    {
                        "name": "latest",
                        "path": payload.scene_path,
                        "timestamp": int(latest_mtime),
                        "size": 0,
                        "rev": latest_rev,
                        "is_latest": True,
                    }
                )

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
