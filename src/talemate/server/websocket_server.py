import asyncio
import base64
import os
import traceback

import structlog

import talemate.instance as instance
from talemate import Helper, Scene
from talemate.client.base import ClientBase
from talemate.client.registry import CLIENT_CLASSES
from talemate.config import SceneAssetUpload, load_config, save_config
from talemate.context import ActiveScene, active_scene
from talemate.emit import Emission, Receiver, abort_wait_for_input, emit
from talemate.files import list_scenes_directory
from talemate.load import load_scene
from talemate.scene_assets import Asset
from talemate.agents.memory.exceptions import MemoryAgentError
from talemate.server import (
    assistant,
    character_importer,
    config,
    devtools,
    quick_settings,
    world_state_manager,
)

__all__ = [
    "WebsocketHandler",
]

log = structlog.get_logger("talemate.server.websocket_server")

AGENT_INSTANCES = {}


class WebsocketHandler(Receiver):
    def __init__(self, socket, out_queue, llm_clients=dict()):
        self.agents = {typ: {"name": typ} for typ in instance.agent_types()}
        self.socket = socket
        self.waiting_for_input = False
        self.input = None
        self.scene = Scene()
        self.out_queue = out_queue
        self.config = load_config()

        for name, agent_config in self.config.get("agents", {}).items():
            self.agents[name] = agent_config

        self.llm_clients = self.config.get("clients", llm_clients)

        instance.get_agent("memory", self.scene)

        # unconveniently named function, this `connect` method is called
        # to connect signals handlers to the websocket handler
        self.connect()

        # connect LLM clients
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.connect_llm_clients())

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
        }

        self.set_agent_routers()

        # self.request_scenes_list()

        # instance.emit_clients_status()

    def set_agent_routers(self):

        for agent_type, agent in instance.AGENTS.items():
            handler_cls = getattr(agent, "websocket_handler", None)
            if not handler_cls:
                continue

            log.info(
                "Setting agent router", agent_type=agent_type, router=handler_cls.router
            )
            self.routes[handler_cls.router] = handler_cls(self)

    def disconnect(self):
        super().disconnect()
        abort_wait_for_input()

        memory_agent = instance.get_agent("memory")
        if memory_agent and self.scene:
            memory_agent.close_db(self.scene)

    async def connect_llm_clients(self):
        client = None

        for client_name, client_config in self.llm_clients.items():
            try:
                client = self.llm_clients[client_name]["client"] = instance.get_client(
                    **client_config
                )
            except TypeError as e:
                raise
                log.error("Error connecting to client", client_name=client_name, e=e)
                continue

            log.info(
                "Configured client",
                client_name=client_name,
                client_type=client.client_type,
            )

        await self.connect_agents()

    async def connect_agents(self):
        if not self.llm_clients:
            instance.emit_agents_status()
            return

        for agent_typ, agent_config in self.agents.items():
            try:
                client = self.llm_clients.get(agent_config.get("client"))["client"]
            except TypeError as e:
                client = None

            if not client or not client.enabled:
                # select first enabled client
                try:
                    client = self.get_first_enabled_client()
                    agent_config["client"] = client.name
                except IndexError:
                    client = None

                if not client:
                    agent_config["client"] = None

            if client:
                log.debug("Linked agent", agent_typ=agent_typ, client=client.name)
            else:
                log.warning("No client available for agent", agent_typ=agent_typ)

            agent = instance.get_agent(agent_typ, client=client)
            agent.client = client
            await agent.apply_config(**agent_config)

        instance.emit_agents_status()

    def get_first_enabled_client(self) -> ClientBase:
        """
        Will return the first enabled client available

        If no enabled clients are available, an IndexError will be raised
        """
        for client in self.llm_clients.values():
            if client and client["client"].enabled:
                return client["client"]
        raise IndexError("No enabled clients available")

    def init_scene(self):
        # Setup scene
        scene = Scene()

        # Init helper agents
        for agent_typ, agent_config in self.agents.items():
            if agent_typ == "memory":
                agent_config["scene"] = scene

            log.debug("init agent", agent_typ=agent_typ, agent_config=agent_config)
            agent = instance.get_agent(agent_typ, **agent_config)

            # if getattr(agent, "client", None):
            #    self.llm_clients[agent.client.name] = agent.client

            scene.add_helper(Helper(agent))

        return scene

    async def load_scene(
        self, path_or_data, reset=False, callback=None, file_name=None
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

            conversation_helper = scene.get_helper("conversation")

            scene.active = True

            with ActiveScene(scene):
                try:
                    scene = await load_scene(
                        scene, path_or_data, conversation_helper.agent.client, reset=reset
                    )
                except MemoryAgentError as e:
                    emit("status", message=str(e), status="error")
                    log.error("load_scene", error=str(e))
                    return
                

            self.scene = scene

            if callback:
                await callback()

            with ActiveScene(scene):
                await scene.start()
        except Exception:
            log.error("load_scene", error=traceback.format_exc())
        finally:
            self.scene.active = False

    def queue_put(self, data):
        # Get the current event loop
        loop = asyncio.get_event_loop()
        # Schedule the put coroutine to run as soon as possible
        loop.call_soon_threadsafe(lambda: self.out_queue.put_nowait(data))

    async def configure_clients(self, clients):
        existing = set(self.llm_clients.keys())

        self.llm_clients = {}

        log.info("Configuring clients", clients=clients)

        for client in clients:
            client.pop("status", None)
            client_cls = CLIENT_CLASSES.get(client["type"])

            # so hacky, such sad
            ignore_model_names = [
                "Disabled",
                "No model loaded",
                "Could not connect",
                "No API key set",
            ]
            if client.get("model") in ignore_model_names:
                # if client instance exists copy model_name from it
                _client = instance.get_client(client["name"])
                if _client:
                    client["model"] = getattr(_client, "model_name", None)
                else:
                    client.pop("model", None)

            if not client_cls:
                log.error("Client type not found", client=client)
                continue

            client_config = self.llm_clients[client["name"]] = {
                "name": client["name"],
                "type": client["type"],
                "enabled": client.get("enabled", True),
            }
            for dfl_key in client_cls.Meta().defaults.dict().keys():
                client_config[dfl_key] = client.get(
                    dfl_key, client.get("data", {}).get(dfl_key)
                )

        # find clients that have been removed
        removed = existing - set(self.llm_clients.keys())
        if removed:
            for agent_typ, agent_config in self.agents.items():
                if (
                    "client"
                    in instance.agents.AGENT_CLASSES[agent_typ].config_options()
                ):
                    agent = instance.get_agent(agent_typ)
                    if agent and agent.client and agent.client.name in removed:
                        agent_config["client"] = None
                        agent.client = None
                        instance.emit_agent_status(agent.__class__, agent)

            for name in removed:
                log.debug("Destroying client", name=name)
                instance.destroy_client(name)

        self.config["clients"] = self.llm_clients

        await self.connect_llm_clients()
        save_config(self.config)

        instance.sync_emit_clients_status()

    async def configure_agents(self, agents):
        self.agents = {typ: {} for typ in instance.agent_types()}

        log.debug("Configuring agents")

        for agent in agents:
            name = agent["name"]

            # special case for memory agent
            if name == "memory" or name == "tts":
                self.agents[name] = {
                    "name": name,
                }
                agent_instance = instance.get_agent(name, **self.agents[name])
                if agent_instance.has_toggle:
                    self.agents[name]["enabled"] = agent["enabled"]

                if getattr(agent_instance, "actions", None):
                    self.agents[name]["actions"] = agent.get("actions", {})

                await agent_instance.apply_config(**self.agents[name])
                log.debug("Configured agent", name=name)
                continue

            if name not in self.agents:
                continue

            if isinstance(agent["client"], dict):
                try:
                    client_name = agent["client"]["client"]["value"]
                except KeyError:
                    continue
            else:
                client_name = agent["client"]

            if client_name not in self.llm_clients:
                continue

            self.agents[name] = {
                "client": self.llm_clients[client_name]["name"],
                "name": name,
            }

            agent_instance = instance.get_agent(name, **self.agents[name])

            try:
                agent_instance.client = self.llm_clients[client_name]["client"]
            except KeyError:
                self.llm_clients[client_name]["client"] = agent_instance.client = (
                    instance.get_client(client_name)
                )

            if agent_instance.has_toggle:
                self.agents[name]["enabled"] = agent["enabled"]

            if getattr(agent_instance, "actions", None):
                self.agents[name]["actions"] = agent.get("actions", {})

            await agent_instance.apply_config(**self.agents[name])

            log.debug(
                "Configured agent",
                name=name,
                client_name=self.llm_clients[client_name]["name"],
                client=self.llm_clients[client_name]["client"],
            )

        self.config["agents"] = self.agents
        save_config(self.config)

        instance.emit_agents_status()

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
                    }
                )
            except Exception as e:
                log.error("emission passthrough", error=traceback.format_exc())

    def handle_system(self, emission: Emission):
        self.queue_put(
            {
                "type": "system",
                "message": emission.message,
                "id": emission.id,
                "status": emission.status,
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
        self.queue_put(
            {
                "type": "narrator",
                "message": emission.message,
                "id": emission.id,
                "character": emission.character.name if emission.character else "",
                "flags": (
                    int(emission.message_object.flags) if emission.message_object else 0
                ),
            }
        )

    def handle_director(self, emission: Emission):
        if emission.character:
            character = emission.character.name
        elif emission.message_object.source:
            character = emission.message_object.source
        else:
            character = ""

        director = instance.get_agent("director")
        direction_mode = director.actor_direction_mode

        self.queue_put(
            {
                "type": "director",
                "message": emission.message_object.instructions.strip(),
                "id": emission.id,
                "character": character,
                "action": emission.message_object.action,
                "direction_mode": direction_mode,
                "flags": (
                    int(emission.message_object.flags) if emission.message_object else 0
                ),
            }
        )

    def handle_character(self, emission: Emission):
        self.queue_put(
            {
                "type": "character",
                "message": emission.message,
                "character": emission.character.name if emission.character else "",
                "id": emission.id,
                "color": emission.character.color if emission.character else None,
                "flags": (
                    int(emission.message_object.flags) if emission.message_object else 0
                ),
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

    def handle_config_saved(self, emission: Emission):
        self.queue_put(
            {
                "type": "app_config",
                "data": emission.data,
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
        client = instance.get_client(emission.id)
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
                "api_url": getattr(client, "api_url", None) if client else None,
                "api_key": getattr(client, "api_key", None) if client else None,
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

    def handle_client_bootstraps(self, emission: Emission):
        self.queue_put(
            {
                "type": "client_bootstraps",
                "data": emission.data,
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

        player_character = self.scene.get_player_character()
        player_character_name = player_character.name if player_character else ""

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

    def request_scenes_list(self, query: str = ""):
        scenes_list = list_scenes_directory()

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

    def request_scene_assets(self, asset_ids: list[str]):
        scene_assets = self.scene.assets

        try:
            for asset_id in asset_ids:
                asset = scene_assets.get_asset_bytes_as_base64(asset_id)

                self.queue_put(
                    {
                        "type": "scene_asset",
                        "asset_id": asset_id,
                        "asset": asset,
                        "media_type": scene_assets.get_asset(asset_id).media_type,
                    }
                )
        except Exception as exc:
            log.error("request_scene_assets", error=traceback.format_exc())

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
            except Exception as exc:
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

    def add_scene_asset(self, data: dict):
        asset_upload = SceneAssetUpload(**data)
        asset = self.scene.assets.add_asset_from_image_data(asset_upload.content)

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
                    "asset": self.scene.assets.get_asset_bytes_as_base64(asset.id),
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
                editor.fix_exposition(new_text, character)
            )

        self.scene.edit_message(message_id, new_text)

    def apply_scene_config(self, scene_config: dict):
        self.scene.apply_scene_config(scene_config)
        self.queue_put(
            {
                "type": "scene_config",
                "data": self.scene.scene_config,
            }
        )

    def handle_character_card_upload(self, image_data_url: str, filename: str) -> str:
        image_type = image_data_url.split(";")[0].split(":")[1]
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
