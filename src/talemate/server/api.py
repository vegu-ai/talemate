import asyncio
import json
import traceback

import structlog
import websockets

import talemate.instance as instance
from talemate.client.base import (
    resolve_all_generation_errors,
    resolve_generation_error,
)
from talemate.config import get_config, commit_config
from talemate.server.config import app_config_message
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
WEBSOCKET_DISCONNECT_EXCEPTIONS = (
    websockets.exceptions.ConnectionClosed,
    RuntimeError,
)
CONNECTION_TASK_DRAIN_TIMEOUT = 1.0


def _is_task_failure(result):
    return isinstance(result, BaseException) and not isinstance(
        result, asyncio.CancelledError
    )


def get_active_frontend_handler():
    return _active_frontend_websocket_handler


async def send_queued_frames(websocket, message_queue: asyncio.Queue) -> Exception:
    """Send the queued frames in order until the socket closes; return the
    exception that closed it."""
    while True:
        # check if there are messages in the queue
        if message_queue.empty():
            await asyncio.sleep(0.01)
            continue

        message = await message_queue.get()
        try:
            payload = json.dumps(message, cls=JSONEncoder)
            await websocket.send(payload)
        except WEBSOCKET_DISCONNECT_EXCEPTIONS as exc:
            return exc
        finally:
            # WebsocketHandler.flush joins the queue
            message_queue.task_done()


async def client_status_loop(interval: float = 3.0):
    """Emit client and agent status while a frontend is connected."""
    steps = (instance.emit_clients_status, instance.agent_ready_checks, commit_config)
    # a step that keeps failing must neither end the loop - this connection
    # would get no further client or agent status until the page is reloaded -
    # nor starve the steps after it, since commit_config() runs last and a
    # settings change that never reaches disk is lost without a trace
    last_errors: dict[str, str] = {}
    while True:
        for step in steps:
            try:
                await step()
            except Exception:
                error = traceback.format_exc()
                if last_errors.get(step.__name__) == error:
                    log.debug("client status loop", step=step.__name__)
                else:
                    last_errors[step.__name__] = error
                    log.error("client status loop", step=step.__name__, error=error)
            else:
                last_errors.pop(step.__name__, None)
        await asyncio.sleep(interval)


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
    disconnect_exc = None

    log.info("frontend connected")

    import_initial_node_definitions()

    async def frontend_disconnect(exc):
        global _active_frontend_websocket
        global _active_frontend_websocket_handler
        nonlocal scene_task
        log.warning(f"frontend disconnected: {exc}")

        # no user response can arrive anymore - terminate any coroutine still
        # waiting on a generation error dialog
        resolve_all_generation_errors("cancel")
        if scene_task:
            scene_task.cancel()
        try:
            handler.disconnect()
        finally:
            # Clear the active websocket reference so a new frontend can connect.
            if _active_frontend_websocket is websocket:
                _active_frontend_websocket = None
            if _active_frontend_websocket_handler is handler:
                _active_frontend_websocket_handler = None

    # Create a task to send messages from the queue
    async def send_messages():
        nonlocal disconnect_exc
        disconnect_exc = await send_queued_frames(websocket, message_queue)

    # task to test connection
    async def test_connection():
        nonlocal disconnect_exc
        while True:
            try:
                await websocket.send(json.dumps({"type": "ping"}))
            except WEBSOCKET_DISCONNECT_EXCEPTIONS as exc:
                disconnect_exc = exc
                return
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

                    # pending error dialogs belong to the outgoing scene's
                    # generations - cancel them so their coroutines don't hang
                    resolve_all_generation_errors("cancel")

                    file_path = data.get("file_path")
                    scene_data = data.get("scene_data")
                    filename = data.get("filename")
                    reset = data.get("reset", False)
                    scene_initialization = data.get("scene_initialization")

                    await message_queue.put(
                        {
                            "type": "system",
                            "id": "scene.loading",
                            "request_id": data.get("request_id"),
                            "status": "loading",
                        }
                    )

                    async def scene_loading_done():
                        await message_queue.put(
                            {
                                "type": "system",
                                "id": "scene.loaded",
                                "request_id": data.get("request_id"),
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
                            scene_initialization=scene_initialization,
                            request_id=data.get("request_id"),
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
                elif action_type == "request_scenes_tree":
                    handler.request_scenes_tree()
                elif action_type == "request_client_status":
                    await handler.request_client_status()
                elif action_type == "request_scene_assets":
                    log.debug("request_scene_assets", data=data)
                    handler.request_scene_assets(data.get("asset_ids"))
                elif action_type == "request_file_image_data":
                    log.info("request_file_image_data", data=data)
                    handler.request_file_image_data(
                        data.get("file_path"), data.get("request_id")
                    )
                elif action_type == "upload_scene_asset":
                    log.info("upload_scene_asset")
                    await handler.add_scene_asset(data=data)
                elif action_type == "request_scene_history":
                    log.info("request_scene_history")
                    handler.request_scene_history()
                elif action_type == "request_assets":
                    log.info("request_assets")
                    handler.request_assets(data.get("assets"))
                elif action_type == "generation_error_response":
                    request_id = data.get("request_id")
                    action = data.get("action")
                    log.info(
                        "generation_error_response",
                        request_id=request_id,
                        action=action,
                    )
                    if request_id and action:
                        resolve_generation_error(request_id, action)
                elif action_type == "interrupt":
                    log.info("interrupt")
                    handler.scene.interrupt()
                    if handler.scene.loading:
                        scene_task.cancel()
                        scene_task = None
                elif action_type == "auto_retry_abort":
                    client_name = data.get("client")
                    generation_id = data.get("generation_id")
                    log.info(
                        "auto_retry_abort",
                        client=client_name,
                        generation_id=generation_id,
                    )
                    if generation_id:
                        try:
                            instance.get_client(client_name).request_auto_retry_abort(
                                generation_id
                            )
                        except KeyError:
                            pass
                elif action_type == "request_app_config":
                    log.info("request_app_config")

                    await message_queue.put(app_config_message(get_config()))
                else:
                    log.info("Routing to sub-handler", action_type=action_type)
                    await handler.route(data)

        except WEBSOCKET_DISCONNECT_EXCEPTIONS:
            raise

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
        nonlocal disconnect_exc
        try:
            while True:
                data = await websocket.recv()
                data = json.loads(data)
                await process_message(data)

        # handle disconnects
        except WEBSOCKET_DISCONNECT_EXCEPTIONS as exc:
            disconnect_exc = exc

    main_task = asyncio.create_task(handle_messages())
    send_messages_task = asyncio.create_task(send_messages())
    send_status_task = asyncio.create_task(client_status_loop())
    test_connection_task = asyncio.create_task(test_connection())

    connection_tasks = (
        main_task,
        send_messages_task,
        send_status_task,
        test_connection_task,
    )
    try:
        # Each task owns one connection-lifetime loop, so any return starts
        # teardown for the complete set.
        await asyncio.wait(connection_tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in connection_tasks:
            if not task.done():
                task.cancel()

        # Cancellation handlers can wait for scene release, which happens in
        # frontend_disconnect. Bound this first drain so they cannot keep the
        # active connection slot forever.
        done, _ = await asyncio.wait(
            connection_tasks,
            timeout=CONNECTION_TASK_DRAIN_TIMEOUT,
        )
        drained_results = await asyncio.gather(*done, return_exceptions=True)
        cleanup_exc = disconnect_exc or next(
            (result for result in drained_results if _is_task_failure(result)),
            None,
        )
        await frontend_disconnect(cleanup_exc)
        results = await asyncio.gather(*connection_tasks, return_exceptions=True)

    for result in results:
        if _is_task_failure(result):
            raise result
