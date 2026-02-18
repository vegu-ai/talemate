import structlog
from typing import ClassVar

import talemate.instance as instance
import talemate.agents.visual.backends as backends
from talemate.agents.visual.schema import (
    AnalysisRequest,
    AnalysisResponse,
)
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionConditional,
)

log = structlog.get_logger("talemate.agents.visual.talemate_client")

BACKEND_NAME = "talemate_client"


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "Talemate Client"
    image_create = False
    image_edit = False
    image_analyzation = True
    description = "Analyze images using any vision-capable Talemate LLM client."

    client_name: str | None = None

    _test_conn_cache_maxage: ClassVar[int] = 5

    @property
    def instance_label(self) -> str:
        return self.client_name or "No client"

    @property
    def generator_label(self) -> str | None:
        if not self.client_name:
            return None
        try:
            client = instance.get_client(self.client_name)
            return f"{self.client_name} ({client.model_name})"
        except KeyError:
            return self.client_name

    @property
    def status_cache_key(self) -> str:
        return f"{self.name}-{self.client_name or 'none'}"

    def _get_vision_client(self):
        """Retrieve the configured Talemate client and validate vision support."""
        if not self.client_name:
            raise ValueError("No Talemate client selected for vision analysis")

        client = instance.get_client(self.client_name)

        if not client.supports_vision:
            raise ValueError(
                f"Client '{self.client_name}' does not support vision "
                f"(capable={client.vision_capable}, enabled={client.vision_enabled})"
            )

        if not client.enabled:
            raise ValueError(f"Client '{self.client_name}' is disabled")

        if not client.connected:
            raise ValueError(f"Client '{self.client_name}' is not connected")

        return client

    async def ready(self) -> backends.BackendStatus:
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        if not self.client_name:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message="No client selected",
            )

        try:
            client = instance.get_client(self.client_name)
        except KeyError:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message=f"Client '{self.client_name}' not found",
            )

        if not client.enabled:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message=f"Client '{self.client_name}' is disabled",
            )

        if not client.connected:
            return backends.BackendStatus(
                type=backends.BackendStatusType.DISCONNECTED,
                message=f"Client '{self.client_name}' is not connected",
            )

        if not client.supports_vision:
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR,
                message=f"Client '{self.client_name}' vision not enabled",
            )

        return backends.BackendStatus(type=backends.BackendStatusType.OK)

    async def analyze(
        self, request: AnalysisRequest, response: AnalysisResponse
    ) -> AnalysisResponse:
        client = self._get_vision_client()

        refs = list(request.reference_bytes or [])
        if not refs or not refs[0]:
            raise ValueError("Image analysis requires at least one reference image")

        image_bytes = refs[0]

        log.debug(
            "talemate_client.analyze",
            client_name=self.client_name,
            model=client.model_name,
            prompt=request.prompt[:100],
        )

        try:
            analysis_text = await client.analyze_image(image_bytes, request.prompt)
            response.analysis = analysis_text
            return response
        except Exception as e:
            log.error("talemate_client.analyze.error", error=str(e))
            raise


class TalemateClientMixin:
    """Mixin for VisualAgent to support the Talemate Client analysis backend."""

    @classmethod
    def _get_vision_client_choices(cls) -> list[dict]:
        """Build choices list of vision-capable+enabled clients."""
        choices = []
        for name, client in instance.client_instances():
            if client.supports_vision:
                choices.append(
                    {
                        "label": f"{name} ({client.model_name or 'no model'})",
                        "value": name,
                    }
                )
        return choices

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["talemate_client_image_analyzation"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-search",
            label="Talemate Client",
            subtitle="Image analysis",
            description="Analyze images using any vision-capable Talemate LLM client.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_analyzation",
                value=BACKEND_NAME,
            ),
            config={
                "client": AgentActionConfig(
                    type="text",
                    value="",
                    choices=[],
                    label="Client",
                    description=(
                        "Select which Talemate client to use for image analysis. "
                        "Only clients with vision enabled are shown. If no clients "
                        "appear, ensure you have enabled vision in the client's "
                        "settings (Vision tab) for a client with a vision-capable model."
                    ),
                    save_on_change=True,
                ),
            },
        )

    async def talemate_client_backend_image_analyzation(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend:
        """
        Instantiate or update the talemate_client analysis backend.
        """
        backend = self.backend_image_analyzation
        backend_instance_exists = isinstance(backend, Backend)
        action_config = self.actions["talemate_client_image_analyzation"].config
        client_name = action_config["client"].value or None

        _reinit = force or not backend_instance_exists

        if _reinit:
            return Backend(client_name=client_name)

        backend.client_name = client_name
        return backend

    async def talemate_client_prepare_analysis(
        self, request: AnalysisRequest
    ) -> Backend:
        return self.backend_image_analyzation

    async def talemate_client_emit_status(self, processing: bool = None):
        """Update client choices when status is emitted."""
        action = self.actions.get("talemate_client_image_analyzation")
        if not action or "client" not in action.config:
            return

        choices = TalemateClientMixin._get_vision_client_choices()
        action.config["client"].choices = choices
