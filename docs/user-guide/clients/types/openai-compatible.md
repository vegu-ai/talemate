# OpenAI Compatible Client

Allows you to use Talemate with a service that exposes an openai-like API.

!!! warning "Use the officual client if it is available"
    Only use this if the service you are trying access doen't already have official support from Talemate.
    All the officially supported clients can be found [here](/talemate/user-guide/clients/).

## DeepInfra

If you want to add a DeepInfra client, go to **Settings → Connections → Clients**, click **:material-plus-box: Add client** and pick `OpenAI Compatible API` from the client type menu.

![Client DeepInfra](/talemate/img/0.40.0/client-deepinfra.png)

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

The number of tokens to use as context when generating text. Defaults to `16384`.

### Parameters

The **Parameters** section of the client editor lets you control which sampler parameters are sent with each request. Some OpenAI-compatible services reject requests that include parameters they don't support for the selected model, returning an error instead of a generation. If you run into this, you can turn the offending parameter off so it is left out of the request entirely.

Each parameter has its own toggle:

- **Send temperature**
- **Send top_p**
- **Send presence_penalty**

All three are enabled by default. Turning a toggle off omits that parameter from the request completely (it is not sent as a zero value). Leave them enabled unless the service you are connecting to errors when it receives one of them.

### Streaming

**Stream** is on by default: the server sends the response as it is generated, so the tokens-per-second figure on the client card moves while it works. Until the first token arrives the card shows *waiting…*, which is normal while a long prompt is processed. Turn **Stream** off, under **Parameters**, if your server does not support streaming; the card then shows the speed once the whole response is in.

### Reasoning

Enable **Reasoning** in the client editor for a reasoning model. Choose **Reasoning Effort** and the **Reasoning Effort Format** your server accepts:

| Format | What Talemate sends |
| --- | --- |
| `none` (initial setting) | No effort field; the server uses its own defaults. |
| `reasoning_effort` | A field such as `"reasoning_effort": "high"`. |
| `reasoning` | An object such as `"reasoning": {"effort": "high"}`. |

The effort choices are `default`, `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`. Pick a level supported by your server and model. Effort `default` omits the setting in every format. Effort `none` is different from format `none`: it sends a request for no reasoning when a sending format is selected, and only works on models that accept that level.

These settings apply to both chat completions (**API handles prompt template** enabled) and text completions (disabled). Support can differ between those endpoints, even on the same server. Check the server's documentation; Talemate does not infer support from its URL or model name, probe it, or retry a rejected request with a different format.

**Completion Token Parameter**, next to **Reasoning Effort Format**, chooses the field used for the total completion limit:

| Parameter | When to use it |
| --- | --- |
| `max_tokens` (initial setting) | Servers using the traditional completion limit, including most text-completion endpoints. Existing saved clients keep this choice. |
| `max_completion_tokens` | OpenAI chat completions and compatible servers that require this parameter. |

The choice applies whenever the response token cap is enabled, even with reasoning disabled. It changes only the field name, not the limit. For direct OpenAI at `https://api.openai.com/v1`, enable **API handles prompt template**, choose `reasoning_effort` and `max_completion_tokens`, and disable any sampler parameters the selected model rejects. OpenAI chat completions reject the `reasoning` object with HTTP 400; that format is for other servers that accept it.

**Extra Completion Tokens** retains your saved **Reasoning Tokens** value. It adds headroom to the selected total completion limit when reasoning and the response token cap are enabled, and remains available to prompt templates as `reasoning_tokens`. It does not send a separate thinking budget. Use **Reasoning Effort** to control depth instead. Choosing an effort or a completion token parameter does not change this allowance.

With **API handles prompt template** enabled, servers such as llama.cpp (`llama-server --jinja`) return the reasoning separately from the answer, and Talemate reads it from there, shows it with the prompt in the prompt viewer and ignores the strip pattern. If the server leaves the reasoning in the answer instead, Talemate strips it with your [reasoning pattern](/talemate/user-guide/clients/reasoning/#response-pattern-configuration); in this mode a response without a matching pattern is used as it is, unless you set a validation pattern or a reason prefill, which mean the reasoning started and make an unclosed block follow **Pattern Not Found Behavior**. Without **API handles prompt template**, Talemate looks for the reasoning in the response text and needs a pattern that matches your model.

When a sending format is selected, the client card shows the chosen effort in a dropdown, where you can change it quickly. With format `none`, it shows a field for the extra completion allowance instead. With Reasoning off, a **Reasoning Disabled** chip takes the place of the dropdown or the field. Turning Talemate reasoning off, globally or for an agent action, omits the effort setting and padding; the server may still reason according to its own defaults. Keep your existing [reasoning patterns](/talemate/user-guide/clients/reasoning/#response-pattern-configuration) if your model includes thinking in its response text.

### Ready to use

Click `Save` in the toolbar to add the client.

Once it is added, the client should appear in the clients list and should display the currently loaded model.

![Client DeepInfra Ready](/talemate/img/0.26.0/client-deepinfra-ready.png)

### Common issues

#### Generations are weird / bad

Make sure the [correct prompt template is assigned](/talemate/user-guide/clients/prompt-templates/).

#### The error names a different problem than expected

When a request fails before the server answers, for example a refused connection or a rejected key, the error dialog shows the actual cause. A server that needs no key can be left with an empty **API Key**.

#### Could not connect

The API URL field is empty. This client reports `Could not connect` when it has no URL to send requests to.

A URL that is present but wrong does not produce this error — this client takes the model name from the field you filled in rather than asking the service for it, so it keeps reporting as connected and the problem shows up as a failed generation instead.
--8<-- "docs/snippets/common.md:client-response-length"
