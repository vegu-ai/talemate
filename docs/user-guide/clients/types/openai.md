# OpenAI Client

If you want to add an OpenAI client, change the `Client Type` to `OpenAI`.

![Client OpenAI](/talemate/img/0.26.0/client-openai.png)

Click `Save` to add the client.

### OpenAI API Key

The client should appear in the clients list. If you haven't setup OpenAI before, you will see a warning that the API key is missing.

![Client openai no api key](/talemate/img/0.26.0/client-openai-no-api-key.png)

Click the `SET API KEY` button. This will open the api settings window where you can add your OpenAI API key.

For additional instructions on obtaining and setting your OpenAI API key, see [OpenAI API instructions](/user-guide/apis/openai/).

![OpenAI settings](/talemate/img/0.26.0/openai-settings.png)

Click `Save` and after a moment the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client OpenAI Ready](/talemate/img/0.26.0/client-openai-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Which model to use. Currently defaults to `gpt-4o`.

!!! note "Talemate lags behind OpenAI"
    When OpenAI adds a new model, it currently requires a Talemate update to add it to the list of available models. We are working on making this more dynamic.