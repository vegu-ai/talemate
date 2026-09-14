from typing import Any

import pydantic
import structlog

from talemate.config import get_config, Config

log = structlog.get_logger("talemate.server.quick_settings")


class SetQuickSettingsPayload(pydantic.BaseModel):
    setting: str
    value: Any


class SceneHeaderSlotEdit(pydantic.BaseModel):
    item: str
    shown: bool


class QuickSettingsPlugin:
    router = "quick_settings"

    @property
    def scene(self):
        return self.websocket_handler.scene

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler

    async def handle(self, data: dict):
        log.info("quick settings action", action=data.get("action"))

        fn = getattr(self, f"handle_{data.get('action')}", None)

        if fn is None:
            return

        await fn(data)

    async def handle_set(self, data: dict):
        payload = SetQuickSettingsPayload(**data)
        config: Config = get_config()

        if payload.setting == "auto_save":
            config.game.general.auto_save = payload.value
        elif payload.setting == "auto_progress":
            config.game.general.auto_progress = payload.value
        elif payload.setting == "auto_attach_assets":
            config.appearance.scene.auto_attach_assets = payload.value
        elif payload.setting == "scene_header_enabled":
            config.game.scene_header.enabled = payload.value
        elif payload.setting in ("scene_header_slot_a", "scene_header_slot_b"):
            # an edit applies to the stored list, never to a client copy
            edit = SceneHeaderSlotEdit.model_validate(payload.value)
            config.game.scene_header.set_item_shown(
                payload.setting.removeprefix("scene_header_"), edit.item, edit.shown
            )
        else:
            raise NotImplementedError(f"Setting {payload.setting} not implemented.")

        await config.set_dirty()

        self.websocket_handler.queue_put(
            {"type": self.router, "action": "set_done", "data": payload.model_dump()}
        )
