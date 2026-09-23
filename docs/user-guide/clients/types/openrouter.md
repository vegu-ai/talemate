# OpenRouter Client

If you want to add an OpenRouter client, go to **Settings → Connections → Clients**, click **:material-plus-box: Add client** and pick `OpenRouter` from the client type menu.

![Client OpenRouter](/talemate/img/0.40.0/client-openrouter.png)

Click `Save` in the toolbar to add the client.

### OpenRouter API Key

The client should appear in the clients list. If you haven't set up OpenRouter before, you will see a warning that the API key is missing.

![Client openrouter no api key](/talemate/img/0.31.0/client-openrouter-no-api-key.png)

Click the `SET API KEY` button. This will open the application settings on the API Keys page where you can add your OpenRouter API key.

For additional instructions on obtaining and setting your OpenRouter API key, see [OpenRouter API instructions](/talemate/user-guide/apis/openrouter/).

![OpenRouter settings](/talemate/img/0.39.0/api-keys-openrouter.png)

!!! info "The API key is in the client editor too"
    The **OpenRouter API Key** card sits in the **General** section of the client editor, so you can paste your key there instead of going to the API Keys page. It is the same key either way.

Click `Save` and after a moment the client should have a red dot next to it, saying that there is no model loaded.

Click the :material-cogs: icon to go to the client's editor on the Clients settings page and select a model.

![OpenRouter select model](/talemate/img/0.40.0/client-openrouter-select-model.png).

Click save and the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client OpenRouter Ready](/talemate/img/0.31.0/client-openrouter-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Choose any model available via your OpenRouter account. Talemate dynamically fetches the list of models associated with your API key so new models will show up automatically.

##### Context Length

Maximum context length (in tokens) that OpenRouter should consider. If you are not sure leave the default value.

##### Concurrent Inference

Found in the **Concurrency** section of the client editor. When enabled, batch operations that need several queries can send multiple requests to OpenRouter in parallel instead of one at a time, which can speed those operations up.

This is **on by default**. See the [Concurrent Requests](/talemate/user-guide/clients/concurrent-requests/) page for more detail.

!!! note "Available models are fetched automatically"
    Talemate fetches the list of available OpenRouter models when you save the configuration (if a valid API key is present). If you add or remove models to your account later, simply click **Save** in the application settings again to refresh the list. 

### Reasoning

New OpenRouter clients start with reasoning on and 2048 **Reasoning Tokens**. A client you saved before keeps its own setting. Turn **Reasoning** on or off in the **Reasoning** section of the client editor, or with the :material-brain: button on the client card.

With reasoning on, Talemate asks OpenRouter to let the model think first, with a budget set by **Reasoning Tokens** (at least 256). With reasoning off, Talemate sends no reasoning request at all, and the card shows a **Reasoning Disabled** chip. A model that thinks only when asked, such as Claude Haiku 4.5, then answers straight away. A model that always thinks, such as Gemini 3.8 Flash, still thinks by its own default.

You can keep reasoning on when you pick a model that cannot think. OpenRouter ignores the reasoning request for such a model, and the model answers as usual.

!!! warning "Keep reasoning on for Google models"
    With reasoning off, Talemate may pre-fill the start of the answer to steer the model. Google models on OpenRouter refuse such requests with an error, so keep reasoning on for them.

!!! note "Changed in 0.40.0"
    Before 0.40.0, Talemate sent the reasoning budget even with reasoning off, so a model such as Claude still thought. If you liked those answers, turn reasoning on.

### Parameters

The **Parameters** section of the client editor lets you control which sampler parameters are sent with each request. Some model providers on OpenRouter reject requests that include parameters they don't support for the selected model, returning an error instead of a generation. If you run into this, you can turn the offending parameter off so it is left out of the request entirely.

Each parameter has its own toggle:

- **Send temperature**
- **Send top_p**
- **Send top_k**
- **Send min_p**
- **Send frequency_penalty**
- **Send presence_penalty**
- **Send repetition_penalty**

All of them are enabled by default. Turning a toggle off omits that parameter from the request completely (it is not sent as a zero value). Leave them enabled unless the provider serving your model errors when it receives one of them — for example, some providers only accept a `frequency_penalty` or `presence_penalty` of exactly `0` for certain models.
--8<-- "docs/snippets/common.md:client-response-length"
