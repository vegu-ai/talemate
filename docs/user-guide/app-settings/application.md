# :material-application-outline: Application

![App settings - Application](/talemate/img/0.38.0/app-settings-application.png)

Configure various API keys for integration with external services. (OpenAI, Anthropic, etc.)

Each external service has its own page in the sidebar. Select a service, paste your key or token, and save.

## HuggingFace Token

!!! info "Added in 0.38.0"

Some features download model weights from [Hugging Face](https://huggingface.co/). Most weights are open and download without any credentials, but a few are **gated** — Hugging Face requires you to be signed in and to have accepted the model's terms before it will let you download them. The Pocket TTS voice-cloning model is one such gated model.

To download gated weights, add a HuggingFace access token:

1. Open the **HuggingFace** page under Application settings.
2. Create a token at [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). A read token is sufficient.
3. Paste it into the **HuggingFace Token** field and save.

The token is shared across Talemate. Once set here, any feature that needs to download gated weights (such as the [Pocket TTS](../agents/voice/pocket-tts.md) agent) will use it automatically. You can also set the same token directly in the Pocket TTS agent config — both fields point at the same setting.

!!! note "Accepting model terms"
    A token only proves who you are. For gated models you still need to visit the model's page on Hugging Face and accept its terms once with the same account before the download will succeed.