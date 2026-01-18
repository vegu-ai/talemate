# Overview

Talemate uses client(s) to connect to local or remote AI text generation APIs like koboldcpp, text-generation-webui or OpenAI.

The various [agents](/talemate/user-guide/agents/) will use these connections to generate content.

## Why multiple clients?

Talemate supports and encourages use of multiple clients. We believe it makes sense to give certain tasks to certain models. Some models may be more suited for for management tasks, while others may be better at creative tasks. 

It is, however, perfectly fine to just use a single client for all tasks if you prefer.

## Client setup instructions

### Officially supported APIs

##### Remote APIs

- [OpenAI](/talemate/user-guide/clients/types/openai/)
- [Anthropic](/talemate/user-guide/clients/types/anthropic/)
- [mistral.ai](/talemate/user-guide/clients/types/mistral/)
- [Cohere](/talemate/user-guide/clients/types/cohere/)
- [Groq](/talemate/user-guide/clients/types/groq/)
- [Google Gemini](/talemate/user-guide/clients/types/google/)

##### Local APIs

- [KoboldCpp](/talemate/user-guide/clients/types/koboldcpp/)
- [llama.cpp](/talemate/user-guide/clients/types/llamacpp/)
- [Text-Generation-WebUI](/talemate/user-guide/clients/types/text-generation-webui/)
- [LMStudio](/talemate/user-guide/clients/types/lmstudio/)

### APIs functional via OpenAI compatible client

!!! note
    These APIs do not have a talemate client, but the OpenAI compatible client can be used to connect to them.

- [DeepInfra](/talemate/user-guide/clients/types/openai-compatible/#deepinfra)