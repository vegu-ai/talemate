# Connect a client

!!! note "First time setup?"
    If this is your first time launching Talemate, the [Setup Wizard](setup-wizard.md) will guide you through adding your first client and configuring essential settings. This page covers manual client configuration for adding additional clients or if you skipped the wizard.

Once Talemate is up and running and you are connected, the Home screen shows a warning at the top while no client is configured, reminding you that all enabled clients and agents need to be configured before you can load scenes.

Talemate uses client(s) to connect to local or remote AI text generation APIs like koboldcpp, text-generation-webui or OpenAI.

!!! note "Which model?"
    Talemate expects a current reasoning model with reliable structured output and 16k or more context. See [Model expectations](model-expectations.md) for the bar, known good examples and what still works with an older model.

## Add a new client

On the right hand side click the **:material-plus-box: ADD CLIENT** button. 

![connect a client add client](/talemate/img/0.26.0/connect-a-client-add-client.png)

!!! note "No button?"
    If there is no button, you may need to toggle the client options by clicking this button

    ![open clients](/talemate/img/0.26.0/open-clients.png)

This takes you to **Settings → Connections → Clients** with the **Client type** menu open. Pick the type of client you want to add and it is created right away, with its editor next to the list.

![connect a client add client](/talemate/img/0.40.0/connect-a-client-add-client.png)

Fill in the client's settings and click **:material-check-circle-outline: Save** in the toolbar at the top to apply them. Nothing is connected until you save.

## Choose an API / Client Type

We have support for multiple local and remote APIs. You can choose to use one or more of them.

!!! note "Local vs remote"
    A local API runs on your machine, while a remote API runs on a server somewhere else. 

Select the API you want to use and click through to follow the instructions to configure a client for it:

##### Remote APIs

- [OpenAI](/talemate/user-guide/clients/types/openai/)
- [Anthropic](/talemate/user-guide/clients/types/anthropic/)
- [mistral.ai](/talemate/user-guide/clients/types/mistral/)
- [Cohere](/talemate/user-guide/clients/types/cohere/)
- [DeepSeek](/talemate/user-guide/clients/types/deepseek/)
- [Groq](/talemate/user-guide/clients/types/groq/)
- [Google Gemini](/talemate/user-guide/clients/types/google/)
- [OpenRouter](/talemate/user-guide/clients/types/openrouter/)
- [Pi Bridge](/talemate/user-guide/clients/types/pi-bridge/) — any provider reachable through a local [pi coding agent](https://github.com/earendil-works/pi) install

##### Local APIs

- [KoboldCpp](/talemate/user-guide/clients/types/koboldcpp/)
- [llama.cpp](/talemate/user-guide/clients/types/llamacpp/)
- [Ollama](/talemate/user-guide/clients/types/ollama/)
- [Text-Generation-WebUI](/talemate/user-guide/clients/types/text-generation-webui/)
- [LMStudio](/talemate/user-guide/clients/types/lmstudio/)
- [TabbyAPI](/talemate/user-guide/clients/types/tabbyapi/)

##### Unofficial OpenAI API implementations

- [DeepInfra](/talemate/user-guide/clients/types/openai-compatible/#deepinfra)

## Assign the client to the agents

Whenever you add your first client, Talemate will automatically assign it to all agents. Once the client is configured and assigned, all agents should have a green dot next to them. (Or grey if the agent is currently disabled)

![Connect a client assigned](/talemate/img/0.30.0/connect-a-client-ready.png)

You can tell the client is assigned to the agent by checking the tag beneath the agent name, which will contain the client name if it is assigned.

![Agent has client assigned](/talemate/img/0.26.0/agent-has-client-assigned.png)

## Its not assigned!

If for some reason the client is not assigned to the agent, you can manually assign it to all agents by clicking the **:material-transit-connection-variant: Assign to all agents** button.

![Connect a client assign to all agents](/talemate/img/0.26.0/connect-a-client-assign-to-all-agents.png)

The same action is available on the [Clients settings page](/talemate/user-guide/clients/client-configuration/), above the client editor. There it is applied when you save, and it is disabled while the client itself is disabled — enable the client first.