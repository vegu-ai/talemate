import datetime
import json
import os
import shutil
import tempfile
import pydantic
from typing import Any

import huggingface_hub
import requests
import structlog
from jinja2 import Environment, FileSystemLoader

__all__ = ["model_prompt", "PromptSpec"]

# (connect, read) timeout in seconds applied to every huggingface_hub request.
# Some HF calls (notably HfApi.list_models) issue requests without any timeout,
# so a network issue reaching huggingface.co would otherwise hang indefinitely.
HF_REQUEST_TIMEOUT = (10, 30)


class _TimeoutHTTPSession(requests.Session):
    """requests.Session that applies a default timeout to every request."""

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", HF_REQUEST_TIMEOUT)
        return super().request(*args, **kwargs)


# Ensure all huggingface_hub HTTP requests fail fast on connection issues
# instead of hanging forever. Calls that pass their own timeout are unaffected.
huggingface_hub.configure_http_backend(backend_factory=_TimeoutHTTPSession)

BASE_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "..",
    "templates",
    "llm-prompt",
)

# holds the default templates
STD_TEMPLATE_PATH = os.path.join(BASE_TEMPLATE_PATH, "std")

# user-supplied base templates (sits inside std/ but gitignored)
STD_USER_TEMPLATE_PATH = os.path.join(STD_TEMPLATE_PATH, "user")

# llm prompt templates provided by talemate
TALEMATE_TEMPLATE_PATH = os.path.join(BASE_TEMPLATE_PATH, "talemate")

# user overrides
USER_TEMPLATE_PATH = os.path.join(BASE_TEMPLATE_PATH, "user")

DEFAULT_TEMPLATE = "default.jinja2"

TEMPLATE_IDENTIFIERS = []


def register_template_identifier(cls):
    TEMPLATE_IDENTIFIERS.append(cls)
    return cls


log = structlog.get_logger("talemate.model_prompts")


def _raise_exception(msg):
    raise Exception(msg)


class PromptSpec(pydantic.BaseModel):
    template: str | None = None
    reasoning_pattern: str | None = None
    reasoning_validation_pattern: str | None = None

    def set_spec(self, key: str, value: Any):
        setattr(self, key, value)


class ModelPrompt:
    """
    Will attempt to load an LLM prompt template based on the model name

    If the model name is not found, it will default to the 'default' template
    """

    template_map = {}

    @property
    def env(self):
        if not hasattr(self, "_env"):
            log.info("modal prompt", base_template_path=BASE_TEMPLATE_PATH)
            self._env = Environment(
                loader=FileSystemLoader(
                    [
                        USER_TEMPLATE_PATH,
                        TALEMATE_TEMPLATE_PATH,
                    ]
                )
            )

        return self._env

    @property
    def std_templates(self) -> list[str]:
        # Built-in templates from std/ (excluding user/ subdir)
        builtin = [t["name"] for t in self.list_std_builtin_templates()]
        # User-supplied templates from std/user/, prefixed with "user/"
        user = [f"user/{t['name']}" for t in self.list_std_user_templates()]
        return sorted(builtin) + sorted(user)

    def __call__(
        self,
        model_name: str,
        system_message: str,
        prompt: str,
        double_coercion: str = None,
        default_template: str = DEFAULT_TEMPLATE,
        reasoning_tokens: int = 0,
        spec: PromptSpec = None,
    ):
        template, template_file = self.get_template(model_name)
        if not template:
            template_file = default_template
            template = self.env.get_template(template_file)

        if not double_coercion:
            double_coercion = ""

        if "<|BOT|>" not in prompt and double_coercion:
            prompt = f"{prompt}<|BOT|>"

        if "<|BOT|>" in prompt:
            user_message, coercion_message = prompt.split("<|BOT|>", 1)
            coercion_message = f"{double_coercion}{coercion_message}"
        else:
            user_message = prompt
            coercion_message = ""

        if spec is None:
            spec = PromptSpec()

        spec.template = template_file

        # Build GGUF/llama.cpp compatible messages list
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": user_message.strip()})
        if coercion_message:
            messages.append({"role": "assistant", "content": coercion_message})

        return (
            template.render(
                {
                    # Talemate native vars
                    "system_message": system_message,
                    "prompt": prompt.strip(),
                    "user_message": user_message.strip(),
                    "coercion_message": coercion_message,
                    "set_response": lambda prompt, response_str: self.set_response(
                        prompt, response_str, double_coercion
                    ),
                    "reasoning_tokens": reasoning_tokens,
                    "spec": spec,
                    # GGUF/llama.cpp compatible vars
                    "messages": messages,
                    "bos_token": "",
                    "eos_token": "",
                    "add_generation_prompt": True,
                    "enable_thinking": reasoning_tokens > 0,
                    "thinking_budget": reasoning_tokens,
                    "strftime_now": lambda fmt: datetime.datetime.now().strftime(fmt),
                    "raise_exception": _raise_exception,
                }
            ),
            template_file,
        )

    def set_response(self, prompt: str, response_str: str, double_coercion: str = None):
        prompt = prompt.strip("\n").strip()

        if not double_coercion:
            double_coercion = ""

        if "<|BOT|>" not in prompt and double_coercion:
            prompt = f"{prompt}<|BOT|>"

        if "<|BOT|>" in prompt:
            response_str = f"{double_coercion}{response_str}"

            if "\n<|BOT|>" in prompt:
                prompt = prompt.replace("\n<|BOT|>", response_str)
            else:
                prompt = prompt.replace("<|BOT|>", response_str)
        else:
            prompt = prompt.rstrip("\n") + response_str

        return prompt

    def clean_model_name(self, model_name: str):
        """
        Clean the model name to be used in the template file name.
        """
        return model_name.replace("/", "__").replace(":", "_").replace("\\", "__")

    def get_template(self, model_name: str):
        """
        Will attempt to load an LLM prompt template - this supports
        partial filename matching on the template file name.
        """

        matches = []

        cleaned_model_name = self.clean_model_name(model_name)

        # Iterate over all templates in the loader's directory
        for template_name in self.env.list_templates():
            # strip extension
            template_name_match = os.path.splitext(template_name)[0]

            # if template_name_match is the same as cleaned_model_name, return it
            if template_name_match.lower() == cleaned_model_name.lower():
                return self.env.get_template(template_name), template_name

            # Check if the model name is in the template filename
            if template_name_match.lower() in cleaned_model_name.lower():
                matches.append(template_name)

        # If there are no matches, return None
        if not matches:
            return None, None

        # If there is only one match, return it
        if len(matches) == 1:
            return self.env.get_template(matches[0]), matches[0]

        # If there are multiple matches, return the one with the longest name
        sorted_matches = sorted(matches, key=lambda x: len(x), reverse=True)
        return self.env.get_template(sorted_matches[0]), sorted_matches[0]

    def create_user_override(self, template_name: str, model_name: str):
        """
        Will copy a std template to USER_TEMPLATE_PATH/model_name.jinja2

        Supports both built-in templates (e.g. "ChatML.jinja2") and
        user-supplied templates (e.g. "user/MyTemplate.jinja2").
        """

        template_name = template_name.split(".jinja2")[0]

        cleaned_model_name = self.clean_model_name(model_name)

        if template_name.startswith("user/"):
            safe_name = os.path.basename(template_name[5:])
            source_path = os.path.join(STD_USER_TEMPLATE_PATH, safe_name + ".jinja2")
        else:
            source_path = os.path.join(STD_TEMPLATE_PATH, template_name + ".jinja2")

        dest_path = os.path.join(USER_TEMPLATE_PATH, cleaned_model_name + ".jinja2")
        shutil.copyfile(source_path, dest_path)

        return dest_path

    def _list_templates_in_dir(self, directory: str) -> list[dict]:
        """List .jinja2 templates in a directory with their content."""
        if not os.path.isdir(directory):
            return []
        results = []
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".jinja2"):
                continue
            fpath = os.path.join(directory, fname)
            if not os.path.isfile(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                results.append({"name": fname, "content": f.read()})
        return results

    def list_std_builtin_templates(self) -> list[dict]:
        """List built-in std/ templates with their content."""
        return self._list_templates_in_dir(STD_TEMPLATE_PATH)

    def list_std_user_templates(self) -> list[dict]:
        """List user-supplied templates in std/user/ with their content."""
        return self._list_templates_in_dir(STD_USER_TEMPLATE_PATH)

    def get_std_template_content(self, template_name: str) -> str | None:
        """Read content of a template from std/ or std/user/."""
        safe_name = os.path.basename(template_name)
        if template_name.startswith("user/"):
            fpath = os.path.join(STD_USER_TEMPLATE_PATH, safe_name)
        else:
            fpath = os.path.join(STD_TEMPLATE_PATH, safe_name)
        if not os.path.isfile(fpath):
            return None
        with open(fpath, "r", encoding="utf-8") as f:
            return f.read()

    def save_std_user_template(self, template_name: str, content: str) -> str:
        """Save/create a template in std/user/. Returns the file path."""
        os.makedirs(STD_USER_TEMPLATE_PATH, exist_ok=True)
        safe_name = os.path.basename(template_name)
        if not safe_name.endswith(".jinja2"):
            safe_name += ".jinja2"
        fpath = os.path.join(STD_USER_TEMPLATE_PATH, safe_name)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        return fpath

    def delete_std_user_template(self, template_name: str) -> bool:
        """Delete a template from std/user/."""
        safe_name = os.path.basename(template_name)
        fpath = os.path.join(STD_USER_TEMPLATE_PATH, safe_name)
        if os.path.isfile(fpath):
            os.remove(fpath)
            return True
        return False

    def _download_hf_file(
        self, repo_id: str, filename: str, revision: str
    ) -> str | None:
        """
        Download a single file from a HF repo into a temporary directory and
        return its contents. Returns None if the file is missing or cannot be
        retrieved (e.g. 404 or a connection issue).
        """
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = huggingface_hub.hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    cache_dir=tmpdir,
                    revision=revision,
                )
                with open(path) as f:
                    return f.read()
        except Exception as e:
            if not str(e).startswith("404"):
                log.error(
                    "query_hf_for_prompt_template_suggestion",
                    error=str(e),
                    filename=filename,
                )
            return None

    def _match_template_identifier(self, content: str) -> str | None:
        """Return the template file name whose identifier matches content."""
        for identifier_cls in TEMPLATE_IDENTIFIERS:
            identifier = identifier_cls()
            if identifier(content):
                return f"{identifier.template_str}.jinja2"
        return None

    def query_hf_for_prompt_template_suggestion(self, model_name: str) -> str | None:
        api = huggingface_hub.HfApi()

        log.debug("query_hf_for_prompt_template_suggestion", model_name=model_name)

        # if file ends with .gguf, split - and remove the last part
        if model_name.endswith(".gguf"):
            model_name = model_name.rsplit("-", 1)[0]
            model_name_alt = f"{model_name}-GGUF"
        else:
            model_name_alt = None

        log.debug("query_hf_for_prompt_template_suggestion", model_name=model_name)

        branch_name = "main"

        try:
            models = list(api.list_models(model_name=model_name))
            if not models and model_name_alt:
                models = list(api.list_models(model_name=model_name_alt))
        except Exception as e:
            log.warning(
                "query_hf_for_prompt_template_suggestion: "
                "could not reach HuggingFace to determine prompt template",
                model_name=model_name,
                error=str(e),
            )
            return None

        if not models:
            return None

        model = models[0]

        repo_id = f"{model.id}"

        # Files are checked in priority order; the first matching identifier wins.
        for filename in ("chat_template.jinja2", "README.md"):
            content = self._download_hf_file(repo_id, filename, branch_name)
            if content:
                match = self._match_template_identifier(content)
                if match:
                    return match

        # tokenizer_config.json stores the chat template under a "chat_template" key
        config_content = self._download_hf_file(
            repo_id, "tokenizer_config.json", branch_name
        )
        if config_content:
            try:
                config = json.loads(config_content)
            except json.JSONDecodeError:
                config = {}
            match = self._match_template_identifier(config.get("chat_template", ""))
            if match:
                return match


model_prompt = ModelPrompt()


class TemplateIdentifier:
    def __call__(self, content: str):
        return False


@register_template_identifier
class Mistralv7TekkenIdentifier(TemplateIdentifier):
    template_str = "MistralV7Tekken"

    def __call__(self, content: str):
        return (
            "[SYSTEM_PROMPT]" in content
            and "[INST]" in content
            and "[/INST]" in content
        )


@register_template_identifier
class MistralIdentifier(TemplateIdentifier):
    template_str = "Mistral"

    def __call__(self, content: str):
        return "[INST]" in content and "[/INST]" in content


@register_template_identifier
class Llama3Identifier(TemplateIdentifier):
    template_str = "Llama3"

    def __call__(self, content: str):
        return "<|start_header_id|>" in content and "<|end_header_id|>" in content


@register_template_identifier
class ChatMLIdentifier(TemplateIdentifier):
    template_str = "ChatML"

    def __call__(self, content: str):
        """
        <|im_start|>system
        {{ system_message }}<|im_end|>
        <|im_start|>user
        {{ user_message }}<|im_end|>
        <|im_start|>assistant
        {{ coercion_message }}
        """

        return "<|im_start|>" in content and "<|im_end|>" in content


@register_template_identifier
class CommandRIdentifier(TemplateIdentifier):
    template_str = "CommandR"

    def __call__(self, content: str):
        """
        <BOS_TOKEN><|START_OF_TURN_TOKEN|><|USER_TOKEN|>{{ system_message }}
        {{ user_message }}<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|>
        <|CHATBOT_TOKEN|>{{ coercion_message }}
        """

        return (
            "<|START_OF_TURN_TOKEN|>" in content
            and "<|END_OF_TURN_TOKEN|>" in content
            and "<|SYSTEM_TOKEN|>" not in content
        )


@register_template_identifier
class CommandRPlusIdentifier(TemplateIdentifier):
    template_str = "CommandRPlus"

    def __call__(self, content: str):
        """
        <BOS_TOKEN><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|>{{ system_message }}
        <|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|USER_TOKEN|>{{ user_message }}
        <|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>{{ coercion_message }}
        """

        return (
            "<|START_OF_TURN_TOKEN|>" in content
            and "<|END_OF_TURN_TOKEN|>" in content
            and "<|SYSTEM_TOKEN|>" in content
        )


@register_template_identifier
class InstructionInputResponseIdentifier(TemplateIdentifier):
    template_str = "InstructionInputResponse"

    def __call__(self, content: str):
        return (
            "### Instruction:" in content
            and "### Input:" in content
            and "### Response:" in content
        )


@register_template_identifier
class AlpacaIdentifier(TemplateIdentifier):
    template_str = "Alpaca"

    def __call__(self, content: str):
        """
        {{ system_message }}

        ### Instruction:
        {{ user_message }}

        ### Response:
        {{ coercion_message }}
        """

        return "### Instruction:" in content and "### Response:" in content


@register_template_identifier
class OpenChatIdentifier(TemplateIdentifier):
    template_str = "OpenChat"

    def __call__(self, content: str):
        """
        GPT4 Correct System: {{ system_message }}<|end_of_turn|>GPT4 Correct User: {{ user_message }}<|end_of_turn|>GPT4 Correct Assistant: {{ coercion_message }}
        """

        return (
            "<|end_of_turn|>" in content
            and "GPT4 Correct System:" in content
            and "GPT4 Correct User:" in content
            and "GPT4 Correct Assistant:" in content
        )


@register_template_identifier
class VicunaIdentifier(TemplateIdentifier):
    template_str = "Vicuna"

    def __call__(self, content: str):
        """
        SYSTEM: {{ system_message }}
        USER: {{ user_message }}
        ASSISTANT: {{ coercion_message }}
        """

        return "SYSTEM:" in content and "USER:" in content and "ASSISTANT:" in content


@register_template_identifier
class USER_ASSISTANTIdentifier(TemplateIdentifier):
    template_str = "USER_ASSISTANT"

    def __call__(self, content: str):
        """
        USER: {{ system_message }} {{ user_message }} ASSISTANT: {{ coercion_message }}
        """

        return "USER:" in content and "ASSISTANT:" in content


@register_template_identifier
class UserAssistantIdentifier(TemplateIdentifier):
    template_str = "UserAssistant"

    def __call__(self, content: str):
        """
        User: {{ system_message }} {{ user_message }}
        Assistant: {{ coercion_message }}
        """

        return "User:" in content and "Assistant:" in content


@register_template_identifier
class ZephyrIdentifier(TemplateIdentifier):
    template_str = "Zephyr"

    def __call__(self, content: str):
        """
        <|system|>
        {{ system_message }}</s>
        <|user|>
        {{ user_message }}</s>
        <|assistant|>
        {{ coercion_message }}
        """

        return (
            "<|system|>" in content
            and "<|user|>" in content
            and "<|assistant|>" in content
        )


@register_template_identifier
class Phi3Identifier(TemplateIdentifier):
    template_str = "Phi-3"

    def __call__(self, content: str):
        """
        <|user|>
        {{ system_message }}

        {{ user_message }}<|end|>
        <|assistant|>
        {{ coercion_message }}
        """

        return (
            "<|user|>" in content
            and "<|assistant|>" in content
            and "<|end|>" in content
        )


@register_template_identifier
class GraniteIdentifier(TemplateIdentifier):
    template_str = "Granite"

    def __call__(self, content: str):
        return (
            "<|start_of_role|>" in content
            and "<|end_of_role|>" in content
            and "<|end_of_text|>" in content
        )


@register_template_identifier
class GLMIdentifier(TemplateIdentifier):
    template_str = "GLM"

    def __call__(self, content: str):
        return (
            content.startswith("[gMASK]<sop>")
            and "<|system|>" in content
            and "<|user|>" in content
            and "<|assistant|>" in content
        )
