import asyncio
import structlog
from typing import Callable

# import talemate.agents.visual.automatic1111  # noqa: F401
# import talemate.agents.visual.comfyui  # noqa: F401
# import talemate.agents.visual.openai_image  # noqa: F401
from talemate.agents.base import (
    AgentAction,
    set_processing,
)
from talemate.emit import emit
from .schema import (
    GEN_TYPE,
    GenerationResponse,
    BackendStatusType,
    GenerationRequest,
    Resolution,
    FORMAT_TYPE,
)
from .exceptions import ImageEditNotAvailableError, TextToImageNotAvailableError

log = structlog.get_logger("talemate.agents.visual.generation")


class GenerationMixin:
    # helpers

    @property
    def can_edit_images(self) -> bool:
        return (
            self.backend_image_edit is not None
            and self.backend_image_edit.status.type == BackendStatusType.OK
        )

    @property
    def can_generate_images(self) -> bool:
        return (
            self.backend is not None
            and self.backend.status.type == BackendStatusType.OK
        )

    def resolution(self, format: FORMAT_TYPE, action: AgentAction) -> Resolution:
        if format == FORMAT_TYPE.LANDSCAPE:
            w, h = action.config["resolution_landscape"].value
            return Resolution(width=w, height=h)
        elif format == FORMAT_TYPE.PORTRAIT:
            w, h = action.config["resolution_portrait"].value
            return Resolution(width=w, height=h)
        w, h = action.config["resolution_square"].value
        return Resolution(width=w, height=h)

    # errors

    async def on_image_generation_error(self, error: Exception):
        emit(
            "image_generation_failed",
            websocket_passthrough=True,
            data={"error": str(error)},
        )
        emit("status", "Image generation failed.", status="error")

    def _track_generation_task(self, task: asyncio.Task, backend: object):
        """
        Track a generation task and its backend for cancellation support.
        Automatically removes the task from tracking when it completes.
        """
        # Initialize tracking structures if needed
        if not hasattr(self, "_active_generation_tasks"):
            self._active_generation_tasks: set[asyncio.Task] = set()
        if not hasattr(self, "_generation_task_backends"):
            self._generation_task_backends: dict[asyncio.Task, object] = {}

        # Add task to tracking
        self._active_generation_tasks.add(task)
        self._generation_task_backends[task] = backend

        # Remove task from tracking when it completes
        def remove_task(fut):
            self._active_generation_tasks.discard(task)
            self._generation_task_backends.pop(task, None)

        task.add_done_callback(remove_task)

    @set_processing
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        response = GenerationResponse(
            request=request,
            id=request.id,
        )

        async def on_done(fut: asyncio.Future[GenerationResponse]):
            response = fut.result()
            log.debug(
                "image_generated",
                request=response.request.model_dump(exclude={"inline_reference"}),
                base64=response.base64[:100] if response.base64 else None,
            )
            emit(
                "image_generated",
                websocket_passthrough=True,
                data=response.model_dump(),
            )
            if request.callback:
                await request.callback(response=response)

        # if reference images are provided we route to image edit
        # otherwise we route to text to image
        if request.gen_type == GEN_TYPE.IMAGE_EDIT:
            await self.generate_image_edit(request, response, on_done)
        else:
            await self.generate_text_to_image(request, response, on_done)

        return response

    async def generate_text_to_image(
        self,
        request: GenerationRequest,
        response: GenerationResponse,
        on_done: Callable[[GenerationResponse], None],
    ):
        if not self.can_generate_images:
            raise TextToImageNotAvailableError("Text to image is not available")

        backend = self.backend
        fn = getattr(self, f"{self.backend.name}_prepare_generation", None)
        if fn:
            backend = await fn(request)

        response.backend_name = backend.name

        task = asyncio.create_task(backend.generate(request, response))
        task.add_done_callback(lambda fut: asyncio.create_task(on_done(fut)))

        # Track task for cancellation support
        self._track_generation_task(task, backend)

        await self.set_background_processing(task, self.on_image_generation_error)

    async def generate_image_edit(
        self,
        request: GenerationRequest,
        response: GenerationResponse,
        on_done: Callable[[GenerationResponse], None],
    ):
        if not self.can_edit_images:
            raise ImageEditNotAvailableError("Image edit is not available")

        backend = self.backend_image_edit
        fn = getattr(self, f"{self.backend_image_edit.name}_prepare_generation", None)

        if fn:
            backend = await fn(request)

        response.backend_name = backend.name

        task = asyncio.create_task(backend.generate(request, response))
        task.add_done_callback(lambda fut: asyncio.create_task(on_done(fut)))

        # Track task for cancellation support
        self._track_generation_task(task, backend)

        await self.set_background_processing(task, self.on_image_generation_error)

    async def cancel_generation(self):
        """
        Cancel all active image generation tasks.
        """
        if (
            not hasattr(self, "_active_generation_tasks")
            or not self._active_generation_tasks
        ):
            log.debug("cancel_generation", cancelled=False, reason="no_active_tasks")
            return

        # Collect all active tasks and their backends
        active_tasks = [
            task for task in self._active_generation_tasks if not task.done()
        ]

        if not active_tasks:
            log.debug("cancel_generation", cancelled=False, reason="no_active_tasks")
            return

        # Collect unique backends to call cancel_request on
        # Use dict with backend name/id as key to ensure uniqueness
        backends_to_cancel = {}
        for task in active_tasks:
            if hasattr(self, "_generation_task_backends"):
                backend = self._generation_task_backends.get(task)
                if backend:
                    # Use backend name as key for uniqueness
                    backend_key = getattr(backend, "name", id(backend))
                    backends_to_cancel[backend_key] = backend

        # Cancel all tasks
        cancelled_count = 0
        for task in active_tasks:
            if not task.done():
                task.cancel()
                cancelled_count += 1

        # Call cancel_request on all unique backends
        for backend in backends_to_cancel.values():
            try:
                await backend.cancel_request()
            except Exception as e:
                log.error(
                    "cancel_generation.backend_cancel_failed",
                    error=str(e),
                    backend=backend.name if hasattr(backend, "name") else str(backend),
                )

        log.info(
            "cancel_generation",
            cancelled=True,
            task_count=cancelled_count,
            backend_count=len(backends_to_cancel),
        )
