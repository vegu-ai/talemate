import pydantic
import structlog

from .base import FieldGroup, ExtraField

import talemate.ux.schema as ux_schema


log = structlog.get_logger(__name__)

__all__ = [
    "RemoteServiceMixin",
    "EndpointOverrideMixin",
    "endpoint_override_extra_fields",
    "EndpointOverrideGroup",
    "EndpointOverrideField",
    "EndpointOverrideBaseURLField",
    "EndpointOverrideAPIKeyField",
]

def endpoint_override_extra_fields():
    return {
        "override_base_url": EndpointOverrideBaseURLField(),
        "override_api_key": EndpointOverrideAPIKeyField(),
    }

class EndpointOverride(pydantic.BaseModel):
    override_base_url: str | None = None
    override_api_key: str | None = None
    
class EndpointOverrideGroup(FieldGroup):
    name: str = "endpoint_override"
    label: str = "Endpoint Override"
    description: str = ("Override the default base URL used by this client to access the {client_type} service API.\n\n"
                        "IMPORTANT: Provide an override only if you fully trust the endpoint. When set, the {client_type} API key defined in the global application settings is deliberately ignored to avoid accidental credential leakage. "
                        "If the override endpoint requires an API key, enter it below.")
    icon: str = "mdi-api"

class EndpointOverrideField(ExtraField):
    group: EndpointOverrideGroup = pydantic.Field(default_factory=EndpointOverrideGroup)
    
class EndpointOverrideBaseURLField(EndpointOverrideField):
    name: str = "override_base_url"
    type: str = "text"
    label: str = "Base URL"
    required: bool = False
    description: str = "Override the base URL for the remote service"
    
class EndpointOverrideAPIKeyField(EndpointOverrideField):
    name: str = "override_api_key"
    type: str = "password"
    label: str = "API Key"
    required: bool = False
    description: str = "Override the API key for the remote service"
    note: ux_schema.Note = pydantic.Field(default_factory=lambda: ux_schema.Note(
        text="This is NOT the API key for the official {client_type} API. It is only used when overriding the base URL. The official {client_type} API key can be configured in the application settings.",
        color="warning",
    ))


class EndpointOverrideMixin:
    override_base_url: str | None = None
    override_api_key: str | None = None
    
    def set_client_api_key(self, api_key: str | None):
        if getattr(self, "client", None):
            try:
                self.client.api_key = api_key
            except Exception as e:
                log.error("Error setting client API key", error=e, client=self.client_type)

    @property
    def api_key(self) -> str | None:
        if self.endpoint_override_base_url_configured:
            return self.override_api_key
        return getattr(self, f"{self.client_type}_api_key", None)

    @property
    def base_url(self) -> str | None:
        if self.override_base_url and self.override_base_url.strip():
            return self.override_base_url
        return None

    @property
    def endpoint_override_base_url_configured(self) -> bool:
        return self.override_base_url and self.override_base_url.strip()
    
    @property
    def endpoint_override_api_key_configured(self) -> bool:
        return self.override_api_key and self.override_api_key.strip()
    
    @property
    def endpoint_override_fully_configured(self) -> bool:
        return self.endpoint_override_base_url_configured and self.endpoint_override_api_key_configured

    def _reconfigure_endpoint_override(self, **kwargs):
        if "override_base_url" in kwargs:
            orig = getattr(self, "override_base_url", None)
            self.override_base_url = kwargs["override_base_url"]
            if getattr(self, "client", None) and orig != self.override_base_url:
                log.info("Reconfiguring client base URL", new=self.override_base_url)
                self.set_client(kwargs.get("max_token_length"))
            
        if "override_api_key" in kwargs:
            self.override_api_key = kwargs["override_api_key"]
            self.set_client_api_key(self.override_api_key)

class RemoteServiceMixin:

    def prompt_template(self, system_message: str, prompt: str):
        if "<|BOT|>" in prompt:
            _, right = prompt.split("<|BOT|>", 1)
            if right:
                prompt = prompt.replace("<|BOT|>", "\nStart your response with: ")
            else:
                prompt = prompt.replace("<|BOT|>", "")

        return prompt

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))
        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])

    def on_config_saved(self, event):
        config = event.data
        self.config = config
        self.set_client(max_token_length=self.max_token_length)

    async def status(self):
        self.emit_status()
