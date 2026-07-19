# Mistral.ai Client

If you want to add an Mistral.ai client, change the `Client Type` to `Mistral.ai`.

![Client Mistral.ai](/talemate/img/0.26.0/client-mistral.png)

Click `Save` to add the client.

### Mistral.ai API Key

The client should appear in the clients list. If you haven't setup Mistral.ai before, you will see a warning that the API key is missing.

![Client mistral no api key](/talemate/img/0.26.0/client-mistral-no-api-key.png)

Click the `SET API KEY` button. This will open the application settings on the API Keys page where you can add your Mistral.ai API key.

For additional instructions on obtaining and setting your Mistral.ai API key, see [Mistral.ai API instructions](/talemate/user-guide/apis/mistral/).

![Mistral.ai settings](/talemate/img/0.39.0/api-keys-mistral.png)

Click `Save` and after a moment the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client Mistral.ai Ready](/talemate/img/0.26.0/client-mistral-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Which model to use. Currently defaults to `mixtral-8x22`.

!!! note "Talemate lags behind Mistral.ai"
    When Mistral.ai adds a new model, it may take a Talemate update to add it to the list of available models. However, you can always manually enter any model name in the model field if you know the exact model identifier.

##### Concurrent Inference

Found under the **Concurrency** tab in the client settings. When enabled, batch operations that need several queries (currently visual prompt generation for image generation) can send multiple requests to the Mistral.ai API in parallel instead of one at a time, which can speed those operations up.

This is **off by default**. Whether concurrent requests actually complete in parallel depends on your Mistral.ai account's rate limits. See the [Concurrent Requests](/talemate/user-guide/clients/concurrent-requests/) page for more detail.
--8<-- "docs/snippets/common.md:client-response-length"
