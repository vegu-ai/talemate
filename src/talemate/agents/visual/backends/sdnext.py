import base64
import httpx
import structlog

from talemate.instance import get_agent
from talemate.agents.base import AgentAction, AgentActionConfig, AgentActionConditional
import talemate.agents.visual.backends as backends
from talemate.agents.visual.schema import (
    GenerationRequest,
    GenerationResponse,
    GEN_TYPE,
    PROMPT_TYPE,
    Resolution,
)


log = structlog.get_logger("talemate.agents.visual.sdnext")


BACKEND_NAME = "sdnext"

## Removed schedule options – not present in SD.Next OpenAPI


@backends.register
class Backend(backends.Backend):
    name = BACKEND_NAME
    label = "SD.Next"
    image_create = True
    image_edit = True
    image_analyzation = False
    description = "Stable Diffusion Next text/image backend via SD.Next API."

    api_url: str
    username: str | None = None
    password: str | None = None

    @property
    def max_references(self) -> int:
        # Minimal edit support: one reference image
        return 1 if self.gen_type == GEN_TYPE.IMAGE_EDIT else 0

    @property
    def instance_label(self) -> str:
        return self.api_url

    @property
    def generate_timeout(self) -> int:
        return get_agent("visual").generate_timeout

    def _get_auth(self) -> httpx.BasicAuth | None:
        """Get basic auth credentials if both username and password are set."""
        if self.username and self.password:
            return httpx.BasicAuth(self.username, self.password)
        return None

    async def ready(self) -> backends.BackendStatus:
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        try:
            auth = self._get_auth()
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url=f"{self.api_url}/sdapi/v1/memory", timeout=timeout, auth=auth
                )
                ready = response.status_code == 200
                return backends.BackendStatus(
                    type=backends.BackendStatusType.OK
                    if ready
                    else backends.BackendStatusType.ERROR
                )
        except httpx.RequestError as e:
            log.error(
                "Failed to test connection to SD.Next",
                error=str(e),
                api_url=self.api_url,
                timeout=timeout,
            )
            return backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )

    async def _txt2img(self, request: GenerationRequest) -> bytes | None:
        steps = request.agent_config.get("steps") or request.sampler_settings.steps
        cfg_scale = request.agent_config.get("cfg_scale") or 7
        sampler_name = request.agent_config.get("sampler_name") or "DPM++ 2M"

        payload = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt or "",
            "steps": steps,
            "width": request.resolution.width,
            "height": request.resolution.height,
            "cfg_scale": cfg_scale,
            "sampler_name": sampler_name,
            "send_images": True,
        }

        # Per SD.Next OpenAPI, select model via override_settings
        if request.agent_config.get("model"):
            payload["override_settings"] = {
                "sd_model_checkpoint": request.agent_config.get("model")
            }
            payload["override_settings_restore_afterwards"] = False

        log.info(
            "sdnext.Backend.txt2img",
            payload=payload,
            api_url=self.api_url,
            request=request,
        )

        auth = self._get_auth()
        async with httpx.AsyncClient() as client:
            _response = await client.post(
                url=f"{self.api_url}/sdapi/v1/txt2img",
                json=payload,
                timeout=self.generate_timeout,
                auth=auth,
            )
            _response.raise_for_status()

        r = _response.json()
        images = r.get("images", [])
        if not images:
            return None
        b64_data = images[0]
        try:
            return base64.b64decode(b64_data)
        except Exception:
            if "," in b64_data:
                return base64.b64decode(b64_data.split(",", 1)[1])
            return None

    async def _img2img(self, request: GenerationRequest) -> bytes | None:
        steps = request.agent_config.get("steps") or request.sampler_settings.steps
        cfg_scale = request.agent_config.get("cfg_scale") or 7
        sampler_name = request.agent_config.get("sampler_name") or "DPM++ 2M"

        init_images: list[str] = []
        for img_bytes in request.reference_bytes or []:
            if not img_bytes:
                continue
            init_images.append(base64.b64encode(img_bytes).decode("utf-8"))

        if not init_images:
            return None

        payload = {
            "init_images": init_images[:1],  # minimal support: use the first image
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt or "",
            "steps": steps,
            "width": request.resolution.width,
            "height": request.resolution.height,
            "cfg_scale": cfg_scale,
            "sampler_name": sampler_name,
            "send_images": True,
        }

        # Per SD.Next OpenAPI, select model via override_settings
        if request.agent_config.get("model"):
            payload["override_settings"] = {
                "sd_model_checkpoint": request.agent_config.get("model")
            }
            payload["override_settings_restore_afterwards"] = False

        log.info(
            "sdnext.Backend.img2img",
            payload={k: v for k, v in payload.items() if k != "init_images"},
            api_url=self.api_url,
            request=request,
        )

        auth = self._get_auth()
        async with httpx.AsyncClient() as client:
            _response = await client.post(
                url=f"{self.api_url}/sdapi/v1/img2img",
                json=payload,
                timeout=self.generate_timeout,
                auth=auth,
            )
            _response.raise_for_status()

        r = _response.json()
        images = r.get("images", [])
        if not images:
            return None
        b64_data = images[0]
        try:
            return base64.b64decode(b64_data)
        except Exception:
            if "," in b64_data:
                return base64.b64decode(b64_data.split(",", 1)[1])
            return None

    async def generate(
        self, request: GenerationRequest, response: GenerationResponse
    ) -> GenerationResponse:
        if request.gen_type == GEN_TYPE.IMAGE_EDIT:
            image_bytes = await self._img2img(request)
        else:
            image_bytes = await self._txt2img(request)

        if image_bytes:
            response.generated = image_bytes
        return response

    async def cancel_request(self):
        """
        Cancel the current generation request by calling SD.Next's /interrupt endpoint.
        """
        log.info("sdnext.Backend.cancel_request", api_url=self.api_url)
        try:
            auth = self._get_auth()
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url=f"{self.api_url}/sdapi/v1/interrupt", auth=auth
                )
                response.raise_for_status()
                log.info("sdnext.Backend.cancel_request", response=response.text)
        except Exception as e:
            log.error(
                "sdnext.Backend.cancel_request",
                error=str(e),
                api_url=self.api_url,
            )
            raise


class SDNextHandler:
    def __init__(self, backend: Backend, action: AgentAction):
        self.backend = backend
        self.action = action

    @property
    def api_url(self) -> str:
        return self.action.config["api_url"].value

    @property
    def resolution_square(self) -> Resolution:
        return Resolution(*self.action.config["resolution_square"].value)

    @property
    def resolution_portrait(self) -> Resolution:
        return Resolution(*self.action.config["resolution_portrait"].value)

    @property
    def resolution_landscape(self) -> Resolution:
        return Resolution(*self.action.config["resolution_landscape"].value)


class SDNextMixin:
    @classmethod
    def _shared_config(cls) -> dict[str, AgentActionConfig]:
        return {
            "api_url": AgentActionConfig(
                type="text",
                value="http://localhost:7860",
                label="API URL",
                description="The URL of the SD.Next API",
                save_on_change=True,
            ),
            "username": AgentActionConfig(
                type="text",
                title="Authentication (optional, server dependent)",
                value="",
                label="Username",
                description="Username for basic authentication.",
                save_on_change=True,
            ),
            "password": AgentActionConfig(
                type="password",
                value="",
                label="Password",
                description="Password for basic authentication.",
                save_on_change=True,
            ),
            "steps": AgentActionConfig(
                title="Sampler Settings",
                type="number",
                value=40,
                label="Steps",
                min=5,
                max=150,
                step=1,
                description="Number of render steps",
            ),
            "sampling_method": AgentActionConfig(
                type="text",
                choices=[],  # populated dynamically from /sdapi/v1/samplers
                value="DPM++ 2M",
                label="Sampling Method",
                description="The sampling method to use",
            ),
            # schedule_type removed – not in SD.Next OpenAPI
            "cfg": AgentActionConfig(
                type="number",
                value=7,
                label="CFG Scale",
                description="Classifier-free guidance scale",
                min=1,
                max=30,
                step=0.5,
            ),
            "prompt_type": AgentActionConfig(
                type="text",
                title="Prompt generation",
                value=PROMPT_TYPE.KEYWORDS,
                label="Prompting Type",
                choices=PROMPT_TYPE.choices(),
                description="Semantic style of the generated prompt.",
            ),
            "model": AgentActionConfig(
                type="autocomplete",
                value="",
                label="Model",
                choices=[],
                description="The main image generation model to use.",
            ),
            "resolution_square": AgentActionConfig(
                type="vector2",
                title="Resolutions",
                value=[1024, 1024],
                label="Square",
                description="The resolution to use for square images.",
            ),
            "resolution_portrait": AgentActionConfig(
                type="vector2",
                value=[832, 1216],
                label="Portrait",
                description="The resolution to use for portrait images.",
            ),
            "resolution_landscape": AgentActionConfig(
                type="vector2",
                value=[1216, 832],
                label="Landscape",
                description="The resolution to use for landscape images.",
            ),
        }

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["sdnext_image_create"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image",
            label="SD.Next",
            subtitle="Text to image",
            description="Basic text to image generation configuration for SD.Next.",
            condition=AgentActionConditional(
                attribute="_config.config.backend", value=BACKEND_NAME
            ),
            config=cls._shared_config(),
        )

        actions["sdnext_image_edit"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-image-edit",
            label="SD.Next",
            subtitle="Image editing",
            description="Image editing configuration for SD.Next.",
            condition=AgentActionConditional(
                attribute="_config.config.backend_image_edit", value=BACKEND_NAME
            ),
            config=cls._shared_config(),
        )

        return actions

    # helpers
    def sdnext_handler(self, backend_type: str) -> "SDNextHandler | None":
        if (
            backend_type == "backend"
            and self.backend
            and isinstance(self.backend, Backend)
        ):
            return SDNextHandler(self.backend, self.actions["sdnext_image_create"])
        elif (
            backend_type == "backend_image_edit"
            and self.backend_image_edit
            and isinstance(self.backend_image_edit, Backend)
        ):
            return SDNextHandler(
                self.backend_image_edit, self.actions["sdnext_image_edit"]
            )
        return None

    @property
    def sdnext_handlers(self) -> list["SDNextHandler"]:
        return [
            self.sdnext_handler("backend"),
            self.sdnext_handler("backend_image_edit"),
        ]

    async def sdnext_emit_status(self, processing: bool = None):
        # No-op: model choices are updated when vital configuration changes
        return

    async def sdnext_update_model_choices(self, action_name: str):
        action = self.actions[action_name]
        api_url = action.config["api_url"].value
        username = action.config["username"].value or None
        password = action.config["password"].value or None
        auth = httpx.BasicAuth(username, password) if username and password else None
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url=f"{api_url}/sdapi/v1/sd-models", timeout=5, auth=auth
                )
                models = resp.json() if resp.status_code == 200 else []
        except Exception:
            models = []
        choices = [
            {
                "label": m.get("title", m.get("model_name")),
                "value": m.get("title", m.get("model_name")),
            }
            for m in (models or [])
        ]
        action.config["model"].choices = (
            ([{"label": "- Default Model -", "value": ""}] + choices)
            if choices
            else [{"label": "- Default Model -", "value": ""}]
        )

    async def sdnext_update_sampler_choices(self, action_name: str):
        action = self.actions[action_name]
        api_url = action.config["api_url"].value
        username = action.config["username"].value or None
        password = action.config["password"].value or None
        auth = httpx.BasicAuth(username, password) if username and password else None
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url=f"{api_url}/sdapi/v1/samplers", timeout=5, auth=auth
                )
                samplers = resp.json() if resp.status_code == 200 else []
        except Exception:
            samplers = []
        choices = [
            {"label": s.get("name"), "value": s.get("name")}
            for s in (samplers or [])
            if s.get("name")
        ]
        action.config["sampling_method"].choices = choices

    # backend instantiation / swapping
    async def _sdnext_backend(
        self,
        backend: Backend | None,
        action_name: str,
        old_config: dict | None = None,
        force: bool = False,
    ) -> Backend | None:
        backend_instance_exists = isinstance(backend, Backend)
        api_url = self.actions[action_name].config["api_url"].value
        username = self.actions[action_name].config["username"].value or None
        password = self.actions[action_name].config["password"].value or None

        gen_type = (
            GEN_TYPE.TEXT_TO_IMAGE
            if action_name == "sdnext_image_create"
            else GEN_TYPE.IMAGE_EDIT
        )

        prompt_type = self.actions[action_name].config["prompt_type"].value

        try:
            _api_url_changed = (
                old_config[action_name].config["api_url"].value != api_url
            )
            old_username = old_config[action_name].config["username"].value or None
            old_password = old_config[action_name].config["password"].value or None
            _username_changed = old_username != username
            _password_changed = old_password != password
        except Exception:
            _api_url_changed = False
            _username_changed = False
            _password_changed = False

        _reinit = (
            force
            or _api_url_changed
            or _username_changed
            or _password_changed
            or not backend_instance_exists
        )

        if _reinit:
            log.debug(
                "reinitializing sdnext backend",
                action_name=action_name,
                api_url=api_url,
            )
            backend = Backend(
                api_url=api_url,
                gen_type=gen_type,
                prompt_type=prompt_type,
                username=username,
                password=password,
            )
        else:
            backend.api_url = api_url
            backend.username = username
            backend.password = password

        # Update choices when vital config changes or if choices are empty
        model_choices = self.actions[action_name].config["model"].choices
        sampler_choices = self.actions[action_name].config["sampling_method"].choices
        if _reinit or _api_url_changed or not model_choices:
            await self.sdnext_update_model_choices(action_name)
        if _reinit or _api_url_changed or not sampler_choices:
            await self.sdnext_update_sampler_choices(action_name)

        # If API URL changed, preserve previously selected model when possible.
        # Only clear if the selected value is not present in the new choices.
        if _api_url_changed:
            current_value = self.actions[action_name].config["model"].value
            choices = self.actions[action_name].config["model"].choices or []
            values = {c.get("value") for c in choices}
            if current_value and current_value not in values:
                self.actions[action_name].config["model"].value = ""

        backend.prompt_type = prompt_type

        return backend

    async def sdnext_backend(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend | None:
        return await self._sdnext_backend(
            self.backend, "sdnext_image_create", old_config, force
        )

    async def sdnext_backend_image_edit(
        self, old_config: dict | None = None, force: bool = False
    ) -> Backend | None:
        return await self._sdnext_backend(
            self.backend_image_edit, "sdnext_image_edit", old_config, force
        )

    async def sdnext_prepare_generation(self, request: GenerationRequest) -> Backend:
        handler = None
        if request.gen_type == GEN_TYPE.TEXT_TO_IMAGE:
            handler = self.sdnext_handler("backend")
        elif request.gen_type == GEN_TYPE.IMAGE_EDIT:
            handler = self.sdnext_handler("backend_image_edit")

        if not handler:
            raise ValueError(f"Invalid generation type: {request.gen_type}")

        action = handler.action
        request.agent_config["steps"] = action.config["steps"].value
        request.agent_config["sampler_name"] = action.config["sampling_method"].value
        request.agent_config["cfg_scale"] = action.config["cfg"].value
        request.agent_config["model"] = action.config["model"].value
        request.resolution = self.resolution(request.format, action)

        if request.gen_type == GEN_TYPE.IMAGE_EDIT:
            return handler.backend

        return handler.backend
