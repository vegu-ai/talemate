import asyncio
import json
import os

import pydantic
import structlog

from talemate.load import transfer_character

log = structlog.get_logger("talemate.server.character_importer")


class ListCharactersData(pydantic.BaseModel):
    scene_path: str


class ImportCharacterData(pydantic.BaseModel):
    scene_path: str
    character_name: str


class CharacterImporterServerPlugin:
    router = "character_importer"

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler

    @property
    def scene(self):
        return self.websocket_handler.scene

    async def handle(self, data: dict):
        log.info("Character importer action", action=data.get("action"))

        fn = getattr(self, f"handle_{data.get('action')}", None)

        if fn is None:
            return

        await fn(data)

    async def handle_list_characters(self, data):
        list_characters_data = ListCharactersData(**data)

        scene_path = list_characters_data.scene_path

        with open(scene_path, "r") as f:
            scene_data = json.load(f)

        self.websocket_handler.queue_put(
            {
                "type": "character_importer",
                "action": "list_characters",
                "characters": [
                    character["name"] for character in scene_data.get("characters", [])
                ],
            }
        )

        await asyncio.sleep(0)

    async def handle_import(self, data):
        import_character_data = ImportCharacterData(**data)

        scene = self.websocket_handler.scene

        await transfer_character(
            scene,
            import_character_data.scene_path,
            import_character_data.character_name,
        )

        scene.emit_status()

        self.websocket_handler.queue_put(
            {
                "type": "character_importer",
                "action": "import_character_done",
            }
        )
