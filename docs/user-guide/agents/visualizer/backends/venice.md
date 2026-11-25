# Venice

The Venice backend provides text-to-image generation and image editing through [Venice.ai](https://venice.ai). Each operation is configured separately in the Visualizer agent settings.

## Prerequisites

1. Sign in to your Venice account and create an API key in your API settings
2. Copy the API key

You can then either:

- Paste the key into the **Venice API Key** field of the Visualizer's Venice section, or
- Leave that field empty and set the `VENICE_API_KEY` environment variable before starting Talemate

## Configuration

In the Visualizer agent settings, select **Venice** as the backend for text-to-image generation, image editing, or both.

- **Venice API Key**: Your Venice API key. The field is masked. Falls back to the `VENICE_API_KEY` environment variable if empty.
- **Model**: The Venice image model ID. Defaults to `venice-sd35` for text-to-image and `firered-image-edit` for image editing. See Venice's model list for the IDs available to your account.
- **Moderation**: **Auto** blurs images Venice classifies as adult content. **Low** disables the blurring.

## Resolution

Resolution is set from the format you pick:

- Landscape: 1216x832
- Portrait: 832x1216
- Square: 1024x1024

Some models reject explicit width and height. When Venice reports this, Talemate retries with an equivalent aspect ratio (3:2, 2:3 or 1:1) and remembers it for that model.

!!! note "Reference Images"
    Image editing takes a single reference image, which is used as the base for the edit. The output aspect ratio follows the input image.

## Prompt Formatting

The Venice backend uses **Descriptive** prompt formatting: natural language descriptions rather than keyword lists.
