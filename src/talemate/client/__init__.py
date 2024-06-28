import os

import talemate.client.runpod
from talemate.client.anthropic import AnthropicClient
from talemate.client.cohere import CohereClient
from talemate.client.google import GoogleClient
from talemate.client.groq import GroqClient
from talemate.client.koboldcpp import KoboldCppClient
from talemate.client.lmstudio import LMStudioClient
from talemate.client.mistral import MistralAIClient
from talemate.client.openai import OpenAIClient
from talemate.client.openai_compat import OpenAICompatibleClient
from talemate.client.tabbyapi import TabbyAPIClient
from talemate.client.registry import CLIENT_CLASSES, get_client_class, register
from talemate.client.textgenwebui import TextGeneratorWebuiClient
from talemate.client.base import ClientBase, ClientDisabledError
