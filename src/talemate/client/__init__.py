from talemate.client.anthropic import AnthropicClient  # noqa: F401
from talemate.client.base import ClientBase, ClientDisabledError  # noqa: F401
from talemate.client.cohere import CohereClient  # noqa: F401
from talemate.client.deepseek import DeepSeekClient  # noqa: F401
from talemate.client.google import GoogleClient  # noqa: F401
from talemate.client.groq import GroqClient  # noqa: F401
from talemate.client.koboldcpp import KoboldCppClient  # noqa: F401
from talemate.client.llamacpp import LlamaCppClient  # noqa: F401
from talemate.client.lmstudio import LMStudioClient  # noqa: F401
from talemate.client.mistral import MistralAIClient  # noqa: F401
from talemate.client.ollama import OllamaClient  # noqa: F401
from talemate.client.openai import OpenAIClient  # noqa: F401
from talemate.client.openrouter import OpenRouterClient  # noqa: F401
from talemate.client.openai_compat import OpenAICompatibleClient  # noqa: F401
from talemate.client.registry import CLIENT_CLASSES, get_client_class, register  # noqa: F401
from talemate.client.tabbyapi import TabbyAPIClient  # noqa: F401
from talemate.client.textgenwebui import TextGeneratorWebuiClient  # noqa: F401
