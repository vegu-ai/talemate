import asyncio
import json
import traceback

import starlette.websockets
import structlog
import websockets

import talemate.instance as instance
from talemate import VERSION
from talemate.config import get_config, Config, commit_config, update_config
from talemate.client.system_prompts import RENDER_CACHE as SYSTEM_PROMPTS_CACHE
from talemate.server.websocket_server import WebsocketHandler
from talemate.util.data import JSONEncoder
from talemate.context import ActiveScene, Interaction
from talemate.game.engine.nodes.registry import import_initial_node_definitions


log = structlog.get_logger("talemate")

# Only one active frontend websocket is allowed at a time.
# We keep a reference to the active websocket here and reject subsequent
# connection attempts while it is still open.
_active_frontend_websocket = None
_active_frontend_websocket_handler = None


def get_active_frontend_handler():
    return _active_frontend_websocket_handler


async def websocket_endpoint(websocket):
    global _active_frontend_websocket
    global _active_frontend_websocket_handler

    # Reject the connection if another frontend is already connected.
    if _active_frontend_websocket is not None:
        try:
            await websocket.send(
                json.dumps(
                    {
                        "type": "system",
                        "status": "error",
                        "message": "Another Talemate frontend is already connected. Only one connection is allowed.",
                    }
                )
            )
        finally:
            # Close the websocket with a normal closure code.
            await websocket.close()
        return

    # Mark this websocket as the active frontend connection.
    _active_frontend_websocket = websocket
    # Create a queue for outgoing messages
    message_queue = asyncio.Queue()
    handler = WebsocketHandler(websocket, message_queue)
    _active_frontend_websocket_handler = handler
    scene_task = None

    log.info("frontend connected")

    import_initial_node_definitions()

    async def frontend_disconnect(exc):
        global _active_frontend_websocket
        global _active_frontend_websocket_handler
        nonlocal scene_task
        log.warning(f"frontend disconnected: {exc}")

        main_task.cancel()
        send_messages_task.cancel()
        send_status_task.cancel()
        test_connection_task.cancel()
        handler.disconnect()
        if handler.scene:
            handler.scene.active = False
            handler.scene.continue_scene = False
            if scene_task:
                scene_task.cancel()
        # Clear the active websocket reference so a new frontend can connect.
        if _active_frontend_websocket is websocket:
            _active_frontend_websocket = None
        if _active_frontend_websocket_handler is handler:
            _active_frontend_websocket_handler = None

    # Create a task to send messages from the queue
    async def send_messages():
        while True:
            # check if there are messages in the queue
            if message_queue.empty():
                await asyncio.sleep(0.01)
                continue

            message = await message_queue.get()
            await websocket.send(json.dumps(message, cls=JSONEncoder))

    # Create a task to send regular client status updates
    async def send_status():
        while True:
            await instance.emit_clients_status()
            await instance.agent_ready_checks()
            await commit_config()
            await asyncio.sleep(3)

    # task to test connection
    async def test_connection():
        while True:
            try:
                await websocket.send(json.dumps({"type": "ping"}))
            except Exception as e:
                await frontend_disconnect(e)
            await asyncio.sleep(1)

    # process a message from the frontend
    async def process_message(data: dict):
        nonlocal scene_task
        try:
            action_type = data.get("type")

            scene_data = None

            log.debug("frontend message", action_type=action_type)

            with ActiveScene(handler.scene):
                if action_type == "load_scene":
                    if scene_task:
                        log.info("Unloading current scene")
                        handler.scene.continue_scene = False
                        scene_task.cancel()

                    file_path = data.get("file_path")
                    scene_data = data.get("scene_data")
                    filename = data.get("filename")
                    reset = data.get("reset", False)
                    rev = data.get("rev")
                    scene_initialization = data.get("scene_initialization")

                    await message_queue.put(
                        {
                            "type": "system",
                            "id": "scene.loading",
                            "status": "loading",
                        }
                    )

                    async def scene_loading_done():
                        await message_queue.put(
                            {
                                "type": "system",
                                "id": "scene.loaded",
                                "status": "success",
                                "data": {
                                    "hidden": True,
                                    "environment": handler.scene.environment,
                                },
                            }
                        )
                        instance.emit_agents_status()

                    if scene_data and filename:
                        file_path = handler.handle_character_card_upload(
                            scene_data, filename
                        )

                    log.info("load_scene", file_path=file_path, reset=reset)

                    # Create a task to load the scene in the background
                    scene_task = asyncio.create_task(
                        handler.load_scene(
                            file_path,
                            reset=reset,
                            callback=scene_loading_done,
                            rev=rev,
                            scene_initialization=scene_initialization,
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
                    list_images = data.get("list_images", True)
                    handler.request_scenes_list(query, list_images)
                elif action_type == "configure_clients":
                    await update_config({"clients": data.get("clients")})
                    await instance.instantiate_clients()
                    await instance.purge_clients()
                    await instance.emit_clients_status(wait_for_status=True)
                    await instance.ensure_agent_llm_client()
                elif action_type == "configure_agents":
                    await update_config({"agents": data.get("agents")})
                    await instance.configure_agents()
                elif action_type == "request_client_status":
                    await handler.request_client_status()
                elif action_type == "delete_message":
                    handler.delete_message(data.get("id"))
                elif action_type == "request_scene_assets":
                    log.debug("request_scene_assets", data=data)
                    handler.request_scene_assets(data.get("asset_ids"))
                elif action_type == "request_file_image_data":
                    log.info("request_file_image_data", data=data)
                    handler.request_file_image_data(data.get("file_path"))
                elif action_type == "upload_scene_asset":
                    log.info("upload_scene_asset")
                    await handler.add_scene_asset(data=data)
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
                    if handler.scene.loading:
                        scene_task.cancel()
                        scene_task = None
                elif action_type == "request_app_config":
                    log.info("request_app_config")

                    config: Config = get_config().model_dump()
                    config.update(system_prompt_defaults=SYSTEM_PROMPTS_CACHE)

                    await message_queue.put(
                        {
                            "type": "app_config",
                            "data": config,
                            "version": VERSION,
                        }
                    )
                else:
                    log.info("Routing to sub-handler", action_type=action_type)
                    await handler.route(data)

        except (
            websockets.exceptions.ConnectionClosed,
            starlette.websockets.WebSocketDisconnect,
            RuntimeError,
        ) as exc:
            raise exc

        except Exception as e:
            log.error("Unhandled error", error=e, traceback=traceback.format_exc())
            await message_queue.put(
                {
                    "type": "status",
                    "status": "error",
                    "message": f"Unhandled error: {e}",
                }
            )

    # main loop task
    async def handle_messages():
        try:
            while True:
                data = await websocket.recv()
                data = json.loads(data)
                await process_message(data)

        # handle disconnects
        except (
            websockets.exceptions.ConnectionClosed,
            starlette.websockets.WebSocketDisconnect,
            RuntimeError,
        ) as exc:
            await frontend_disconnect(exc)

    main_task = asyncio.create_task(handle_messages())
    send_messages_task = asyncio.create_task(send_messages())
    send_status_task = asyncio.create_task(send_status())
    test_connection_task = asyncio.create_task(test_connection())

    await asyncio.gather(
        main_task,
        send_messages_task,
        send_status_task,
        test_connection_task,
    )
