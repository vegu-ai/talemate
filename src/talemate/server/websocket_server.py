import asyncio
import base64
import os
import traceback
import structlog

import talemate.instance as instance
from talemate import Helper, Scene
from talemate.config import load_config, save_config, SceneAssetUpload
from talemate.emit import Emission, Receiver, abort_wait_for_input, emit
from talemate.files import list_scenes_directory
from talemate.load import load_scene, load_scene_from_data, load_scene_from_character_card


from talemate.server import character_creator
from talemate.server import character_importer
from talemate.server import scene_creator
from talemate.server import config

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
        
        self.connect_llm_clients()

        self.routes = {    
            character_creator.CharacterCreatorServerPlugin.router: character_creator.CharacterCreatorServerPlugin(self),
            character_importer.CharacterImporterServerPlugin.router: character_importer.CharacterImporterServerPlugin(self),
            scene_creator.SceneCreatorServerPlugin.router: scene_creator.SceneCreatorServerPlugin(self),
            config.ConfigPlugin.router: config.ConfigPlugin(self),
        }

        # self.request_scenes_list()

        # instance.emit_clients_status()

    def disconnect(self):
        super().disconnect()
        abort_wait_for_input()

        memory_agent = instance.get_agent("memory")
        if memory_agent and self.scene:
            memory_agent.close_db(self.scene)

    def connect_llm_clients(self):
        client = None

        for client_name, client_config in self.llm_clients.items():
            try:
                client = self.llm_clients[client_name]["client"] = instance.get_client(
                    **client_config
                )
            except TypeError as e:
                log.error("Error connecting to client", client_name=client_name, e=e)
                continue

            log.info("Configured client", client_name=client_name, client_type=client.client_type)

        self.connect_agents()
        
    def connect_agents(self):
        
        if not self.llm_clients:
            instance.emit_agents_status()
            return
        
        for agent_typ, agent_config in self.agents.items():
            try:
                client = self.llm_clients.get(agent_config.get("client"))["client"]
            except TypeError:
                client = None
                
            if not client:
                # select first client
                client = list(self.llm_clients.values())[0]["client"]
                agent_config["client"] = client.name
            
            log.debug("Linked agent", agent_typ=agent_typ, client=client.name)
            agent = instance.get_agent(agent_typ, client=client)
            agent.client = client
            agent.apply_config(**agent_config)
            
            
        instance.emit_agents_status()

    def init_scene(self):
        # Setup scene
        scene = Scene()

        # Init helper agents
        for agent_typ, agent_config in self.agents.items():
            if agent_typ == "memory":
                agent_config["scene"] = scene

            log.debug("init agent", agent_typ=agent_typ, agent_config=agent_config)
            agent = instance.get_agent(agent_typ, **agent_config)

            #if getattr(agent, "client", None):
            #    self.llm_clients[agent.client.name] = agent.client

            scene.add_helper(Helper(agent))

        return scene

    async def load_scene(self, path_or_data, reset=False, callback=None, file_name=None):
        try:
            
            if self.scene:
                instance.get_agent("memory").close_db(self.scene)
            
            scene = self.init_scene()

            if not scene:
                await asyncio.sleep(0.1)
                return

            conversation_helper = scene.get_helper("conversation")

            scene = await load_scene(
                scene, path_or_data, conversation_helper.agent.client, reset=reset
            )

            self.scene = scene

            if callback:
                await callback()

            await scene.start()
        except Exception:
            log.error("load_scene", error=traceback.format_exc())

    def queue_put(self, data):
        # Get the current event loop
        loop = asyncio.get_event_loop()
        # Schedule the put coroutine to run as soon as possible
        loop.call_soon_threadsafe(lambda: self.out_queue.put_nowait(data))

    def configure_clients(self, clients):
        existing = set(self.llm_clients.keys())

        self.llm_clients = {}
        
        log.info("Configuring clients", clients=clients)
        
        for client in clients:
            
            client.pop("status", None)
            
            if client["type"] in ["textgenwebui", "lmstudio"]:
                try:
                    max_token_length = int(client.get("max_token_length", 2048))
                except ValueError:
                    continue
                
                client.pop("model", None)

                self.llm_clients[client["name"]] = {
                    "type": client["type"],
                    "api_url": client["apiUrl"],
                    "name": client["name"],
                    "max_token_length": max_token_length,
                }
            elif client["type"] == "openai":
                
                client.pop("model_name", None)
                client.pop("apiUrl", None)
                
                self.llm_clients[client["name"]] = {
                    "type": "openai",
                    "name": client["name"],
                    "model": client.get("model", client.get("model_name")),
                    "max_token_length": client.get("max_token_length"),
                }

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

        self.connect_llm_clients()
        save_config(self.config)

    def configure_agents(self, agents):
        self.agents = {typ: {} for typ in instance.agent_types()}
        
        log.debug("Configuring agents", agents=agents)

        for agent in agents:
            name = agent["name"]

            # special case for memory agent
            if name == "memory":
                self.agents[name] = {
                    "name": name,
                }
                continue

            if name not in self.agents:
                continue

            if agent["client"] not in self.llm_clients:
                continue

            self.agents[name] = {
                "client": self.llm_clients[agent["client"]]["name"],
                "name": name,
            }

            agent_instance = instance.get_agent(name, **self.agents[name])
            agent_instance.client = self.llm_clients[agent["client"]]["client"]
            
            if agent_instance.has_toggle:
                self.agents[name]["enabled"] = agent["enabled"]

            if getattr(agent_instance, "actions", None):
                self.agents[name]["actions"] = agent.get("actions", {})
                
            agent_instance.apply_config(**self.agents[name])
            
            log.debug("Configured agent", name=name, client_name=self.llm_clients[agent["client"]]["name"], client=self.llm_clients[agent["client"]]["client"])

        self.config["agents"] = self.agents
        save_config(self.config)

        instance.emit_agents_status()

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

    def handle_narrator(self, emission: Emission):
        self.queue_put(
            {
                "type": "narrator",
                "message": emission.message,
                "id": emission.id,
                "character": emission.character.name if emission.character else "",
            }
        )
        
    def handle_director(self, emission: Emission):
        
        if emission.character:
            character = emission.character.name
        elif emission.message_object.source:
            character = emission.message_object.source
        else:
            character = ""
        
        self.queue_put(
            {
                "type": "director",
                "message": emission.message,
                "id": emission.id,
                "character": character,
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
            }
        )

    def handle_time(self, emission: Emission):
        self.queue_put(
            {
                "type": "time",
                "message": emission.message,
                "id": emission.id,
                "ts": emission.message_object.ts,
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
                "max_token_length": client.max_token_length if client else 2048,
                "apiUrl": getattr(client, "api_url", None) if client else None,
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
        history = [archived_history["text"] for archived_history in self.scene.archived_history]
        
        self.queue_put(
            {
                "type": "scene_history",
                "history": history,
            }
        )

    async def request_client_status(self):
        instance.emit_clients_status()
        
    def request_scene_assets(self, asset_ids:list[str]):
        scene_assets = self.scene.assets
        
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
        
    def add_scene_asset(self, data:dict):
        asset_upload = SceneAssetUpload(**data)
        asset = self.scene.assets.add_asset_from_image_data(asset_upload.content)
        
        if asset_upload.scene_cover_image:
            self.scene.assets.cover_image = asset.id
            self.scene.emit_status()
        if asset_upload.character_cover_image:
            character = self.scene.get_character(asset_upload.character_cover_image)
            old_cover_image = character.cover_image
            character.cover_image = asset.id
            if not self.scene.assets.cover_image or old_cover_image == self.scene.assets.cover_image:
                self.scene.assets.cover_image = asset.id
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
        self.scene.edit_message(message_id, new_text)

    def apply_scene_config(self, scene_config:dict):
        self.scene.apply_scene_config(scene_config)
        self.queue_put(
            {
                "type": "scene_config",
                "data": self.scene.scene_config,
            }
        )
        
    def handle_character_card_upload(self, image_data_url:str, filename:str) -> str:
            
        image_type = image_data_url.split(";")[0].split(":")[1]
        image_data = base64.b64decode(image_data_url.split(",")[1])
        characters_path = os.path.join("./scenes", "characters")
        
        filepath = os.path.join(characters_path, filename)
        
        with open(filepath, "wb") as f:
            f.write(image_data)
            
        return filepath
        
        
    async def route(self, data:dict):
        
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