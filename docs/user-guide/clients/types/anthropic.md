# Anthropic Client

If you want to add an Anthropic client, change the `Client Type` to `Anthropic`.

![Client Anthropic](/talemate/img/0.26.0/client-anthropic.png)

Click `Save` to add the client.

### Anthropic API Key

The client should appear in the clients list. If you haven't setup Anthropic before, you will see a warning that the API key is missing.

![Client anthropic no api key](/talemate/img/0.26.0/client-anthropic-no-api-key.png)

Click the `SET API KEY` button. This will open the api settings window where you can add your Anthropic API key.

For additional instructions on obtaining and setting your Anthropic API key, see [Anthropic API instructions](/talemate/user-guide/apis/anthropic/).

![Anthropic settings](/talemate/img/0.26.0/anthropic-settings.png)

Click `Save` and after a moment the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client Anthropic Ready](/talemate/img/0.26.0/client-anthropic-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Which model to use. Currently defaults to `claudr-3.5-sonnet`.

!!! note "Talemate lags behind Anthropic"
    When Anthropic adds a new model, it may take a Talemate update to add it to the list of available models. However, you can always manually enter any model name in the model field if you know the exact model identifier.