# Ollama Client

If you want to add an Ollama client, change the `Client Type` to `Ollama`.

![Client Ollama](/talemate/img/0.31.0/client-ollama.png)

Click `Save` to add the client.

### Ollama Server

The client should appear in the clients list. Talemate will ping the Ollama server to verify that it is running. If the server is not reachable you will see a warning.

![Client ollama offline](/talemate/img/0.31.0/client-ollama-offline.png)

Make sure that the Ollama server is running (by default at `http://localhost:11434`) and that the model you want to use has been pulled.

It may also show a yellow dot next to it, saying that there is no model loaded.

![Client ollama no model](/talemate/img/0.31.0/client-ollama-no-model.png)

Open the client settings by clicking the :material-cogs: icon, to select a model.

![Ollama settings](/talemate/img/0.31.0/client-ollama-select-model.png)

Click save and the client should have a green dot next to it, indicating that it is ready to go.

![Client ollama ready](/talemate/img/0.31.0/client-ollama-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### API URL

The base URL where the Ollama HTTP endpoint is running. Defaults to `http://localhost:11434`.

##### Model

Name of the Ollama model to use. Talemate will automatically fetch the list of models that are currently available in your local Ollama instance.

##### API handles prompt template

If enabled, Talemate will send the raw prompt and let Ollama apply its own built-in prompt template. If you are unsure leave this disabled – Talemate's own prompt template generally produces better results.

##### Allow thinking

If enabled Talemate will allow models that support "thinking" (`assistant:thinking` messages) to deliberate before forming the final answer. At the moment Talemate has limited support for this feature when talemate is handling the prompt template. Its probably ok to turn it on if you let Ollama handle the prompt template.

!!! tip
    You can quickly refresh the list of models by making sure the Ollama server is running and then hitting **Save** again in the client settings. 

### Common issues

#### Generations are weird / bad

If letting talemate handle the prompt template, make sure the [correct prompt template is assigned](/talemate/user-guide/clients/prompt-templates/).

