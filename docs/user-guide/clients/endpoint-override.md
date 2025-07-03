# Endpoint Override

Starting in version 0.31.0 it is now possible for some of the remote clients to override the endpoint used for the API.

THis is helpful wehn you want to point the client at a proxy gateway to serve the api instead (LiteLLM for example).

!!! warning "Only use trusted endpoints"
    Only use endpoints that you trust and NEVER used your actual API key with them, unless you are hosting your endpoint proxy yourself.

    If you need to provide an api key there is a separate field for that specifically in the endpoint override settings.

## How to use

Clients that support it will have a tab in their settings that allows you to override the endpoint.

![Endpoint Override](/talemate/img/0.31.0/client-endpoint-override.png)

##### Base URL

The base URL of the endpoint. For example, `http://localhost:4000` if you're running a local LiteLLM gateway,

##### API Key

The API key to use for the endpoint. This is only required if the endpoint requires an API key. This is **NOT** the API key you would use for the official API. For LiteLLM for example this could be the `general_settings.master_key` value.