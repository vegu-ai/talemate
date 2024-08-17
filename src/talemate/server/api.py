import asyncio
import json
import os
import traceback

import starlette.websockets
import structlog
import websockets

import talemate.instance as instance
from talemate import VERSION
from talemate.config import load_config
from talemate.server.websocket_server import WebsocketHandler

log = structlog.get_logger("talemate")
from talemate.context import ActiveScene, Interaction


async def websocket_endpoint(websocket, path):
    # Create a queue for outgoing messages
    message_queue = asyncio.Queue()
    handler = WebsocketHandler(websocket, message_queue)
    scene_task = None

    log.info("frontend connected")

    try:
        # Create a task to send messages from the queue
        async def send_messages():
            while True:
                # check if there are messages in the queue
                if message_queue.empty():
                    await asyncio.sleep(0.01)
                    continue

                message = await message_queue.get()
                await websocket.send(json.dumps(message))

        send_messages_task = asyncio.create_task(send_messages())

        # Create a task to send regular client status updates
        async def send_status():
            while True:
                await instance.emit_clients_status()
                await instance.agent_ready_checks()
                await asyncio.sleep(3)

        send_status_task = asyncio.create_task(send_status())

        # create a task that will retriece client boostrap information

        async def send_client_bootstraps():
            while True:
                try:
                    await instance.sync_client_bootstraps()
                except Exception as e:
                    log.error(
                        "send_client_bootstraps",
                        error=e,
                        traceback=traceback.format_exc(),
                    )
                await asyncio.sleep(15)

        send_client_bootstraps_task = asyncio.create_task(send_client_bootstraps())

        while True:
            data = await websocket.recv()
            data = json.loads(data)
            action_type = data.get("type")

            scene_data = None

            log.debug("frontend message", action_type=action_type)

            with ActiveScene(handler.scene):
                if action_type == "load_scene":
                    if scene_task:
                        handler.scene.continue_scene = False
                        scene_task.cancel()

                    file_path = data.get("file_path")
                    scene_data = data.get("scene_data")
                    filename = data.get("filename")
                    reset = data.get("reset", False)

                    await message_queue.put(
                        {
                            "type": "system",
                            "message": "Loading scene file ...",
                            "id": "scene.loading",
                            "status": "loading",
                        }
                    )

                    async def scene_loading_done():
                        await message_queue.put(
                            {
                                "type": "system",
                                "message": "Scene file loaded ...",
                                "id": "scene.loaded",
                                "status": "success",
                                "data": {
                                    "hidden": True,
                                    "environment": handler.scene.environment,
                                },
                            }
                        )

                    if scene_data and filename:
                        file_path = handler.handle_character_card_upload(
                            scene_data, filename
                        )

                    log.info("load_scene", file_path=file_path, reset=reset)

                    # Create a task to load the scene in the background
                    scene_task = asyncio.create_task(
                        handler.load_scene(
                            file_path, reset=reset, callback=scene_loading_done
                        )
                    )

                elif action_type == "interact":
                    log.debug("interact", data=data)
                    text = data.get("text")
                    with Interaction(act_as=data.get("act_as")):
                        if handler.waiting_for_input:
                            handler.send_input(text)

                elif action_type == "request_scenes_list":
                    query = data.get("query", "")
                    handler.request_scenes_list(query)
                elif action_type == "configure_clients":
                    await handler.configure_clients(data.get("clients"))
                elif action_type == "configure_agents":
                    await handler.configure_agents(data.get("agents"))
                elif action_type == "request_client_status":
                    await handler.request_client_status()
                elif action_type == "delete_message":
                    handler.delete_message(data.get("id"))
                elif action_type == "scene_config":
                    log.info("scene_config", data=data)
                    handler.apply_scene_config(data.get("scene_config"))
                elif action_type == "request_scene_assets":
                    log.info("request_scene_assets", data=data)
                    handler.request_scene_assets(data.get("asset_ids"))
                elif action_type == "upload_scene_asset":
                    log.info("upload_scene_asset")
                    handler.add_scene_asset(data=data)
                elif action_type == "request_scene_history":
                    log.info("request_scene_history")
                    handler.request_scene_history()
                elif action_type == "request_assets":
                    log.info("request_assets")
                    handler.request_assets(data.get("assets"))
                elif action_type == "edit_message":
                    log.info("edit_message", data=data)
                    handler.edit_message(data.get("id"), data.get("text"))
                elif action_type == "interrupt":
                    log.info("interrupt")
                    handler.scene.interrupt()
                elif action_type == "request_app_config":
                    log.info("request_app_config")
                    await message_queue.put(
                        {
                            "type": "app_config",
                            "data": load_config(),
                            "version": VERSION,
                        }
                    )
                else:
                    log.info("Routing to sub-handler", action_type=action_type)
                    await handler.route(data)

    # handle disconnects
    except (
        websockets.exceptions.ConnectionClosed,
        starlette.websockets.WebSocketDisconnect,
        RuntimeError,
    ):
        log.warning("frontend disconnected")
        send_messages_task.cancel()
        send_status_task.cancel()
        send_client_bootstraps_task.cancel()
        handler.disconnect()
        if handler.scene:
            handler.scene.active = False
            handler.scene.continue_scene = False
            if scene_task:
                scene_task.cancel()
