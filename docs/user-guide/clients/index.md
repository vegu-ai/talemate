# Overview

Talemate uses client(s) to connect to local or remote AI text generation APIs like koboldcpp, text-generation-webui or OpenAI.

The various [agents](/user-guide/agents/) will use these connections to generate content.

## Why multiple clients?

Unlike other, similar projects, Talemate supports and encourages use of multiple clients. We belief it makes sense to give certain tasks to certain models. Some models may be more suited for for management tasks, while others may be better at creative tasks. 

It is however, perfectly fine to just use a single client for all tasks if you prefer.

## Officially supported APIs

##### Remote APIs

- [OpenAI](/user-guide/clients/types/openai/)
- [Anthropic](/user-guide/clients/types/anthropic/)
- [mistral.ai](/user-guide/clients/types/mistral/)
- [Cohere](/user-guide/clients/types/cohere/)
- [Groq](/user-guide/clients/types/groq/)
- [Google Gemini](/user-guide/clients/types/google/)

##### Local APIs

- [KoboldCpp](/user-guide/clients/types/koboldcpp/)
- [Text-Generation-WebUI](/user-guide/clients/types/text-generation-webui/) 
- [LMStudio](/user-guide/clients/types/lmstudio/)

## APIs functional via OpenAI compatible client

!!! note
    These APIs do not have a talemate client, but the OpenAI compatible client can be used to connect to them.

- [DeepInfra](/user-guide/clients/types/openai-compatible/#deepinfra)
- llamacpp with the `api_like_OAI.py` wrapper