from typing import Any

import pydantic
import structlog

from talemate.config import get_config, Config

log = structlog.get_logger("talemate.server.quick_settings")


class SetQuickSettingsPayload(pydantic.BaseModel):
    setting: str
    value: Any


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
        else:
            raise NotImplementedError(f"Setting {payload.setting} not implemented.")

        await config.set_dirty()

        self.websocket_handler.queue_put(
            {"type": self.router, "action": "set_done", "data": payload.model_dump()}
        )
