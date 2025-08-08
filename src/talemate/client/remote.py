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
    description: str = (
        "Override the default base URL used by this client to access the {client_type} service API.\n\n"
        "IMPORTANT: Provide an override only if you fully trust the endpoint. When set, the {client_type} API key defined in the global application settings is deliberately ignored to avoid accidental credential leakage. "
        "If the override endpoint requires an API key, enter it below."
    )
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
    note: ux_schema.Note = pydantic.Field(
        default_factory=lambda: ux_schema.Note(
            text="This is NOT the API key for the official {client_type} API. It is only used when overriding the base URL. The official {client_type} API key can be configured in the application settings.",
            color="warning",
        )
    )


class EndpointOverrideMixin:
    @property
    def override_base_url(self) -> str | None:
        return self.client_config.override_base_url

    @property
    def override_api_key(self) -> str | None:
        return self.client_config.override_api_key

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
        return (
            self.endpoint_override_base_url_configured
            and self.endpoint_override_api_key_configured
        )


class RemoteServiceMixin:
    async def status(self):
        self.emit_status()
