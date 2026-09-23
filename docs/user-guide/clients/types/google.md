# Google Client

If you want to add an Google client, go to **Settings → Connections → Clients**, click **:material-plus-box: Add client** and pick `Google` from the client type menu.

![Client Google](/talemate/img/0.40.0/client-google.png)

Click `Save` in the toolbar to add the client.

### Google Cloud Credentials

The client should appear in the clients list. If you haven't setup Google before, you will see a warning that the API credentials are missing.

![Client google no api key](/talemate/img/0.40.0/client-google-creds-missing.png)

Click the `SETUP GOOGLE API CREDENTIALS` button. This will open the application settings on the API Keys page where you can add your Google API credentials.

For additional instructions on obtaining and setting your Google API credentials, see [Google API instructions](/talemate/user-guide/apis/google/).

![Google settings](/talemate/img/0.39.0/api-keys-google.png)

Click `Save` and after a moment the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client Google Ready](/talemate/img/0.26.0/client-google-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Which model to use. Currently defaults to `gemini-3.7-flash`.

!!! note "Talemate lags behind Google"
    When Google adds a new model, it may take a Talemate update to add it to the list of available models. However, you can always manually enter any model name in the model field if you know the exact model identifier.

##### Context Length

Maximum context length (in tokens) for generations sent to Google. If you are not sure, leave the default value.

##### Concurrent Inference

Found in the **Concurrency** section of the client editor. When enabled, batch operations that need several queries can send multiple requests to the Google API in parallel instead of one at a time, which can speed those operations up.

This is **on by default**. See the [Concurrent Requests](/talemate/user-guide/clients/concurrent-requests/) page for more detail.

##### Disable Safety Settings

Will turn off the google reponse validation for what they consider harmful content. Use at your own risk.
--8<-- "docs/snippets/common.md:client-response-length"
