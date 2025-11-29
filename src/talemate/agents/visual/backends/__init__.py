import asyncio
import pydantic
import structlog
import random
from typing import ClassVar
import time
from talemate.instance import get_agent
from talemate.agents.visual.schema import (
    BackendBase,
    BackendStatus,
    BackendStatusType,
    GenerationRequest,
    GenerationResponse,
    AnalysisRequest,
    AnalysisResponse,
)

__all__ = [
    "BACKENDS",
    "Backend",
    "BackendStatus",
    "BackendStatusType",
    "register",
    "NONE_BACKEND",
]

log = structlog.get_logger("talemate.agents.visual.backends")

BACKENDS = {}

NONE_BACKEND = {
    "value": "",
    "label": "- None -",
}


class Backend(BackendBase):
    _test_conn_task: asyncio.Task | None = pydantic.PrivateAttr(default=None)
    _test_conn_lock: asyncio.Lock = pydantic.PrivateAttr(default_factory=asyncio.Lock)
    _test_conn_cache: ClassVar[dict[str, BackendStatus]] = {}
    _test_conn_cache_maxage: ClassVar[int] = 1
    _test_conn_cache_data: ClassVar[dict[str, dict]] = {}

    @property
    def instance_label(self) -> str:
        return self.label

    @property
    def generator_label(self) -> str | None:
        return None

    @property
    def status_color(self) -> str:
        if self.status.type == BackendStatusType.ERROR:
            return "error"
        elif self.status.type == BackendStatusType.DISCONNECTED:
            return "muted"
        elif self.status.type == BackendStatusType.WARNING:
            return "warning"
        else:
            return "success"

    @property
    def max_references(self) -> int:
        return 0

    @property
    def status_description(self) -> str:
        if self.status.type == BackendStatusType.ERROR:
            return self.status.message
        elif self.status.type == BackendStatusType.DISCONNECTED:
            return "Disconnected"
        elif self.status.type == BackendStatusType.WARNING:
            return f"Connected to {self.instance_label} - {self.status.message}"
        else:
            return f"Connected to {self.instance_label}"

    @classmethod
    def as_choice(cls) -> dict[str, str]:
        return {
            "value": cls.name,
            "label": cls.label,
        }

    @property
    def status_cache_key(self) -> str:
        return f"{self.name}-{self.instance_label}"

    async def on_status_change(self):
        visual_agent = get_agent("visual")
        log.debug(
            "Backend.on_status_change",
            backend=self.name,
            instance_label=self.instance_label,
        )
        await visual_agent.emit_status()

    def _update_status_from_future(self, fut: asyncio.Future):
        current_status = self.status
        try:
            result = fut.result()
        except Exception as e:
            self.status = BackendStatus(
                type=BackendStatusType.ERROR,
                message=str(e),
            )
        else:
            self.status = result
        self._test_conn_cache[self.status_cache_key] = self.status

        if current_status and current_status != self.status:
            asyncio.create_task(self.on_status_change())

    async def ensure_test_connection_task(self) -> asyncio.Task:
        """Create the test_connection task once and attach a status-updating callback.

        Non-blocking; returns the in-flight or newly created task.
        """
        async with self._test_conn_lock:
            if not self._test_conn_task or self._test_conn_task.done():
                task = asyncio.create_task(self._test_connection())
                task.add_done_callback(self._update_status_from_future)
                self._test_conn_task = task
            return self._test_conn_task

    async def ready(self) -> BackendStatus:
        raise NotImplementedError("ready not implemented")

    def _get_cache_data(self) -> dict:
        """Override this method to return data that should be cached after successful test_connection.

        Returns a dict of data to cache. The dict will be stored and can be retrieved
        by other backend instances sharing the same cache key.
        """
        return {}

    def _apply_cache_data(self, data: dict):
        """Override this method to apply cached data to this backend instance.

        Called when using cached status to restore any additional data that was
        cached from a previous test_connection call.
        """
        pass

    async def _test_connection(self) -> BackendStatus:
        # sleep random
        await asyncio.sleep(random.uniform(0.2, 0.5))

        cache = self._test_conn_cache.get(self.status_cache_key)
        if cache and time.time() - cache.timestamp < self._test_conn_cache_maxage:
            # log.debug("Using cached test connection status", backend=self.name, instance_label=self.instance_label)
            # Apply any cached data
            cached_data = self._test_conn_cache_data.get(self.status_cache_key)
            if cached_data:
                self._apply_cache_data(cached_data)
            return cache

        # log.debug("Testing connection to backend", backend=self.name, instance_label=self.instance_label)
        status = await self.test_connection()

        # Store cache data if test_connection was successful
        if status.type == BackendStatusType.OK:
            cache_data = self._get_cache_data()
            if cache_data:
                self._test_conn_cache_data[self.status_cache_key] = cache_data

        return status

    async def test_connection(self, timeout: int = 2) -> BackendStatus:
        raise NotImplementedError("test_connection not implemented")

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        raise NotImplementedError("generate not implemented")

    async def analyze(
        self, request: AnalysisRequest, response: AnalysisResponse
    ) -> AnalysisResponse:
        raise NotImplementedError("analyze not implemented")

    async def cancel_request(self):
        """
        Cancel the current generation request.
        By default, this does nothing. Backends can override this method
        to implement cancellation logic.
        """
        pass


def register(backend: type[Backend]) -> type[Backend]:
    if backend.name in BACKENDS:
        raise ValueError(f"Backend {backend.name} already registered")
    BACKENDS[backend.name] = backend
    return backend
