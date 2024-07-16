# TabbyAPI Client

!!! abstract "This requires you to have a TabbyAPI instance running"
    If you do not have a TabbyAPI instance running, you can follow their setup instructions 
    in their [GitHub Repository](https://github.com/theroyallab/tabbyAPI).

If you want to add a TabbyAPI client, change the `Client Type` to `TabbyAPI`.

![Client TabbyAPI](/talemate/img/0.26.0/client-tabbyapi.png)

!!! note "Should work out of the box with a local TabbyAPI instance"
    The default values should work with a local TabbyAPI instance if you have followed their setup instructions and are running the server on the default port.

Click `Save` to add the client.

### Ready to use

Once it is added, the client should appear in the clients list and should display the currently loaded model.

![Client TabbyAPI Ready](/talemate/img/0.26.0/client-tabbyapi-ready.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### API Url

The URL of your TabbyAPI instance, without any path. For example, `http://localhost:5000/v1`.

##### API Key

If the TabbyAPI instance requires an API key, you can set it here.

##### API handles prompt template

This will cause requests to go to the chat/completions API instead and TabbyAPI will be in control of the prompt template. This means if you enable this TabbyAPI needs to be configured correctly and Talemate will also lose control of the prompt template, causing a likely loss in quality.

This setting is recommended to keep disabled.

##### Context Length

The number of tokens to use as context when generating text. Defaults to `8192`.

### Common issues

#### Generations are weird / bad

Make sure the [correct prompt template is assigned](/user-guide/clients/prompt-templates/).

#### Could not connect

![Client tabbyapi could not connect](/talemate/img/0.26.0/client-tabbyapi-could-not-connect.png)

Possible reasons:

- TabbyAPI instance is not running
- the API url is incorrect
- the API key is incorrect
- the connection is somehow blocked. (For example, by a firewall)