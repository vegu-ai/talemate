# Overview

Talemate uses client(s) to connect to local or remote AI text generation APIs like koboldcpp, text-generation-webui or OpenAI.

The various [agents](/user-guide/agents/) will use these connections to generate content.

## Why multiple clients?

Unlike other, similar projects, Talemate supports and encourages use of multiple clients. We belief it makes sense to give certain tasks to certain models. Some models may be more suited for for management tasks, while others may be better at creative tasks. 

It is however, perfectly fine to just use a single client for all tasks if you prefer.