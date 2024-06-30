# OpenAI Compatible Client

Allows you to use Talemate with a service that exposes an openai-like API.

!!! warning "Use the officual client if it is available"
    Only use this if the service you are trying access doen't already have official support from Talemate.
    All the officially supported clients can be found [here](/user-guide/clients/).

## DeepInfra

If you want to add a DeepInfra client, change the `Client Type` to `DeepInfra`.

![Client DeepInfra](/img/0.26.0/client-deepinfra.png)

### Settings

##### Client Name

A unique name for the client that makes sense to you.

##### API Url

The URL of DeepInfra's openai api - currently `https://api.deepinfra.com/v1/openai`

##### API Key

Your DeepInfra api key. You can manage your DeepInfra API keys at [https://deepinfra.com/dash/api_keys](https://deepinfra.com/dash/api_keys)

##### API handles prompt template

This will cause requests to go to the chat/completions API instead and DeepInfra will be in control of the prompt template. This means if you enable this DeepInfra needs to be configured correctly and Talemate will also lose control of the prompt template, causing a likely loss in quality.

This setting is recommended to keep disabled.

##### Model name

Currently you need to manually specify which model to use by typing its name as it exists on deepinfra.com.

Decent choices:

```{ .copy }
microsoft/WizardLM-2-8x22B
```

```{ .copy }
nvidia/Nemotron-4-340B-Instruct
```

```{ .copy }
meta-llama/Meta-Llama-3-70B-Instruct
```

```{ .copy }
mistralai/Mixtral-8x22B-Instruct-v0.1
```

##### Context Length

The number of tokens to use as context when generating text. Defaults to `8192`.

### Ready to use

Click `Save` to add the client.

Once it is added, the client should appear in the clients list and should display the currently loaded model.

![Client DeepInfra Ready](/img/0.26.0/client-deepinfra-ready.png)

### Common issues

#### Generations are weird / bad

Make sure the [correct prompt template is assigned](/user-guide/clients/prompt-templates/).