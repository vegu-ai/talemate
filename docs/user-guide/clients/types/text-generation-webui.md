# Text-Generation-WebUI Client

!!! abstract "This requires you to have a Text-Generation-WebUI instance running"
    If you do not have a Text-Generation-WebUI instance running, you can follow their setup instructions 
    in their [GitHub repository](https://github.com/oobabooga/text-generation-webui).

If you want to add an Text-Generation-WebUI client, change the `Client Type` to `Text-Generation-WebUI (ooba)`.

![Client Text-Generation-WebUI](/talemate/img/0.26.0/client-ooba.png)

!!! note "Should work out of the box with a local Text-Generation-WebUI instance"
    The default values should work with a local Text-Generation-WebUI instance if you have followed their setup instructions and are running the server on the default port.

Click `Save` to add the client.

### Ready to use

Once it is added, the client should appear in the clients list and should display the currently loaded model.

![Client Text-Generation-WebUI Ready](/talemate/img/0.26.0/client-ooba-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### API Url

The URL of your Text-Generation-WebUI instance, without any path. For example, `http://localhost:5000`.

##### API Key

If the Text-Generation-WebUI instance requires an API key, you can set it here.

##### Context Length

The number of tokens to use as context when generating text. Defaults to `8192`.

### Common issues

#### Generations are weird / bad

Make sure the [correct prompt template is assigned](/talemate/user-guide/clients/prompt-templates/).

#### No model loaded

![Client ooba no model loaded](/talemate/img/0.26.0/client-ooba-no-model-loaded.png)

If your client displays a `No model loaded` message, it means that you haven't loaded a model yet. Go to your Text-Generation-WebUI instance and load a model.

#### Could not connect

![Client ooba could not connect](/talemate/img/0.26.0/client-ooba-could-not-connect.png)

This means that either your Text-Generation-WebUI instance is not running, the url is incorrect, or the connection is somehow blocked. (For example, by a firewall)