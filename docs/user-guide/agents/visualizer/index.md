# Overview

The Visualizer agent handles image generation for characters and environments in your scenes. It provides a comprehensive system for creating, editing, and managing visual content through the [Visual Library](visual-library.md).

The Visualizer agent supports multiple image generation backends, allowing you to choose the best tool for your needs. It can perform three main types of operations:

- **Text to Image**: Generate new images from text prompts
- **Image Editing**: Modify existing images using reference images
- **Image Analysis**: Analyze images using AI to extract information

## Key Features

- **Multiple Backend Support**: Works with various image generation services including Google, ComfyUI, AUTOMATIC1111, OpenAI, and more
- **Style Templates**: Configure different visual styles for different types of content (character cards, portraits, scene backgrounds, etc.)
- **Visual Library Integration**: Generated images are managed through the Visual Library, where you can organize, iterate, and save visual assets
- **[Inline Visuals](../../inline-visuals.md)**: Generated images can appear directly in your scene feed alongside messages, providing an immersive visual storytelling experience (new in v0.35.0)
- **Automatic Generation**: Optionally allow the agent to automatically generate visual content based on scene context
- **Prompt Generation**: Supports both direct prompts and natural language instructions that incorporate character and scene context

## Configuration

The Visualizer agent can be configured through its settings panel, where you can:

- Select backends for different operations (text-to-image, image editing, image analysis)
- Configure generation timeouts
- Set up automatic backend setup and generation
- Customize visual styles for different content types

See the [Settings](settings.md) page for detailed configuration options.

## Backend Documentation

The Visualizer agent supports multiple backends, each with its own configuration requirements:

- **[ComfyUI](backends/comfyui.md)**: Advanced node-based workflow system for image generation and editing
- **[Google](backends/google.md)**: Google's Gemini image models for generation, editing, and analysis
- **[OpenAI](backends/openai.md)**: OpenAI's DALL·E 3 and GPT-Image models
- **[OpenRouter](backends/openrouter.md)**: Access multiple AI providers through OpenRouter's unified API
- **[SD.Next](backends/sdnext.md)**: Improved fork of AUTOMATIC1111 with better performance and features
- **[AUTOMATIC1111](backends/a1111.md)**: Legacy Stable Diffusion WebUI backend (deprecated, use SD.Next instead)

## Usage

The Visualizer agent can be accessed through several methods:

### Visual Library

The primary interface for image generation is the Visual Library, accessible from the toolbar when a scene is active. You can generate images using either:

- **Prompt Mode**: Direct text descriptions of what you want to create
- **Instruct Mode**: Natural language instructions that incorporate character and scene context

For more information on using the Visual Library, see the [Visual Library documentation](visual-library.md).

### Scenario Tools Shortcuts

Quick shortcuts are available through the scenario tools menu, allowing you to quickly generate images for:

- **Visualize Scene**: Generate images of the current scene environment
- **Visualize Character**: Generate character portraits or cards
- **Visualize Moment**: Generate scene illustrations depicting the current story moment

These shortcuts support keyboard modifiers: hold **ALT** to generate prompts only (without creating images), or hold **CTRL** to provide custom instructions.

When **Auto-attach visuals** is enabled in the visualizer menu, generated images will automatically appear in your scene feed as [inline visuals](../../inline-visuals.md). You can configure the display size and behavior of these images in the [Appearance Settings](../../app-settings/appearance.md#visuals).

### Director Chat

The Director agent can also generate images through director chat. When chatting with the director, you can ask it to create visual assets for scenes or characters, and it will use the Visualizer agent to generate the requested images.

For more information on director chat, see the [Director Chat documentation](../director/chat.md).

