# Connect a client

!!! note "First time setup?"
    If this is your first time launching Talemate, the [Setup Wizard](setup-wizard.md) will guide you through adding your first client and configuring essential settings. This page covers manual client configuration for adding additional clients or if you skipped the wizard.

Once Talemate is up and running and you are connected, you will see a notification in the corner instructing you to configured a client.

![no clients](/talemate/img/0.26.0/no-clients.png)

Talemate uses client(s) to connect to local or remote AI text generation APIs like koboldcpp, text-generation-webui or OpenAI.

## Add a new client

On the right hand side click the **:material-plus-box: ADD CLIENT** button. 

![connect a client add client](/talemate/img/0.26.0/connect-a-client-add-client.png)

!!! note "No button?"
    If there is no button, you may need to toggle the client options by clicking this button

    ![open clients](/talemate/img/0.26.0/open-clients.png)

The client configuration window will appear. Here you can choose the type of client you want to add.

![connect a client add client modal](/talemate/img/0.30.0/connect-a-client-add-client-modal.png)

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