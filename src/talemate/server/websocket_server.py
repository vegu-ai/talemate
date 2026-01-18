import asyncio
import base64
import uuid
import os
import traceback

import structlog

import talemate.instance as instance
from talemate import Scene
from talemate.client.system_prompts import RENDER_CACHE as SYSTEM_PROMPTS_CACHE
from talemate.config.schema import SceneAssetUpload
from talemate.config import get_config, Config
from talemate.context import ActiveScene
from talemate.emit import Emission, Receiver, abort_wait_for_input, emit
import talemate.emit.async_signals as async_signals
from talemate.files import list_scenes_directory
from talemate.load import load_scene, SceneInitialization
from talemate.scene_assets import Asset, get_media_type_from_file_path, VIS_TYPE
from talemate.server import (
    assistant,
    character_importer,
    config,
    devtools,
    quick_settings,
    ux,
    world_state_manager,
    node_editor,
    package_manager,
    scene_assets as scene_assets_plugin,
)
from talemate.server.scene_assets_batching import SceneAssetsBatchingMixin

__all__ = [
    "WebsocketHandler",
]

log = structlog.get_logger("talemate.server.websocket_server")

AGENT_INSTANCES = {}


class WebsocketHandler(SceneAssetsBatchingMixin, Receiver):
    def __init__(self, socket, out_queue, llm_clients=dict()):
        self.socket = socket
        self.waiting_for_input = False
        self.input = None
        self.scene = Scene()
        self.out_queue = out_queue

        # Initialize scene assets batching
        self._init_scene_assets_batching()

        self.routes = {
            assistant.AssistantPlugin.router: assistant.AssistantPlugin(self),
            character_importer.CharacterImporterServerPlugin.router: character_importer.CharacterImporterServerPlugin(
                self
            ),
            config.ConfigPlugin.router: config.ConfigPlugin(self),
            world_state_manager.WorldStateManagerPlugin.router: world_state_manager.WorldStateManagerPlugin(
                self
            ),
            quick_settings.QuickSettingsPlugin.router: quick_settings.QuickSettingsPlugin(
                self
            ),
            devtools.DevToolsPlugin.router: devtools.DevToolsPlugin(self),
            node_editor.NodeEditorPlugin.router: node_editor.NodeEditorPlugin(self),
            package_manager.PackageManagerPlugin.router: package_manager.PackageManagerPlugin(
                self
            ),
            scene_assets_plugin.SceneAssetsPlugin.router: scene_assets_plugin.SceneAssetsPlugin(
                self
            ),
            ux.UxPlugin.router: ux.UxPlugin(self),
        }

        # unconveniently named function, this `connect` method is called
        # to connect signals handlers to the websocket handler
        self.connect()

        self.set_agent_routers()

        instance.emit_agents_status()

    @property
    def config(self) -> Config:
        return get_config()

    def set_agent_routers(self):
        for agent_type, agent in instance.AGENTS.items():
            handler_cls = getattr(agent, "websocket_handler", None)
            if not handler_cls or handler_cls.router in self.routes:
                continue

            log.info(
                "Setting agent router", agent_type=agent_type, router=handler_cls.router
            )
            self.routes[handler_cls.router] = handler_cls(self)

    def disconnect(self):
        super().disconnect()
        abort_wait_for_input()

        # Cleanup scene assets batching
        self._cleanup_scene_assets_batching()

        memory_agent = instance.get_agent("memory")
        if memory_agent and self.scene:
            memory_agent.close_db(self.scene)

        for plugin in self.routes.values():
            if hasattr(plugin, "disconnect"):
                plugin.disconnect()

    def connect(self):
        super().connect()
        async_signals.get("config.changed").connect(self.on_config_changed)

    def init_scene(self):
        # Setup scene
        scene = Scene()

        # Init helper agents
        for agent_typ in instance.agent_types():
            agent = instance.get_agent(agent_typ)
            agent.connect(scene)
            agent.scene = scene
            if agent_typ == "memory":
                continue
            log.debug("init agent", agent_typ=agent_typ)

        return scene

    async def load_scene(
        self,
        path_or_data,
        reset=False,
        callback=None,
        file_name=None,
        rev: int | None = None,
        scene_initialization: dict | None = None,
    ):
        try:
            if self.scene:
                instance.get_agent("memory").close_db(self.scene)
                self.scene.disconnect()
                self.scene.active = False

            scene = self.init_scene()

            if not scene:
                await asyncio.sleep(0.1)
                return

            self.scene = scene

            scene.active = True

            with ActiveScene(scene):
                try:
                    # Use input path directly
                    scene_path = path_or_data
                    add_to_recent = rev is None
                    scene = await load_scene(
                        scene,
                        scene_path,
                        reset=reset,
                        add_to_recent=add_to_recent,
                        scene_initialization=SceneInitialization(**scene_initialization)
                        if scene_initialization
                        else None,
                    )
                    # If a revision is requested, reconstruct and load it
                    if rev is not None:
                        from talemate.changelog import write_reconstructed_scene

                        temp_name = f"{scene.filename.replace('.json', '')}-{str(uuid.uuid4())[:10]}.json"
                        temp_path = await write_reconstructed_scene(
                            scene, to_rev=rev, output_filename=temp_name
                        )
                        scene = self.init_scene()
                        scene.active = True
                        scene._memory_never_persisted = True
                        scene = await load_scene(
                            scene,
                            temp_path,
                            add_to_recent=False,
                        )
                        scene.filename = ""
                        os.remove(temp_path)
                except Exception as e:
                    self.scene = self.init_scene()
                    return await self.load_scene_failure(e)

            if not scene:
                # if scene is None at this point then load scene failed, likely with
                # a warning. This usually happens when generation cancel was triggered.
                # TODO: more explicit handling
                return await self.load_scene_failure(
                    Exception("Scene loading interrupted")
                )

            if callback:
                await callback()

            with ActiveScene(scene):
                await scene.start()
        except Exception:
            log.error("load_scene", error=traceback.format_exc())
        finally:
            self.scene.active = False

    async def load_scene_failure(self, error: Exception):
        emit("status", message=str(error), status="error")
        await self.out_queue.put(
            {
                "type": "system",
                "id": "scene.load_failure",
                "data": {
                    "hidden": True,
                },
            }
        )

    def queue_put(self, data):
        # Get the current event loop
        loop = asyncio.get_event_loop()
        # Schedule the put coroutine to run as soon as possible
        loop.call_soon_threadsafe(lambda: self.out_queue.put_nowait(data))

    def handle(self, emission: Emission):
        called = super().handle(emission)

        if called is False and emission.websocket_passthrough:
            log.debug(
                "emission passthrough", emission=emission.message, typ=emission.typ
            )
            try:
                self.queue_put(
                    {
                        "type": emission.typ,
                        "message": emission.message,
                        "data": emission.data,
                        "meta": emission.meta,
                        **emission.kwargs,
                    }
                )
            except Exception:
                log.error("emission passthrough", error=traceback.format_exc())

    def handle_system(self, emission: Emission):
        # Generate UUID for system messages if they don't have an id
        message_id = emission.id if emission.id else str(uuid.uuid4())
        self.queue_put(
            {
                "type": "system",
                "message": emission.message,
                "id": message_id,
                "status": emission.status,
                "meta": emission.meta,
                "character": emission.character.name if emission.character else "",
            }
        )

    def handle_status(self, emission: Emission):
        self.queue_put(
            {
                "type": "status",
                "message": emission.message,
                "id": emission.id,
                "status": emission.status,
                "data": emission.data,
            }
        )

    def handle_narrator(self, emission: Emission):
        message_obj = emission.message_object
        asset_id = None
        asset_type = None
        if message_obj and hasattr(message_obj, "asset_id"):
            asset_id = message_obj.asset_id
            asset_type = message_obj.asset_type

        self.queue_put(
            {
                "type": "narrator",
                "message": emission.message,
                "id": emission.id,
                "character": emission.character.name if emission.character else "",
                "asset_id": asset_id,
                "asset_type": asset_type,
                "flags": (
                    int(emission.message_object.flags) if emission.message_object else 0
                ),
                "rev": (emission.message_object.rev if emission.message_object else 0),
            }
        )

    def handle_director(self, emission: Emission):
        director = instance.get_agent("director")
        direction_mode = director.actor_direction_mode

        # Scene direction protocol
        if (
            emission.data
            and emission.data.get("scene_direction_protocol")
            and emission.data.get("action")
        ):
            self.queue_put(
                {
                    "type": "director",
                    "action": emission.data.get("action"),
                    **emission.data,
                }
            )
            return

        # Director chat protocol
        if emission.data and "chat_id" in emission.data:
            self.queue_put(
                {
                    "type": "director",
                    "action": emission.data.get("action"),
                    "chat_id": emission.data.get("chat_id"),
                    **emission.data,
                }
            )
            return

        # Nothing more we can do without a proper DirectorMessage payload
        if emission.message_object is None:
            return

        character = emission.message_object.character_name

        self.queue_put(
            {
                "type": "director",
                "message": emission.message_object.instructions.strip(),
                "id": emission.id,
                "character": character,
                "action": emission.message_object.action,
                "direction_mode": direction_mode,
                "subtype": emission.message_object.subtype,
                "data": emission.data,
                "flags": (
                    int(emission.message_object.flags) if emission.message_object else 0
                ),
                "rev": (emission.message_object.rev if emission.message_object else 0),
            }
        )

    def handle_character(self, emission: Emission):
        message_obj = emission.message_object
        asset_id = None
        asset_type = None
        if message_obj and hasattr(message_obj, "asset_id"):
            asset_id = message_obj.asset_id
            asset_type = message_obj.asset_type

        self.queue_put(
            {
                "type": "character",
                "message": emission.message,
                "character": emission.character.name if emission.character else "",
                "id": emission.id,
                "color": emission.character.color if emission.character else None,
                "asset_id": asset_id,
                "asset_type": asset_type,
                "flags": (
                    int(emission.message_object.flags) if emission.message_object else 0
                ),
                "rev": (emission.message_object.rev if emission.message_object else 0),
            }
        )

    def handle_time(self, emission: Emission):
        self.queue_put(
            {
                "type": "time",
                "message": emission.message,
                "id": emission.id,
                "ts": emission.message_object.ts,
                "flags": (
                    int(emission.message_object.flags) if emission.message_object else 0
                ),
            }
        )

    def handle_context_investigation(self, emission: Emission):
        message_obj = emission.message_object
        asset_id = None
        asset_type = None
        if message_obj and hasattr(message_obj, "asset_id"):
            asset_id = message_obj.asset_id
            asset_type = message_obj.asset_type

        self.queue_put(
            {
                "type": "context_investigation",
                "sub_type": message_obj.sub_type if message_obj else None,
                "source_agent": message_obj.source_agent if message_obj else None,
                "source_function": message_obj.source_function if message_obj else None,
                "source_arguments": message_obj.source_arguments
                if message_obj
                else None,
                "message": emission.message,
                "id": emission.id,
                "asset_id": asset_id,
                "asset_type": asset_type,
                "flags": (int(message_obj.flags) if message_obj else 0),
            }
        )

    def handle_prompt_sent(self, emission: Emission):
        self.queue_put(
            {
                "type": "prompt_sent",
                "data": emission.data,
            }
        )

    def handle_clear_screen(self, emission: Emission):
        self.queue_put(
            {
                "type": "clear_screen",
            }
        )

    def handle_remove_message(self, emission: Emission):
        self.queue_put(
            {
                "type": "remove_message",
                "id": emission.id,
            }
        )

    def handle_scene_status(self, emission: Emission):
        self.queue_put(
            {
                "type": "scene_status",
                "name": emission.message,
                "status": emission.status,
                "data": emission.data,
            }
        )

    def handle_world_state(self, emission: Emission):
        self.queue_put(
            {
                "type": "world_state",
                "data": emission.data,
                "status": emission.status,
            }
        )

    async def on_config_changed(self, config: Config):
        data = config.model_dump()

        data.update(system_prompt_defaults=SYSTEM_PROMPTS_CACHE)

        self.queue_put(
            {
                "type": "app_config",
                "data": data,
            }
        )

    def handle_archived_history(self, emission: Emission):
        self.queue_put(
            {
                "type": "scene_history",
                "history": emission.data.get("history", []),
            }
        )

    def handle_command_status(self, emission: Emission):
        self.queue_put(
            {
                "type": "command_status",
                "name": emission.message,
                "status": emission.status,
                "data": emission.data,
            }
        )

    def handle_client_status(self, emission: Emission):
        try:
            client = instance.get_client(emission.id)
        except KeyError:
            return

        enable_api_auth = client.Meta().enable_api_auth if client else False
        self.queue_put(
            {
                "type": "client_status",
                "message": emission.message,
                "model_name": emission.details,
                "name": emission.id,
                "status": emission.status,
                "data": emission.data,
                "max_token_length": client.max_token_length if client else 8192,
                "api_url": getattr(client, "api_url", None) if client else None,
                "api_key": getattr(client, "api_key", None)
                if enable_api_auth
                else None,
            }
        )

    def handle_agent_status(self, emission: Emission):
        self.queue_put(
            {
                "type": "agent_status",
                "message": emission.message,
                "client": emission.details,
                "name": emission.id,
                "status": emission.status,
                "data": emission.data,
                "meta": emission.meta,
            }
        )

    def handle_message_edited(self, emission: Emission):
        self.queue_put(
            {
                "type": "message_edited",
                "message": emission.message,
                "id": emission.id,
                "character": emission.character.name if emission.character else "",
            }
        )

    def handle_autocomplete_suggestion(self, emission: Emission):
        self.queue_put(
            {
                "type": "autocomplete_suggestion",
                "message": emission.message,
            }
        )

    def handle_audio_queue(self, emission: Emission):
        self.queue_put(
            {
                "type": "audio_queue",
                "data": emission.data,
            }
        )

    def handle_request_input(self, emission: Emission):
        self.waiting_for_input = True

        if emission.character and emission.character.is_player:
            message = None
        else:
            message = emission.message

        self.queue_put(
            {
                "type": "request_input",
                "message": message,
                "character": emission.character.name if emission.character else "",
                "data": emission.data,
                "reason": emission.data.get("reason", "") if emission.data else None,
            }
        )

    def send_input(self, message):
        if not self.waiting_for_input:
            return
        self.waiting_for_input = False
        emit(
            typ="receive_input",
            message=message,
        )

        if (
            self.scene.commands.processing_command
            or not message
            or message.startswith("!")
            or self.scene.environment == "creative"
        ):
            self.queue_put({"type": "processing_input"})
            return

        self.queue_put(
            {
                "type": "processing_input",
            }
        )

    async def handle_base64(self, b64data):
        """
        Handle file upload from the client.

        The file data is expected to be a base64 encoded string.

        :param file_data: base64 encoded string representing the file data
        """
        # Decode the base64 string back into bytes
        file_bytes = base64.b64decode(b64data)
        await asyncio.sleep(0.1)

        return file_bytes

    def request_scenes_list(self, query: str = "", list_images: bool = True):
        scenes_list = list_scenes_directory(list_images=list_images)

        if query:
            filtered_list = [
                scene for scene in scenes_list if query.lower() in scene.lower()
            ]
        else:
            filtered_list = scenes_list

        self.queue_put(
            {
                "type": "scenes_list",
                "data": [
                    {
                        "path": scene,
                        "label": "/".join(scene.split("/")[-2:]),
                    }
                    for scene in filtered_list
                    if not os.path.isdir(scene)
                ],
            }
        )

    def request_scene_history(self):
        history = [archived_history for archived_history in self.scene.archived_history]

        self.queue_put(
            {
                "type": "scene_history",
                "history": history,
            }
        )

    async def request_client_status(self):
        await instance.emit_clients_status()

    def request_file_image_data(self, file_path: str):
        """
        Read an image file from the given path and return it as a base64 data URL.
        Used for displaying image previews when loading character cards from file paths.
        """
        try:
            if not os.path.exists(file_path):
                self.queue_put(
                    {
                        "type": "file_image_data",
                        "file_path": file_path,
                        "error": f"File not found: {file_path}",
                    }
                )
                return

            try:
                media_type = get_media_type_from_file_path(file_path)
            except ValueError as e:
                self.queue_put(
                    {
                        "type": "file_image_data",
                        "file_path": file_path,
                        "error": str(e),
                    }
                )
                return

            # Read file and encode as base64
            with open(file_path, "rb") as f:
                file_bytes = f.read()
                base64_data = base64.b64encode(file_bytes).decode("utf-8")
                data_url = f"data:{media_type};base64,{base64_data}"

            self.queue_put(
                {
                    "type": "file_image_data",
                    "file_path": file_path,
                    "image_data": data_url,
                    "media_type": media_type,
                }
            )
        except Exception:
            log.error("request_file_image_data", error=traceback.format_exc())
            self.queue_put(
                {
                    "type": "file_image_data",
                    "file_path": file_path,
                    "error": traceback.format_exc(),
                }
            )

    def request_assets(self, assets: list[dict]):
        # way to request scene assets without loading the scene
        #
        # assets is a list of dicts with keys:
        # path must be turned into absolute path
        # path must begin with Scene.scenes_dir()

        _assets = {}

        for asset_dict in assets:
            try:
                asset_id, asset = self._asset(**asset_dict)
            except Exception:
                log.error("request_assets", error=traceback.format_exc(), **asset_dict)
                continue
            _assets[asset_id] = asset

        self.queue_put(
            {
                "type": "assets",
                "assets": _assets,
            }
        )

    def _asset(self, path: str, **asset):
        absolute_path = os.path.abspath(path)

        if not absolute_path.startswith(Scene.scenes_dir()):
            log.error(
                "_asset",
                error="Invalid path",
                path=absolute_path,
                scenes_dir=Scene.scenes_dir(),
            )
            return

        asset_path = os.path.join(os.path.dirname(absolute_path), "assets")
        asset = Asset(**asset)
        return asset.id, {
            "base64": asset.to_base64(asset_path),
            "media_type": asset.media_type,
        }

    async def add_scene_asset(self, data: dict):
        asset_upload = SceneAssetUpload(**data)
        asset = await self.scene.assets.add_asset_from_image_data(asset_upload.content)

        asset.meta.vis_type = asset_upload.vis_type or VIS_TYPE.UNSPECIFIED
        asset.meta.character_name = asset_upload.character_name

        if asset_upload.scene_cover_image:
            self.scene.assets.cover_image = asset.id
            self.scene.saved = False
            self.scene.emit_status()
        if asset_upload.character_cover_image:
            character = self.scene.get_character(asset_upload.character_cover_image)
            old_cover_image = character.cover_image
            character.cover_image = asset.id
            if (
                not self.scene.assets.cover_image
                or old_cover_image == self.scene.assets.cover_image
            ):
                self.scene.assets.cover_image = asset.id
            self.scene.saved = False
            self.scene.emit_status()
            self.request_scene_assets([character.cover_image])
            self.queue_put(
                {
                    "type": "scene_asset_character_cover_image",
                    "asset_id": asset.id,
                    "media_type": asset.media_type,
                    "character": character.name,
                }
            )

    def delete_message(self, message_id):
        self.scene.delete_message(message_id)

    def edit_message(self, message_id, new_text):
        message = self.scene.get_message(message_id)

        editor = instance.get_agent("editor")

        if editor.enabled and message.typ == "character":
            character = self.scene.get_character(message.character_name)
            loop = asyncio.get_event_loop()
            new_text = loop.run_until_complete(
                editor.cleanup_character_message(new_text, character)
            )

        self.scene.edit_message(message_id, new_text)

    def handle_character_card_upload(self, image_data_url: str, filename: str) -> str:
        image_data = base64.b64decode(image_data_url.split(",")[1])
        characters_path = os.path.join("./scenes", "characters")

        filepath = os.path.join(characters_path, filename)

        with open(filepath, "wb") as f:
            f.write(image_data)

        return filepath

    async def route(self, data: dict):
        route = data["type"]

        if route not in self.routes:
            return

        plugin = self.routes[route]
        try:
            await plugin.handle(data)
        except Exception as e:
            log.error("route", error=traceback.format_exc())
            self.queue_put(
                {
                    "plugin": plugin.router,
                    "type": "error",
                    "error": str(e),
                }
            )
