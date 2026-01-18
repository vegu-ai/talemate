# OpenAI Client

If you want to add an OpenAI client, change the `Client Type` to `OpenAI`.

![Client OpenAI](/talemate/img/0.26.0/client-openai.png)

Click `Save` to add the client.

### OpenAI API Key

The client should appear in the clients list. If you haven't setup OpenAI before, you will see a warning that the API key is missing.

![Client openai no api key](/talemate/img/0.26.0/client-openai-no-api-key.png)

Click the `SET API KEY` button. This will open the api settings window where you can add your OpenAI API key.

For additional instructions on obtaining and setting your OpenAI API key, see [OpenAI API instructions](/talemate/user-guide/apis/openai/).

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
    When OpenAI adds a new model, it may take a Talemate update to add it to the list of available models. However, you can always manually enter any model name in the model field if you know the exact model identifier.

##### Reasoning models (o1, o3, gpt-5)

!!! important "Enable reasoning and allocate tokens"
    The `o1`, `o3`, and `gpt-5` families are reasoning models. They always perform internal thinking before producing the final answer. To use them effectively in Talemate:

    - Enable the **Reasoning** option in the client configuration.
    - Set **Reasoning Tokens** to a sufficiently high value to make room for the model's thinking process.

    A good starting range is 512–1024 tokens. Increase if your tasks are complex. Without enabling reasoning and allocating tokens, these models may return minimal or empty visible content because the token budget is consumed by internal reasoning.

    See the detailed guide: [Reasoning Model Support](/talemate/user-guide/clients/reasoning/).

!!! tip "Getting empty responses?"
    If these models return empty or very short answers, it usually means the reasoning budget was exhausted. Increase **Reasoning Tokens** and try again.