# Groq Client

If you want to add an Groq client, go to **Settings → Connections → Clients**, click **:material-plus-box: Add client** and pick `Groq` from the client type menu.

![Client Groq](/talemate/img/0.40.0/client-groq.png)

Click `Save` in the toolbar to add the client.

### Groq API Key

The client should appear in the clients list. If you haven't setup Groq before, you will see a warning that the API key is missing.

![Client groq no api key](/talemate/img/0.40.0/client-groq-no-api-key.png)

Click the `SET API KEY` button. This will open the application settings on the API Keys page where you can add your Groq API key.

For additional instructions on obtaining and setting your Groq API key, see [Groq API instructions](/talemate/user-guide/apis/groq/).

![Groq settings](/talemate/img/0.39.0/api-keys-groq.png)

Click `Save` and after a moment the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client Groq Ready](/talemate/img/0.26.0/client-groq-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Which model to use. Currently defaults to `moonshotai/kimi-k2-instruct`.

!!! note "Talemate lags behind Groq"
    When Groq adds a new model, it may take a Talemate update to add it to the list of available models. However, you can always manually enter any model name in the model field if you know the exact model identifier.

##### Context Length

Maximum context length (in tokens) for generations sent to Groq. If you are not sure, leave the default value.
--8<-- "docs/snippets/common.md:client-response-length"
