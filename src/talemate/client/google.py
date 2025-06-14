import json
import os

import pydantic
import structlog
import vertexai
from google.api_core.exceptions import ResourceExhausted
from vertexai.generative_models import (
    ChatSession,
    GenerationConfig,
    GenerativeModel,
    ResponseValidationError,
    SafetySetting,
)

from talemate.client.base import ClientBase, ErrorAction, ExtraField, ParameterReroute, CommonDefaults
from talemate.client.registry import register
from talemate.client.remote import RemoteServiceMixin
from talemate.config import Client as BaseClientConfig
from talemate.config import load_config
from talemate.emit import emit
from talemate.emit.signals import handlers
from talemate.util import count_tokens

__all__ = [
    "GoogleClient",
]
log = structlog.get_logger("talemate")

# Edit this to add new models / remove old models
SUPPORTED_MODELS = [
    "gemini-1.0-pro",
    "gemini-1.5-pro-preview-0409",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.5-pro-preview-03-25",
]


class Defaults(CommonDefaults, pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = "gemini-1.0-pro"
    disable_safety_settings: bool = False


class ClientConfig(BaseClientConfig):
    disable_safety_settings: bool = False


@register()
class GoogleClient(RemoteServiceMixin, ClientBase):
    """
    Google client for generating text.
    """

    client_type = "google"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    decensor_enabled = True
    config_cls = ClientConfig

    class Meta(ClientBase.Meta):
        name_prefix: str = "Google"
        title: str = "Google"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()
        extra_fields: dict[str, ExtraField] = {
            "disable_safety_settings": ExtraField(
                name="disable_safety_settings",
                type="bool",
                label="Disable Safety Settings",
                required=False,
                description="Disable Google's safety settings for responses generated by the model.",
            ),
        }

    def __init__(self, model="gemini-1.0-pro", **kwargs):
        self.model_name = model
        self.setup_status = None
        self.model_instance = None
        self.disable_safety_settings = kwargs.get("disable_safety_settings", False)
        self.google_credentials_read = False
        self.google_project_id = None
        self.config = load_config()
        super().__init__(**kwargs)

        handlers["config_saved"].connect(self.on_config_saved)

    @property
    def google_credentials(self):
        path = self.google_credentials_path
        if not path:
            return None
        with open(path) as f:
            return json.load(f)

    @property
    def google_credentials_path(self):
        return self.config.get("google").get("gcloud_credentials_path")

    @property
    def google_location(self):
        return self.config.get("google").get("gcloud_location")

    @property
    def ready(self):
        # all google settings must be set
        return all(
            [
                self.google_credentials_path,
                self.google_location,
            ]
        )

    @property
    def safety_settings(self):
        if not self.disable_safety_settings:
            return None

        safety_settings = [
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_UNSPECIFIED,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_NONE,
            ),
        ]

        return safety_settings

    @property
    def supported_parameters(self):
        return [
            "temperature",
            "top_p",
            "top_k",
            ParameterReroute(
                talemate_parameter="max_tokens", client_parameter="max_output_tokens"
            ),
            ParameterReroute(
                talemate_parameter="stopping_strings", client_parameter="stop_sequences"
            ),
        ]

    def emit_status(self, processing: bool = None):
        error_action = None
        if processing is not None:
            self.processing = processing

        if self.ready:
            status = "busy" if self.processing else "idle"
            model_name = self.model_name
        else:
            status = "error"
            model_name = "Setup incomplete"
            error_action = ErrorAction(
                title="Setup Google API credentials",
                action_name="openAppConfig",
                icon="mdi-key-variant",
                arguments=[
                    "application",
                    "google_api",
                ],
            )

        if not self.model_name:
            status = "error"
            model_name = "No model loaded"

        self.current_status = status
        data = {
            "error_action": error_action.model_dump() if error_action else None,
            "meta": self.Meta().model_dump(),
            "enabled": self.enabled,
        }
        data.update(self._common_status_data()) 
        self.populate_extra_fields(data)

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=model_name,
            status=status if self.enabled else "disabled",
            data=data,
        )

    def set_client(self, max_token_length: int = None, **kwargs):
        if not self.ready:
            log.error("Google cloud setup incomplete")
            if self.setup_status:
                self.setup_status = False
                emit("request_client_status")
                emit("request_agent_status")
            return

        if not self.model_name:
            self.model_name = "gemini-1.0-pro"

        if max_token_length and not isinstance(max_token_length, int):
            max_token_length = int(max_token_length)

        if self.google_credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.google_credentials_path

        model = self.model_name

        self.max_token_length = max_token_length or 16384

        if not self.setup_status:
            if self.setup_status is False:
                project_id = self.google_credentials.get("project_id")
                self.google_project_id = project_id
                if self.google_credentials_path:
                    vertexai.init(project=project_id, location=self.google_location)
                emit("request_client_status")
                emit("request_agent_status")
            self.setup_status = True

        self.model_instance = GenerativeModel(model_name=model)

        log.info(
            "google set client",
            max_token_length=self.max_token_length,
            provided_max_token_length=max_token_length,
            model=model,
        )

    def response_tokens(self, response: str):
        return count_tokens(response.text)

    def prompt_tokens(self, prompt: str):
        return count_tokens(prompt)

    def reconfigure(self, **kwargs):
        if kwargs.get("model"):
            self.model_name = kwargs["model"]
            self.set_client(kwargs.get("max_token_length"))

        if "disable_safety_settings" in kwargs:
            self.disable_safety_settings = kwargs["disable_safety_settings"]

        if "enabled" in kwargs:
            self.enabled = bool(kwargs["enabled"])
            
        self._reconfigure_common_parameters(**kwargs)

    def clean_prompt_parameters(self, parameters: dict):
        super().clean_prompt_parameters(parameters)

        # if top_k is 0, remove it
        if "top_k" in parameters and parameters["top_k"] == 0:
            del parameters["top_k"]

    async def generate(self, prompt: str, parameters: dict, kind: str):
        """
        Generates text from the given prompt and parameters.
        """

        if not self.ready:
            raise Exception("Google cloud setup incomplete")

        right = None
        expected_response = None
        try:
            _, right = prompt.split("\nStart your response with: ")
            expected_response = right.strip()
        except (IndexError, ValueError):
            pass

        human_message = prompt.strip()
        system_message = self.get_system_message(kind)

        self.log.debug(
            "generate",
            prompt=prompt[:128] + " ...",
            parameters=parameters,
            system_message=system_message,
            disable_safety_settings=self.disable_safety_settings,
            safety_settings=self.safety_settings,
        )

        try:

            chat = self.model_instance.start_chat()

            response = await chat.send_message_async(
                human_message,
                safety_settings=self.safety_settings,
                generation_config=parameters,
            )

            self._returned_prompt_tokens = self.prompt_tokens(prompt)
            self._returned_response_tokens = self.response_tokens(response)

            response = response.text

            log.debug("generated response", response=response)

            if expected_response and expected_response.startswith("{"):
                if response.startswith("```json") and response.endswith("```"):
                    response = response[7:-3].strip()

            if right and response.startswith(right):
                response = response[len(right) :].strip()

            return response

        # except PermissionDeniedError as e:
        #    self.log.error("generate error", e=e)
        #    emit("status", message="google API: Permission Denied", status="error")
        #    return ""
        except ResourceExhausted as e:
            self.log.error("generate error", e=e)
            emit("status", message="google API: Quota Limit reached", status="error")
            return ""
        except ResponseValidationError as e:
            self.log.error("generate error", e=e)
            emit(
                "status",
                message="google API: Response Validation Error",
                status="error",
            )
            if not self.disable_safety_settings:
                return "Failed to generate response. Probably due to safety settings, you can turn them off in the client settings."
            return "Failed to generate response. Please check logs."
        except Exception as e:
            raise
