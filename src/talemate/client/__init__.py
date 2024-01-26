import os
from talemate.client.openai import OpenAIClient
from talemate.client.registry import CLIENT_CLASSES, get_client_class, register
from talemate.client.textgenwebui import TextGeneratorWebuiClient
from talemate.client.lmstudio import LMStudioClient
from talemate.client.openai_compat import OpenAICompatibleClient
import talemate.client.runpod
