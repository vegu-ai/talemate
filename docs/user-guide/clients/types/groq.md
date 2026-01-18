# Groq Client

If you want to add an Groq client, change the `Client Type` to `Groq`.

![Client Groq](/talemate/img/0.26.0/client-groq.png)

Click `Save` to add the client.

### Groq API Key

The client should appear in the clients list. If you haven't setup Groq before, you will see a warning that the API key is missing.

![Client groq no api key](/talemate/img/0.26.0/client-groq-no-api-key.png)

Click the `SET API KEY` button. This will open the api settings window where you can add your Groq API key.

For additional instructions on obtaining and setting your Groq API key, see [Groq API instructions](/talemate/user-guide/apis/groq/).

![Groq settings](/talemate/img/0.26.0/groq-settings.png)

Click `Save` and after a moment the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client Groq Ready](/talemate/img/0.26.0/client-groq-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Which model to use. Currently defaults to `llama3-70b-8192`.

!!! note "Talemate lags behind Groq"
    When Groq adds a new model, it may take a Talemate update to add it to the list of available models. However, you can always manually enter any model name in the model field if you know the exact model identifier.