import json
import os
import shutil
import tempfile

import huggingface_hub
import structlog
from jinja2 import Environment, FileSystemLoader

__all__ = ["model_prompt"]

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

# llm prompt templates provided by talemate
TALEMATE_TEMPLATE_PATH = os.path.join(BASE_TEMPLATE_PATH, "talemate")

# user overrides
USER_TEMPLATE_PATH = os.path.join(BASE_TEMPLATE_PATH, "user")

TEMPLATE_IDENTIFIERS = []


def register_template_identifier(cls):
    TEMPLATE_IDENTIFIERS.append(cls)
    return cls


log = structlog.get_logger("talemate.model_prompts")


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
        env = Environment(loader=FileSystemLoader(STD_TEMPLATE_PATH))
        return sorted(env.list_templates())

    def __call__(
        self,
        model_name: str,
        system_message: str,
        prompt: str,
        double_coercion: str = None,
    ):
        template, template_file = self.get_template(model_name)
        if not template:
            template_file = "default.jinja2"
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

        return (
            template.render(
                {
                    "system_message": system_message,
                    "prompt": prompt.strip(),
                    "user_message": user_message.strip(),
                    "coercion_message": coercion_message,
                    "set_response": lambda prompt, response_str: self.set_response(
                        prompt, response_str, double_coercion
                    ),
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

    def get_template(self, model_name: str):
        """
        Will attempt to load an LLM prompt template - this supports
        partial filename matching on the template file name.
        """

        matches = []

        cleaned_model_name = model_name.replace("/", "__")

        # Iterate over all templates in the loader's directory
        for template_name in self.env.list_templates():
            # strip extension
            template_name_match = os.path.splitext(template_name)[0]
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
        Will copy STD_TEMPLATE_PATH/template_name to USER_TEMPLATE_PATH/model_name.jinja2
        """

        template_name = template_name.split(".jinja2")[0]

        cleaned_model_name = model_name.replace("/", "__")

        shutil.copyfile(
            os.path.join(STD_TEMPLATE_PATH, template_name + ".jinja2"),
            os.path.join(USER_TEMPLATE_PATH, cleaned_model_name + ".jinja2"),
        )

        return os.path.join(USER_TEMPLATE_PATH, cleaned_model_name + ".jinja2")

    def query_hf_for_prompt_template_suggestion(self, model_name: str):
        api = huggingface_hub.HfApi()

        try:
            author, model_name = model_name.split("_", 1)
        except ValueError:
            return None

        branch_name = "main"

        # special popular cases

        # bartowski

        if author == "bartowski" and "exl2" in model_name:
            # split model_name by exl2 and take the first part with "exl2" readded
            # the second part is the branch name
            model_name, branch_name = model_name.split("exl2_", 1)
            model_name = f"{model_name}exl2"

        models = list(api.list_models(model_name=model_name, author=author))

        if not models:
            return None

        model = models[0]

        repo_id = f"{author}/{model_name}"

        # Check README.md
        with tempfile.TemporaryDirectory() as tmpdir:
            readme_path = huggingface_hub.hf_hub_download(
                repo_id=repo_id,
                filename="README.md",
                cache_dir=tmpdir,
                revision=branch_name,
            )
            if not readme_path:
                return None
            with open(readme_path) as f:
                readme = f.read()
                for identifer_cls in TEMPLATE_IDENTIFIERS:
                    identifier = identifer_cls()
                    if identifier(readme):
                        return f"{identifier.template_str}.jinja2"

        # Check tokenizer_config.json
        # "chat_template" key
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = huggingface_hub.hf_hub_download(
                repo_id=repo_id,
                filename="tokenizer_config.json",
                cache_dir=tmpdir,
                revision=branch_name,
            )
            if not config_path:
                return None
            with open(config_path) as f:
                config = json.load(f)
                for identifer_cls in TEMPLATE_IDENTIFIERS:
                    identifier = identifer_cls()
                    if identifier(config.get("chat_template", "")):
                        return f"{identifier.template_str}.jinja2"


model_prompt = ModelPrompt()


class TemplateIdentifier:
    def __call__(self, content: str):
        return False


@register_template_identifier
class Llama2Identifier(TemplateIdentifier):
    template_str = "Llama2"

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
