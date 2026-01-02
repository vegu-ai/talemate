import base64
import httpx
import structlog

from talemate.instance import get_agent
from talemate.agents.base import AgentAction, AgentActionConfig, AgentActionConditional
import talemate.agents.visual.backends as backends
from talemate.agents.visual.backends.utils import (
    normalize_api_url,
    get_resolution_choices,
)
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
    auth_method: str | None = None
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    model: str | None = None
    models: list[dict] = []

    @property
    def max_references(self) -> int:
        # Minimal edit support: one reference image
        return 1 if self.gen_type == GEN_TYPE.IMAGE_EDIT else 0

    @property
    def instance_label(self) -> str:
        return self.api_url

    @property
    def generator_label(self) -> str | None:
        return self.model

    @property
    def generate_timeout(self) -> int:
        return get_agent("visual").generate_timeout

    def _get_auth(self) -> httpx.BasicAuth | None:
        """Get basic auth credentials if auth_method is basic and both username and password are set."""
        if self.auth_method == "basic" and self.username and self.password:
            return httpx.BasicAuth(self.username, self.password)
        return None

    def _get_headers(self) -> dict[str, str]:
        """Get authorization headers for bearer auth."""
        headers = {}
        if self.auth_method == "bearer" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def ready(self) -> backends.BackendStatus:
        try:
            await self.ensure_test_connection_task()
        except Exception as e:
            self.status = backends.BackendStatus(
                type=backends.BackendStatusType.ERROR, message=str(e)
            )
        return self.status

    async def on_status_change(self):
        visual_agent = get_agent("visual")
        choices_changed_create = False
        choices_changed_edit = False
        if self.status.type == backends.BackendStatusType.OK:
            choices_changed_create = await visual_agent.sdnext_update_model_choices(
                "sdnext_image_create", backend=self
            )
            choices_changed_edit = await visual_agent.sdnext_update_model_choices(
                "sdnext_image_edit", backend=self
            )
        if choices_changed_create or choices_changed_edit:
            await super().on_status_change()

    def _get_cache_data(self) -> dict:
        """Return models list to cache for sharing with other backends."""
        return {"models": self.models}

    def _apply_cache_data(self, data: dict):
        """Apply cached models list to this backend instance."""
        if "models" in data:
            self.models = data["models"]

    async def test_connection(self, timeout: int = 2) -> backends.BackendStatus:
        try:
            auth = self._get_auth()
            headers = self._get_headers()
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url=f"{normalize_api_url(self.api_url)}/sdapi/v1/sd-models",
                    timeout=timeout,
                    auth=auth,
                    headers=headers,
                )
                ready = response.status_code == 200
                if ready:
                    try:
                        self.models = response.json()
                    except Exception:
                        self.models = []
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
            payload["sd_model_checkpoint"] = request.agent_config.get("model")

        log.info(
            "sdnext.Backend.txt2img",
            payload=payload,
            api_url=self.api_url,
            request=request,
        )

        auth = self._get_auth()
        headers = self._get_headers()
        async with httpx.AsyncClient() as client:
            _response = await client.post(
                url=f"{normalize_api_url(self.api_url)}/sdapi/v1/txt2img",
                json=payload,
                timeout=self.generate_timeout,
                auth=auth,
                headers=headers,
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
            payload["sd_model_checkpoint"] = request.agent_config.get("model")

        log.info(
            "sdnext.Backend.img2img",
            payload={k: v for k, v in payload.items() if k != "init_images"},
            api_url=self.api_url,
            request=request.model_dump(exclude={"reference_bytes"}),
        )

        auth = self._get_auth()
        headers = self._get_headers()
        async with httpx.AsyncClient() as client:
            _response = await client.post(
                url=f"{normalize_api_url(self.api_url)}/sdapi/v1/img2img",
                json=payload,
                timeout=self.generate_timeout,
                auth=auth,
                headers=headers,
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
            headers = self._get_headers()
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url=f"{normalize_api_url(self.api_url)}/sdapi/v1/interrupt",
                    auth=auth,
                    headers=headers,
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
    def _shared_config(cls, action_name: str) -> dict[str, AgentActionConfig]:
        return {
            "api_url": AgentActionConfig(
                type="text",
                value="http://localhost:7860",
                label="API URL",
                description="The URL of the SD.Next API",
                save_on_change=True,
            ),
            "auth_method": AgentActionConfig(
                type="text",
                value="none",
                label="Authentication Method",
                description="The authentication method to use.",
                choices=[
                    {"label": "None", "value": "none"},
                    {"label": "Basic (username/password)", "value": "basic"},
                    {"label": "Bearer (API Key)", "value": "bearer"},
                ],
                save_on_change=True,
            ),
            "username": AgentActionConfig(
                type="text",
                title="Authentication (optional, server dependent)",
                value="",
                label="Username",
                description="Username for basic authentication.",
                save_on_change=True,
                condition=AgentActionConditional(
                    attribute=f"{action_name}.config.auth_method", value="basic"
                ),
            ),
            "password": AgentActionConfig(
                type="password",
                value="",
                label="Password",
                description="Password for basic authentication.",
                save_on_change=True,
                condition=AgentActionConditional(
                    attribute=f"{action_name}.config.auth_method", value="basic"
                ),
            ),
            "api_key": AgentActionConfig(
                type="password",
                value="",
                label="API Key",
                description="API Key for bearer authentication.",
                save_on_change=True,
                condition=AgentActionConditional(
                    attribute=f"{action_name}.config.auth_method", value="bearer"
                ),
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
                choices=get_resolution_choices("square"),
            ),
            "resolution_portrait": AgentActionConfig(
                type="vector2",
                value=[832, 1216],
                label="Portrait",
                description="The resolution to use for portrait images.",
                choices=get_resolution_choices("portrait"),
            ),
            "resolution_landscape": AgentActionConfig(
                type="vector2",
                value=[1216, 832],
                label="Landscape",
                description="The resolution to use for landscape images.",
                choices=get_resolution_choices("landscape"),
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
            config=cls._shared_config("sdnext_image_create"),
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
            config=cls._shared_config("sdnext_image_edit"),
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
        for handler in self.sdnext_handlers:
            if not handler:
                continue

            if handler.backend and handler.backend.models:
                await self.sdnext_update_model_choices(
                    "sdnext_image_create"
                    if handler.backend.gen_type == GEN_TYPE.TEXT_TO_IMAGE
                    else "sdnext_image_edit",
                    backend=handler.backend,
                )
        return

    def _get_auth_from_config(
        self, action_name: str
    ) -> tuple[httpx.BasicAuth | None, dict[str, str]]:
        """Get auth and headers from action config based on auth_method."""
        action = self.actions[action_name]
        auth_method = action.config["auth_method"].value or "basic"
        username = action.config["username"].value or None
        password = action.config["password"].value or None
        api_key = action.config["api_key"].value or None

        auth = None
        headers = {}
        if auth_method == "basic" and username and password:
            auth = httpx.BasicAuth(username, password)
        elif auth_method == "bearer" and api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        return auth, headers

    async def sdnext_update_model_choices(
        self, action_name: str, backend: Backend | None = None
    ) -> bool:
        action = self.actions[action_name]
        if not backend:
            return

        old_choices = action.config["model"].choices

        choices = [
            {
                "label": m.get("title", m.get("model_name")),
                "value": m.get("title", m.get("model_name")),
            }
            for m in (backend.models or [])
        ]
        action.config["model"].choices = (
            ([{"label": "- Default Model -", "value": ""}] + choices)
            if choices
            else [{"label": "- Default Model -", "value": ""}]
        )

        log.debug(
            "sdnext_update_model_choices",
            old_choices=old_choices,
            new_choices=action.config["model"].choices,
        )

        choices_changed = old_choices != action.config["model"].choices
        return choices_changed

    async def sdnext_update_sampler_choices(self, action_name: str):
        action = self.actions[action_name]
        api_url = action.config["api_url"].value
        auth, headers = self._get_auth_from_config(action_name)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url=f"{normalize_api_url(api_url)}/sdapi/v1/samplers",
                    timeout=5,
                    auth=auth,
                    headers=headers,
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
        auth_method = self.actions[action_name].config["auth_method"].value or "basic"
        username = self.actions[action_name].config["username"].value or None
        password = self.actions[action_name].config["password"].value or None
        api_key = self.actions[action_name].config["api_key"].value or None

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
            old_auth_method = (
                old_config[action_name].config["auth_method"].value or "basic"
            )
            old_username = old_config[action_name].config["username"].value or None
            old_password = old_config[action_name].config["password"].value or None
            old_api_key = old_config[action_name].config["api_key"].value or None
            _auth_method_changed = old_auth_method != auth_method
            _username_changed = old_username != username
            _password_changed = old_password != password
            _api_key_changed = old_api_key != api_key
        except Exception:
            _api_url_changed = False
            _auth_method_changed = False
            _username_changed = False
            _password_changed = False
            _api_key_changed = False

        _reinit = (
            force
            or _api_url_changed
            or _auth_method_changed
            or _username_changed
            or _password_changed
            or _api_key_changed
            or not backend_instance_exists
        )

        model = self.actions[action_name].config["model"].value or None

        if _reinit:
            log.debug(
                "reinitializing sdnext backend",
                action_name=action_name,
                api_url=api_url,
                auth_method=auth_method,
            )
            backend = Backend(
                api_url=api_url,
                gen_type=gen_type,
                prompt_type=prompt_type,
                auth_method=auth_method,
                username=username,
                password=password,
                api_key=api_key,
                model=model,
            )
        else:
            backend.api_url = api_url
            backend.auth_method = auth_method
            backend.username = username
            backend.password = password
            backend.api_key = api_key
            backend.model = model

        # Update choices when vital config changes or if choices are empty
        model_choices = self.actions[action_name].config["model"].choices
        sampler_choices = self.actions[action_name].config["sampling_method"].choices
        _auth_changed = (
            _auth_method_changed
            or _username_changed
            or _password_changed
            or _api_key_changed
        )
        if _reinit or _api_url_changed or _auth_changed or not model_choices:
            await self.sdnext_update_model_choices(action_name, backend=backend)
        if _reinit or _api_url_changed or _auth_changed or not sampler_choices:
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
