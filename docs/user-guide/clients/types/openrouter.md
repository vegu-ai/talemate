# OpenRouter Client

If you want to add an OpenRouter client, change the `Client Type` to `OpenRouter`.

![Client OpenRouter](/talemate/img/0.31.0/client-openrouter.png)

Click `Save` to add the client.

### OpenRouter API Key

The client should appear in the clients list. If you haven't set up OpenRouter before, you will see a warning that the API key is missing.

![Client openrouter no api key](/talemate/img/0.31.0/client-openrouter-no-api-key.png)

Click the `SET API KEY` button. This will open the API settings window where you can add your OpenRouter API key.

For additional instructions on obtaining and setting your OpenRouter API key, see [OpenRouter API instructions](/talemate/user-guide/apis/openrouter/).

![OpenRouter settings](/talemate/img/0.31.0/openrouter-settings.png)

Click `Save` and after a moment the client should have a red dot next to it, saying that there is no model loaded.

Click the :material-cogs: icon to open the client settings and select a model.

![OpenRouter select model](/talemate/img/0.31.0/client-openrouter-select-model.png).

Click save and the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client OpenRouter Ready](/talemate/img/0.31.0/client-openrouter-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Choose any model available via your OpenRouter account. Talemate dynamically fetches the list of models associated with your API key so new models will show up automatically.

##### Max token length

Maximum context length (in tokens) that OpenRouter should consider. If you are not sure leave the default value.

!!! note "Available models are fetched automatically"
    Talemate fetches the list of available OpenRouter models when you save the configuration (if a valid API key is present). If you add or remove models to your account later, simply click **Save** in the application settings again to refresh the list. 