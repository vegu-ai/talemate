import asyncio
import structlog
from typing import Awaitable, Callable

from talemate.agents.base import (
    set_processing,
)
from talemate.emit import emit
from talemate.context import active_scene
from talemate.prompts import Prompt
from talemate.prompts.response import (
    ExtractionError,
    ResponseSpec,
    StrictAnchorExtractor,
)
from .schema import (
    AnalysisResponse,
    BackendStatusType,
    AnalysisRequest,
)
from .exceptions import ImageAnalysisNotAvailableError

log = structlog.get_logger("talemate.agents.visual.analyze")

DEFAULT_ANALYSIS_PROMPT = "Describe this image in detail. (3 paragraphs max.)"

ANALYSIS_TAGS_SPEC = ResponseSpec(
    extractors={
        "analysis": StrictAnchorExtractor(left="<ANALYSIS>", right="</ANALYSIS>"),
        "tags": StrictAnchorExtractor(left="<TAGS>", right="</TAGS>"),
    },
    required=["analysis"],
)


def split_analysis_tags(text: str) -> tuple[str, list[str]]:
    """
    Reads a combined analysis response (visual/analysis-tags.jinja2) into
    the analysis and its tags. Raises ExtractionError when the analysis
    block is missing or empty. A tags block that is missing, unclosed, empty
    or not a comma separated list yields no tags.
    """
    fields = ANALYSIS_TAGS_SPEC.extract_all(text)
    if not fields["analysis"]:
        raise ExtractionError("The analysis block is empty")
    if not fields["tags"]:
        return fields["analysis"], []
    keywords = [tag.strip() for tag in fields["tags"].split(",")]
    if any("\n" in tag for tag in keywords):
        return fields["analysis"], []
    tags, seen = [], set()
    for tag in keywords:
        if tag and tag.lower() not in seen:
            tags.append(tag)
            seen.add(tag.lower())
    return fields["analysis"], tags


class AnalysisMixin:
    # helpers

    @property
    def can_analyze_images(self) -> bool:
        return (
            self.backend_image_analyzation is not None
            and self.backend_image_analyzation.status.type == BackendStatusType.OK
        )

    # errors

    async def on_image_analysis_error(self, error: Exception):
        emit(
            "image_analysis_failed",
            websocket_passthrough=True,
            data={"error": str(error)},
        )
        emit("status", "Image analysis failed.", status="error")

    @set_processing
    async def analyze(
        self, request: AnalysisRequest, await_completion: bool = False
    ) -> AnalysisResponse:
        response = AnalysisResponse(
            request=request,
            id=request.id,
        )

        async def on_done(fut: asyncio.Future[AnalysisResponse]):
            response = fut.result()
            log.debug(
                "image_analyzed",
                request=response.request.model_dump(),
                analysis=response.analysis[:100] if response.analysis else None,
            )

            # Save analysis to asset meta
            # if request.save is True
            if response.request and response.request.asset_id and response.analysis:
                scene = active_scene.get()
                if scene and response.request.asset_id in scene.assets.assets:
                    if response.request.save:
                        asset = scene.assets.get_asset(response.request.asset_id)
                        asset.meta.analysis = response.analysis
                        if response.tags:
                            asset.meta.add_tags(response.tags)
                        scene.assets.update_asset_meta(
                            response.request.asset_id, asset.meta
                        )
                        scene.saved = False
                        scene.emit_status()

            emit(
                "image_analyzed",
                websocket_passthrough=True,
                data=response.model_dump(),
            )

        await self.analyze_image(request, response, on_done, await_completion)

        return response

    async def _run_analysis(
        self, backend, request: AnalysisRequest, response: AnalysisResponse
    ) -> AnalysisResponse:
        if not request.generate_tags:
            return await backend.analyze(request, response)
        prompt = Prompt.get(
            "visual.analysis-tags", vars={"prompt": request.prompt}
        ).render()
        await backend.analyze(request.model_copy(update={"prompt": prompt}), response)
        if response.analysis:
            response.analysis, response.tags = split_analysis_tags(response.analysis)
        return response

    def _track_analysis_task(self, task: asyncio.Task, backend: object):
        """
        Track an analysis task and its backend for cancellation support.
        Automatically removes the task from tracking when it completes.
        """
        # Initialize tracking structures if needed
        if not hasattr(self, "_active_analysis_tasks"):
            self._active_analysis_tasks: set[asyncio.Task] = set()
        if not hasattr(self, "_analysis_task_backends"):
            self._analysis_task_backends: dict[asyncio.Task, object] = {}

        # Add task to tracking
        self._active_analysis_tasks.add(task)
        self._analysis_task_backends[task] = backend

        # Remove task from tracking when it completes
        def remove_task(fut):
            self._active_analysis_tasks.discard(task)
            self._analysis_task_backends.pop(task, None)

        task.add_done_callback(remove_task)

    async def analyze_image(
        self,
        request: AnalysisRequest,
        response: AnalysisResponse,
        on_done: Callable[["asyncio.Future[AnalysisResponse]"], Awaitable[None]],
        await_completion: bool = False,
    ):
        """
        Runs the analysis as a tracked background task. With
        `await_completion=True` the task and its `on_done` handling are
        awaited before returning, and the caller owns failures entirely:
        exceptions propagate instead of reaching the background error
        handler, so no `image_analysis_failed` emission or error status is
        raised. Otherwise the call returns once the task is launched.
        """
        if not self.can_analyze_images:
            raise ImageAnalysisNotAvailableError("Image analysis is not available")

        backend = self.backend_image_analyzation
        fn = getattr(
            self, f"{self.backend_image_analyzation.name}_prepare_analysis", None
        )

        if fn:
            backend = await fn(request)

        response.backend_name = backend.name

        task = asyncio.create_task(self._run_analysis(backend, request, response))

        # Track task for cancellation support
        self._track_analysis_task(task, backend)

        if await_completion:
            await task
            await on_done(task)
        else:
            task.add_done_callback(lambda fut: asyncio.create_task(on_done(fut)))
            await self.set_background_processing(task, self.on_image_analysis_error)

    async def cancel_analysis(self):
        """
        Cancel all active image analysis tasks.
        """
        if (
            not hasattr(self, "_active_analysis_tasks")
            or not self._active_analysis_tasks
        ):
            log.debug("cancel_analysis", cancelled=False, reason="no_active_tasks")
            return

        # Collect all active tasks and their backends
        active_tasks = [task for task in self._active_analysis_tasks if not task.done()]

        if not active_tasks:
            log.debug("cancel_analysis", cancelled=False, reason="no_active_tasks")
            return

        # Collect unique backends to call cancel_request on
        # Use dict with backend name/id as key to ensure uniqueness
        backends_to_cancel = {}
        for task in active_tasks:
            if hasattr(self, "_analysis_task_backends"):
                backend = self._analysis_task_backends.get(task)
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

        # Call cancel_request on all unique backends (if they support it)
        for backend in backends_to_cancel.values():
            try:
                if hasattr(backend, "cancel_request"):
                    await backend.cancel_request()
            except Exception as e:
                log.error(
                    "cancel_analysis.backend_cancel_failed",
                    error=str(e),
                    backend=backend.name if hasattr(backend, "name") else str(backend),
                )

        log.info(
            "cancel_analysis",
            cancelled=True,
            task_count=cancelled_count,
            backend_count=len(backends_to_cancel),
        )
