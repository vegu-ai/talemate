# LMStudio Client
`Last tested with LMStudio 0.2.26`

!!! abstract "This requires you to have a LMStudio instance running"
    If you do not have a LMStudio instance running, you can follow their setup instructions 
    in their [website](https://lmstudio.ai/).

If you want to add an LMStudio client, change the `Client Type` to `LMStudio`.

![Client LMStudio](/talemate/img/0.26.0/client-lmstudio.png)

!!! note "Should work out of the box with a local LMStudio instance"
    The default values should work with a local LMStudio instance if you have followed their setup instructions and are running the server on the default port.

Click `Save` to add the client.

### Ready to use

Once it is added, the client should appear in the clients list and should display the currently loaded model.

![Client LMStudio Ready](/talemate/img/0.26.0/client-lmstudio-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### API Url

The URL of your LMStudio instance, without any path. For example, `http://localhost:1234`.

##### API Key

If the LMStudio instance requires an API key, you can set it here.

##### Context Length

The number of tokens to use as context when generating text. Defaults to `8192`.

### Common issues

#### Generations are weird / bad

Make sure the [correct prompt template is assigned](/user-guide/clients/prompt-templates/).

#### Could not connect

![Client lmstudio could not connect](/talemate/img/0.26.0/client-lmstudio-could-not-connect.png)

This means that either your LMStudio instance or server is not running, the url is incorrect, or the connection is somehow blocked. (For example, by a firewall)

Its not enough to just start LMStudio, you need to also start the server from within the application once you have started LMStudio.