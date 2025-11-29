# OpenRouter

The OpenRouter backend provides access to image generation, editing, and analysis capabilities through OpenRouter's unified API. OpenRouter allows you to access multiple AI providers through a single API, giving you flexibility to choose from various models and providers.

![A dark-themed settings interface for the "Visualizer" application, displaying a sidebar with General, OpenRouter, and Styles navigation options. The main panel allows configuration of backend services, showing "OpenRouter" selected for text-to-image, image editing, and image analysis, with "Google" set as the client. Additional controls include a slider for image generation timeout set to 301 and checkboxes for automatic setup and generation.](/talemate/img/0.34.0/visual-agent-openrouter-1.png)

## Prerequisites

Before configuring the OpenRouter backend, you need to obtain an OpenRouter API key:

1. Go to [OpenRouter Keys](https://openrouter.ai/settings/keys)
2. Sign in with your account
3. Create a new API key or use an existing one
4. Copy the API key

Then configure it in Talemate:

1. Open Talemate Settings → Application → OpenRouter API
2. Paste your OpenRouter API key in the "OpenRouter API Key" field
3. Save your changes

For additional instructions, see the [OpenRouter API setup guide](/talemate/user-guide/apis/openrouter/).

## Configuration

In the Visualizer agent settings, select OpenRouter as your backend for text-to-image generation, image editing, image analysis, or any combination of these. Each operation can be configured separately.

### Text-to-Image Configuration

For text-to-image generation, configure the following settings:

- **OpenRouter API Key**: Your OpenRouter API key (configured globally in Talemate Settings)
- **Model**: Select an image generation model from OpenRouter. The model list is dynamically populated based on models available through your OpenRouter account.
- **Only use these providers**: Optionally filter to specific providers (e.g., only use Google or OpenAI)
- **Ignore these providers**: Optionally exclude specific providers from consideration

![This screenshot depicts the "Visualizer" settings interface, specifically the "OpenRouter Text to Image" configuration tab. The panel displays an active API Key section, a model selection dropdown currently set to "google/gemini-2.5-flash-image", and additional options to filter specific service providers.](/talemate/img/0.34.0/visual-agent-openrouter-2.png)

!!! warning "Model Selection"
    There is no reliable way for Talemate to determine which models support text-to-image generation, so the model list is unfiltered. Please consult the [OpenRouter documentation](https://openrouter.ai/docs) to verify that your selected model supports image generation before using it.

The OpenRouter backend automatically handles aspect ratios based on the format you select:

- **Landscape**: 16:9 aspect ratio
- **Portrait**: 9:16 aspect ratio
- **Square**: 1:1 aspect ratio

### Image Editing Configuration

For image editing, configure similar settings with an additional option:

- **OpenRouter API Key**: Your OpenRouter API key
- **Model**: Select an image editing model from OpenRouter
- **Max References**: Configure the maximum number of reference images (1-3). This determines how many reference images you can provide when editing an image.
- **Provider filtering**: Optionally filter providers (same as text-to-image)

![This screenshot displays the settings interface for an application named Visualizer, specifically focusing on the "OpenRouter - Image Editing" configuration tab. The main panel features input fields for an OpenRouter API key, a model selection dropdown set to "google/gemini-2.5-flash-image," and provider filtering options. Additionally, a slider at the bottom allows users to adjust the "Max References," which is currently set to 1.](/talemate/img/0.34.0/visual-agent-openrouter-3.png)

!!! warning "Model Selection"
    There is no reliable way for Talemate to determine which models support image editing, so the model list is unfiltered. Image editing refers to image generation with support for 1 or more contextual reference images. Please consult the [OpenRouter documentation](https://openrouter.ai/docs) to verify that your selected model supports image editing before using it.

### Image Analysis Configuration

For image analysis, configure the following:

- **OpenRouter API Key**: Your OpenRouter API key
- **Model**: Select a vision-capable text model from OpenRouter
- **Provider filtering**: Optionally filter providers

![A screenshot of the "Visualizer" application interface showing the "OpenRouter Image Analysis" settings panel. The configuration area displays a model selection dropdown set to "google/gemini-2.5-flash" alongside a configured API key field. An informational box notes that the model list is unfiltered and users should verify that their chosen text generation model supports multi-modal vision capabilities.](/talemate/img/0.34.0/visual-agent-openrouter-4.png)

!!! warning "Model Selection"
    There is no reliable way for Talemate to determine which models support image analysis, so the model list is unfiltered. Image analysis requires a text generation model that is multi-modal and supports vision capabilities. Please consult the [OpenRouter documentation](https://openrouter.ai/docs) to verify that your selected model supports vision before using it.

## Usage

Once configured, the OpenRouter backend will appear in the Visualizer agent status with green indicators showing which capabilities are available.

![A dark-mode user interface panel labeled "Visualizer" features a green status indicator dot next to the title. Below the header are several pill-shaped tags, including grey buttons for "Google" and "References 1" alongside three green "OpenRouter" buttons with various icons. This layout likely represents a configuration of active tools or API connections within a software application.](/talemate/img/0.34.0/visual-agent-openrouter-5.png)

The status indicators show:

- **Text to Image**: Available when text-to-image backend is configured
- **Image Edit**: Available when image editing backend is configured (shows max references if configured)
- **Image Analysis**: Available when image analysis backend is configured

## Model Recommendations

OpenRouter provides access to many models from different providers. Here are some general recommendations:

### Text-to-Image and Image Editing

- **google/gemini-2.5-flash-image**: Fast image generation with good quality
- **google/gemini-3-pro-image-preview**: Higher quality option (if available)

### Image Analysis

- **google/gemini-2.5-flash**: Fast analysis with good accuracy
- **google/gemini-2.5-pro**: Higher quality analysis
- **google/gemini-3-pro-preview**: Latest capabilities (if available)

## Provider Filtering

OpenRouter allows you to filter which providers are used for a specific model. This can be useful if:

- You want to use a specific provider for cost or quality reasons
- You want to avoid certain providers
- You want to test different providers for the same model

You can configure provider filtering in each backend's settings:

- **Only use these providers**: Limits requests to only the selected providers
- **Ignore these providers**: Excludes the selected providers from consideration

If both are configured, "Only use these providers" takes precedence.

## Prompt Formatting

The OpenRouter backend uses **Descriptive** prompt formatting by default. This means prompts are formatted as natural language descriptions rather than keyword lists. Provide detailed, natural language descriptions of what you want to create or edit.
