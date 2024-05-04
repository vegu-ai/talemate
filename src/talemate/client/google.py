import pydantic
import structlog
import vertexai
import json
import os
from vertexai.generative_models import GenerativeModel, ChatSession

from talemate.client.base import ClientBase, ErrorAction
from talemate.client.remote import RemoteServiceMixin
from talemate.client.registry import register
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
]


class Defaults(pydantic.BaseModel):
    max_token_length: int = 16384
    model: str = "gemini-1.0-pro"


@register()
class GoogleClient(RemoteServiceMixin, ClientBase):
    """
    Google client for generating text.
    """

    client_type = "google"
    conversation_retries = 0
    auto_break_repetition_enabled = False
    decensor_enabled = True

    class Meta(ClientBase.Meta):
        name_prefix: str = "Google"
        title: str = "Google"
        manual_model: bool = True
        manual_model_choices: list[str] = SUPPORTED_MODELS
        requires_prompt_template: bool = False
        defaults: Defaults = Defaults()

    def __init__(self, model="gemini-1.0-pro", **kwargs):
        self.model_name = model
        self.setup_status = None
        self.model_instance =None
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

        emit(
            "client_status",
            message=self.client_type,
            id=self.name,
            details=model_name,
            status=status,
            data={
                "error_action": error_action.model_dump() if error_action else None,
                "meta": self.Meta().model_dump(),
            },
        )

    def set_client(self, max_token_length: int = None):
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
        )

        try:
            
            chat = self.model_instance.start_chat()
            
            response = await chat.send_message_async(human_message)
            
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
            
            
            """
            response = await self.client.chat(
                model=self.model_name,
                preamble=system_message,
                message=human_message,
                **parameters,
            )

            self._returned_prompt_tokens = self.prompt_tokens(prompt)
            self._returned_response_tokens = self.response_tokens(response)

            log.debug("generated response", response=response.text)

            response = response.text

            if expected_response and expected_response.startswith("{"):
                if response.startswith("```json") and response.endswith("```"):
                    response = response[7:-3].strip()

            if right and response.startswith(right):
                response = response[len(right) :].strip()

            return response
            """
        # except PermissionDeniedError as e:
        #    self.log.error("generate error", e=e)
        #    emit("status", message="google API: Permission Denied", status="error")
        #    return ""
        except Exception as e:
            raise
