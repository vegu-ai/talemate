import asyncio
import pydantic
import structlog
from typing import TYPE_CHECKING, Any, Callable

# import talemate.agents.visual.automatic1111  # noqa: F401
# import talemate.agents.visual.comfyui  # noqa: F401
# import talemate.agents.visual.openai_image  # noqa: F401
from talemate.agents.base import (
    AgentAction,
    AgentEmission,
    set_processing,
)
import talemate.emit.async_signals as async_signals
from talemate.config import get_config
from talemate.emit import emit
from talemate.context import active_scene
from .schema import (
    GEN_TYPE,
    GenerationResponse,
    BackendStatusType,
    GenerationRequest,
    Resolution,
    FORMAT_TYPE,
    VIS_TYPE,
)
from .exceptions import ImageEditNotAvailableError, TextToImageNotAvailableError
from .backends import describe_error

if TYPE_CHECKING:
    from talemate.scene_assets import Asset
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.agents.visual.generation")

async_signals.register(
    "agent.visual.generation.before_generate",
    "agent.visual.generation.after_generate",
    "agent.visual.generation.failed",
)

# an error body can be a whole HTML page; the notification gets one short line
STATUS_REASON_LIMIT = 300


def status_reason(reason: str) -> str:
    line = next(iter(reason.strip().splitlines()), reason)
    if len(line) > STATUS_REASON_LIMIT:
        return line[: STATUS_REASON_LIMIT - 1].rstrip() + "…"
    return line


class GenerationEmission(AgentEmission):
    request: GenerationRequest
    response: GenerationResponse


class GenerationFailedEmission(AgentEmission):
    request: GenerationRequest
    error: str | None = None
    cancelled: bool = False


class RunningGeneration(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    request: GenerationRequest
    scene: Any = None


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

    async def _auto_save_generated_asset(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> "Asset | None":
        """
        Auto-save generated images as scene assets when requested via AssetAttachmentContext.
        """
        try:
            ctx = request.asset_attachment_context
            should_save = bool(ctx and ctx.save_asset)
        except Exception as e:
            # If anything goes wrong inspecting ctx, fail open (no auto-save).
            should_save = False
            log.error("auto_save_generated_asset.failed", error=str(e), request=request)

        if not should_save or not response.image_data:
            return None

        scene = active_scene.get()
        if not scene:
            return None

        try:
            asset = await scene.assets.add_asset_from_generation_response(response)
            response.saved = True
            return asset
        except Exception as e:
            log.error(
                "auto_save_generated_image.failed",
                error=str(e),
                request_id=request.id,
                vis_type=str(request.vis_type),
                character_name=request.character_name,
            )
            return None

    @property
    def running_generations(self) -> dict[str, RunningGeneration]:
        if not hasattr(self, "_running_generations"):
            self._running_generations: dict[str, RunningGeneration] = {}
        return self._running_generations

    def generations_running(self, purpose: str, scene: "Scene | None" = None) -> int:
        scene = scene or active_scene.get()
        return sum(
            1
            for running in self.running_generations.values()
            if running.scene is scene and running.request.purpose == purpose
        )

    async def _generation_failed(
        self, request: GenerationRequest, error: BaseException | None, cancelled: bool
    ):
        running = self.running_generations.pop(request.id, None)
        if running and running.scene:
            running.scene.assets.abandon_generated_backdrop(
                request.asset_attachment_context
            )
        await async_signals.get("agent.visual.generation.failed").send(
            GenerationFailedEmission(
                agent=self,
                request=request,
                error=describe_error(error) if error else None,
                cancelled=cancelled,
            )
        )

    # errors

    async def on_image_generation_error(self, error: Exception):
        reason = describe_error(error)
        emit(
            "image_generation_failed",
            websocket_passthrough=True,
            data={"error": reason},
        )
        # the status notification is where the user sees the reason
        emit(
            "status",
            f"Image generation failed: {status_reason(reason)}",
            status="error",
        )

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
        ctx = request.asset_attachment_context
        # a background meant for the story becomes the backdrop, not a message
        # image; with auto-attach off it only goes to the library
        if (
            request.vis_type == VIS_TYPE.SCENE_BACKGROUND
            and ctx.allow_auto_attach
            and get_config().appearance.scene.auto_attach_assets
        ):
            request.asset_attachment_context = ctx.model_copy(
                update={"scene_backdrop": True, "allow_auto_attach": False}
            )
        self.running_generations[request.id] = RunningGeneration(
            request=request, scene=active_scene.get()
        )
        try:
            return await self._generate(request)
        except asyncio.CancelledError:
            await self._generation_failed(request, None, cancelled=True)
            raise
        except Exception as exc:
            await self._generation_failed(request, exc, cancelled=False)
            raise

    async def _generate(self, request: GenerationRequest) -> GenerationResponse:
        await self.finalize_prompt_request(request)

        response = GenerationResponse(
            request=request,
            id=request.id,
        )

        emission = GenerationEmission(
            agent=self,
            request=request,
            response=response,
        )

        await async_signals.get("agent.visual.generation.before_generate").send(
            emission
        )

        scene = active_scene.get()
        if scene and request.asset_attachment_context.scene_backdrop:
            await scene.assets.begin_generated_backdrop(
                request.asset_attachment_context
            )

        async def on_done(fut: asyncio.Future[GenerationResponse]):
            if fut.cancelled():
                await self._generation_failed(request, None, cancelled=True)
                return
            if fut.exception():
                await self._generation_failed(request, fut.exception(), cancelled=False)
                return
            backdrop_handled = False
            try:
                response = fut.result()
                asset = await self._auto_save_generated_asset(
                    request=request, response=response
                )
                if scene and asset and request.asset_attachment_context.scene_backdrop:
                    backdrop_handled = True
                    await scene.assets.finish_generated_backdrop(
                        request.asset_attachment_context, asset.id
                    )
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
                await async_signals.get("agent.visual.generation.after_generate").send(
                    emission
                )
            finally:
                self.running_generations.pop(request.id, None)
                if scene and not backdrop_handled:
                    scene.assets.abandon_generated_backdrop(
                        request.asset_attachment_context
                    )

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
