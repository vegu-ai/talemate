# Google Client

If you want to add an Google client, change the `Client Type` to `Google`.

![Client Google](/talemate/img/0.26.0/client-google.png)

Click `Save` to add the client.

### Google Cloud Credentials

The client should appear in the clients list. If you haven't setup Google before, you will see a warning that the API credentials are missing.

![Client google no api key](/talemate/img/0.26.0/client-google-creds-missing.png)

Click the `SETUP GOOGLE API CREDENTIALS` button. This will open the api settings window where you can add your Google API credentials.

For additional instructions on obtaining and setting your Google API credentials, see [Google API instructions](/talemate/user-guide/apis/google/).

![Google settings](/talemate/img/0.26.0/google-settings.png)

Click `Save` and after a moment the client should have a green dot next to it, indicating that it is ready to go.

### Ready to use

![Client Google Ready](/talemate/img/0.26.0/client-google-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Model

Which model to use. Currently defaults to `gemini-1.0`.

!!! note "Talemate lags behind Google"
    When Google adds a new model, it may take a Talemate update to add it to the list of available models. However, you can always manually enter any model name in the model field if you know the exact model identifier.


##### Disable Safety Settings

Will turn off the google reponse validation for what they consider harmful content. Use at your own risk.