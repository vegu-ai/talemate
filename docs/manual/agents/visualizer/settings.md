# Settings

![Visual agent settings](../../../../img/0.26.0/visual-agent-settings.png)

##### Client

This is the text generation client to use for prompt generation. You can select any of your configured text generation clients here.

##### Backend

The API to use for image generation.

- [OpenAI](openai.md)
- [AUTOMATIC1111](automatic1111.md)
- [ComfyUI](comfyui.md)

##### Default Style

The style to use for image generation. Prompts will be automatically adjusted to coerce the image generation to use this style.

- Anime
- Concept Art
- Digital Art
- Graphic Novel
- Ink illustration
- Photo

More styles will be added in the future and support for custom styles will be added as well.

##### Automatic Setup

Some clients support both text and image generation. If this setting is enabled, the visualizer will automatically set itself up to use the backend of the client you have selected. This is currently only supported by KoboldCpp.

##### Automatic Generation

Enables or disables automatic generation that may be triggered by scene changes. This is currently only used very sparsely and only by more complex talemate scenes like the Simulation Suite.

##### Process in Background

If enabled, image generation will happen in the background, allowing you to continue using Talemate while the image is being generated.
