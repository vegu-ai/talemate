# Pi Bridge Client

The Pi Bridge client drives generations through the [pi coding agent](https://github.com/earendil-works/pi) instead of talking to an LLM API directly. pi handles provider authentication and model resolution, so any model pi can reach — hosted APIs, subscription auth, or custom providers you define in pi's `models.json` — becomes usable in Talemate.

Talemate runs pi in its headless RPC mode as a pure bridge: pi's coding tools, extensions, skills and project context discovery are all disabled, and each generation runs in an isolated pi process.

## Requirements

The `pi` binary must be installed and on the `PATH` of the machine running the Talemate backend:

```bash
npm install -g @earendil-works/pi-coding-agent
```

If the client shows a `pi binary not found` error, install pi and re-save the client.

## Authentication

pi resolves credentials on its own — Talemate does not manage API keys for this client. Depending on the provider, pi uses:

- Environment variables (e.g. `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`)
- Keys and OAuth tokens stored in pi's `~/.pi/agent/auth.json` (set up via `/login` in interactive pi, including subscription auth such as Claude Pro/Max or ChatGPT)
- Custom providers defined in `~/.pi/agent/models.json`

As a convenience, when the provider is `openrouter` and an OpenRouter API key is configured in Talemate's application settings, that key is passed to pi automatically.

## Settings

##### Client Name

A unique name for the client that makes sense to you.

##### Provider

The pi provider to route generations through (default `openrouter`). Suggestions are read from pi's model catalog, which includes custom providers from `models.json`.

!!! note "Catalog refreshes on save"
    The catalog is read when Talemate starts and again whenever settings are saved. If you add a provider or model to pi (e.g. a new `models.json` entry) while Talemate is running, save the client or application settings once and reopen the client settings to see it. pi only lists providers whose credentials resolve — a provider whose `apiKey` references an unset environment variable stays hidden.

##### Model

Free-form model id, with suggestions from pi's catalog for the selected provider. Model ids that are not in the catalog are passed through to the provider as-is, so newly released or custom models work without waiting for a catalog update.

##### Max token length

Maximum context length (in tokens) to send with a generation request. If you are not sure leave the default value.

##### Thinking Level

When reasoning is enabled for the client, this thinking level is passed to pi (`minimal` through `max`). Availability of the higher levels depends on the selected model. The model's thinking output is captured and shown in Talemate's reasoning display.

!!! note "The thinking budget is enforced by the provider, not Talemate"
    pi translates the level into the provider's thinking budget/effort parameter, but some providers treat it as advisory — a reasoning-heavy model may think well past a `minimal` budget on complex prompts. If a model spends too long thinking regardless of the level, disable Reasoning for the client instead, which requests no thinking at all.

##### Concurrent Inference

When enabled, batch operations may dispatch multiple generations in parallel — each request runs its own pi instance, so requests never share state.

!!! note "Sampling parameters are owned by pi"
    Unlike API clients, the Pi Bridge does not send sampler parameters (temperature, penalties, token caps) with requests — pi and the provider decide those. Talemate's inference presets do not apply to this client, and response length is controlled via instructions rather than a hard token cap.
