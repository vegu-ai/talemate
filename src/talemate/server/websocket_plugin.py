import structlog
from typing import TYPE_CHECKING, Callable
from talemate.emit import emit
from talemate.exceptions import GenerationCancelled
import traceback
import pydantic
import asyncio

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "Plugin",
    "EmitStatusMessage",
]

log = structlog.get_logger("talemate.server.visual")


class EmitStatusMessage(pydantic.BaseModel):
    message: str
    status: str = "success"
    as_scene_message: bool = False


class Plugin:
    router: str = "router"

    @property
    def scene(self) -> "Scene | None":
        return self.websocket_handler.scene

    def __init__(self, websocket_handler):
        self.websocket_handler = websocket_handler
        self.connect()

    def connect(self):
        pass

    def disconnect(self):
        pass

    @classmethod
    def register_sub_handler(cls, action: str, fn: Callable):
        if not hasattr(cls, "sub_handlers"):
            cls.sub_handlers = {}
        cls.sub_handlers[action] = fn

    @classmethod
    def clear_sub_handlers(cls):
        if hasattr(cls, "sub_handlers"):
            cls.sub_handlers = {}

    async def signal_operation_failed(
        self,
        message: str,
        emit_status: bool = True,
        request_id: str | None = None,
        failed_action: str | None = None,
        extra: dict | None = None,
    ):
        payload = {
            "type": self.router,
            "action": "operation_done",
            "error": {"message": message},
        }
        # a router is shared by every sender on it - carry back what failed so
        # a client can tell its own refused request apart from somebody else's
        if request_id is not None:
            payload["request_id"] = request_id
        if failed_action is not None:
            payload["failed_action"] = failed_action
        if extra:
            payload.update(extra)
        self.websocket_handler.queue_put(payload)
        if emit_status:
            emit("status", message=message, status="error")

    async def signal_operation_done(
        self,
        signal_only: bool = False,
        allow_auto_save: bool = True,
        emit_status_message: EmitStatusMessage | str | dict = None,
        request_id: str | None = None,
    ):
        payload = {"type": self.router, "action": "operation_done", "data": {}}
        # same reason as signal_operation_failed: a router is shared by every
        # sender on it, so a completion has to say whose request it answers
        if request_id is not None:
            payload["request_id"] = request_id
        self.websocket_handler.queue_put(payload)

        if emit_status_message:
            if isinstance(emit_status_message, str):
                emit_status_message = EmitStatusMessage(message=emit_status_message)
            elif isinstance(emit_status_message, dict):
                emit_status_message = EmitStatusMessage(**emit_status_message)
            emit(
                "status",
                message=emit_status_message.message,
                status=emit_status_message.status,
                data={"as_scene_message": emit_status_message.as_scene_message},
            )

        if signal_only:
            return

        if self.scene.auto_save and allow_auto_save:
            await self.scene.save(auto=True)
        else:
            self.scene.saved = False
            self.scene.emit_status()

    def create_task_done_callback(
        self,
        success_action: str,
        failure_action: str,
        error_log_message: str,
        failure_message_key: str = "message",
    ):
        """
        Create a callback function for async task completion.

        Args:
            success_action: Action name to send on successful completion
            failure_action: Action name to send on failure
            error_log_message: Log message to use when logging errors
            failure_message_key: Key name for the error message in the failure payload
        """

        def on_done(task: asyncio.Task):
            try:
                task.result()
                self.websocket_handler.queue_put(
                    {"type": self.router, "action": success_action}
                )
            except GenerationCancelled:
                log.warning(error_log_message, cancelled=True)
                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": failure_action,
                        failure_message_key: "Generation cancelled",
                    }
                )
            except Exception as e:
                log.error(error_log_message, error=traceback.format_exc())
                self.websocket_handler.queue_put(
                    {
                        "type": self.router,
                        "action": failure_action,
                        failure_message_key: str(e),
                    }
                )

        return on_done

    def _on_background_task_done(self, task: asyncio.Task) -> None:
        """
        Done-callback for handlers decorated with @background_task. Posts an
        operation_done envelope on the router for the cancel and error paths
        so the frontend's per-component busy state clears even when the
        handler bailed before reaching its trailing signal_operation_done().

        - Success: the handler's own signal_operation_done() already ran,
          nothing to do here.
        - Cancel (GenerationCancelled): post a bare operation_done envelope.
        - Error: post operation_done with an error envelope. set_loading
          already emitted the "Failed" status snackbar (set_error=True), so
          we skip the duplicate emit here.

        Implemented as direct queue_put rather than scheduling another task
        so we don't orphan a follow-up coroutine inside a done-callback.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            # Success — handler called signal_operation_done() itself.
            return
        if isinstance(exc, GenerationCancelled):
            self.websocket_handler.queue_put(
                {"type": self.router, "action": "operation_done", "data": {}}
            )
            return
        # Real exception — error envelope.
        self.websocket_handler.queue_put(
            {
                "type": self.router,
                "action": "operation_done",
                "error": {"message": str(exc)},
            }
        )

    async def handle(self, data: dict):
        action: str = data.get("action")
        log.info(f"{self.router} action", action=action)
        fn = getattr(self, f"handle_{action}", None)

        if self.scene and self.scene.cancel_requested:
            # Terrible way to reset the cancel_requested flag, but it's the only way to avoid double generation cancellation with the current implementation
            # TODO: Fix this
            self.scene.cancel_requested = False

        if fn is None:
            sub_handlers = getattr(self, "sub_handlers", {})
            sub_handler_fn = sub_handlers.get(action)
            if sub_handler_fn:
                log.info(f"{self.router} sub-handler", action=action)
                await sub_handler_fn(self, data)
                return

            return

        try:
            result = await fn(data)
        except Exception as e:
            action_name = data.get("action")
            log.error(
                "Error handling action",
                action=action_name,
                error=e,
                traceback=traceback.format_exc(),
            )
            await self.signal_operation_failed(
                f"Error during {action_name}: {e}",
                request_id=data.get("request_id"),
                failed_action=action_name,
            )
            return

        # Handlers decorated with @background_task return a Task. Attach a
        # done-callback so cancellations and synchronous failures inside the
        # task body (e.g. pydantic validation, missing-character lookups)
        # still post an operation_done envelope on the router and the
        # frontend can clear any local busy state it set when sending the
        # request.
        if isinstance(result, asyncio.Task):
            result.add_done_callback(self._on_background_task_done)
