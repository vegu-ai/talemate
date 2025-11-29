# Google Backend

The Google backend provides image generation, editing, and analysis capabilities using Google's Gemini image models. It supports text-to-image generation, image editing with reference images, and AI-powered image analysis.

![A screenshot of the "Visualizer" application settings interface with the "General" tab selected. It shows configuration dropdowns for Client and various Backends (text to image, image editing, image analysis) all set to "Google," alongside an image generation timeout slider positioned at 301. Additional settings include a checked "Automatic Setup" box, an unchecked "Automatic Generation" box, and a "Fallback Prompt Type" menu set to "Keywords."](/talemate/img/0.34.0/visual-agent-google-4.png)

## Prerequisites

Before configuring the Google backend, you need to obtain a Google API key:

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Create a new API key or use an existing one
4. Copy the API key

Then configure it in Talemate:

1. Open Talemate Settings → Application → Google
2. Paste your Google API key in the "Google API Key" field
3. Save your changes

!!! note "API Key vs Vertex AI Credentials"
    The Visualizer agent uses the Google API key (not Vertex AI service account credentials). Make sure you're using the API key from Google AI Studio, not the service account JSON file used for Vertex AI.

## Configuration

In the Visualizer agent settings, select Google as your backend for text-to-image generation, image editing, image analysis, or any combination of these. Each operation can be configured separately.

### Text-to-Image Configuration

For text-to-image generation, configure the following settings:

- **Google API Key**: Your Google API key (configured globally in Talemate Settings)
- **Model**: Select the image generation model to use:
    - **gemini-2.5-flash-image**: Faster generation, good quality
    - **gemini-3-pro-image-preview**: Higher quality, slower generation

![A dark-themed settings interface for a "Visualizer" application, specifically showing the "Google Text to Image" configuration panel. The main view displays a masked input field for a configured Google API Key and a dropdown menu selecting the "gemini-3-pro-image-preview" model.](/talemate/img/0.34.0/visual-agent-google-5.png)

The Google backend automatically handles aspect ratios based on the format you select:

- **Landscape**: 16:9 aspect ratio
- **Portrait**: 9:16 aspect ratio
- **Square**: 1:1 aspect ratio

### Image Editing Configuration

For image editing, configure similar settings but with an additional option:

- **Google API Key**: Your Google API key
- **Model**: Select the image generation model (same options as text-to-image)
- **Max References**: Configure the maximum number of reference images (1-3). This determines how many reference images you can provide when editing an image.

![A dark-themed configuration interface for the "Visualizer" application displaying settings for the "Google Image Editing" tab. The panel features a configured Google API key section and a dropdown menu selecting the "gemini-3-pro-image-preview" model. A slider control at the bottom sets the "Max References" value to 3.](/talemate/img/0.34.0/visual-agent-google-6.png)

!!! note "Reference Images"
    Google's image editing models can use up to 3 reference images to guide the editing process. The "Max References" setting controls how many reference images Talemate will send to the API. You can adjust this based on your needs, but keep in mind that more references may provide better context for complex edits.

### Image Analysis Configuration

For image analysis, configure the following:

- **Google API Key**: Your Google API key
- **Model**: Select a vision-capable text model:
    - **gemini-2.5-flash**: Fast analysis, good for general use
    - **gemini-2.5-pro**: Higher quality analysis
    - **gemini-3-pro-preview**: Latest model with improved capabilities

!!! note "Analysis Models"
    Image analysis uses text models that support vision capabilities, not the image generation models. These models can analyze images and provide detailed descriptions, answer questions about image content, and extract information from visual content.

## Usage

Once configured, the Google backend will appear in the Visualizer agent status with green indicators showing which capabilities are available.

![A dark-themed user interface panel titled "Visualizer" marked with a green status indicator. Below the title are several clickable buttons, including a "References 3" button and four "Google" buttons distinguished by icons representing screen, image, edit, and search functions.](/talemate/img/0.34.0/visual-agent-google-8.png)

The status indicators show:

- **Text to Image**: Available when text-to-image backend is configured
- **Image Edit**: Available when image editing backend is configured (shows max references if configured)
- **Image Analysis**: Available when image analysis backend is configured

## Model Recommendations

### Text-to-Image and Image Editing

- **gemini-2.5-flash-image**: Best for faster generation and general use. Good balance of speed and quality.
- **gemini-3-pro-image-preview**: Best for higher quality results when speed is less important. Use when you need the best possible image quality.

### Image Analysis

- **gemini-2.5-flash**: Best for quick analysis and general use cases. Fast responses with good accuracy.
- **gemini-2.5-pro**: Best for detailed analysis requiring higher accuracy and more nuanced understanding.
- **gemini-3-pro-preview**: Best for the latest capabilities and most advanced analysis features.

## Prompt Formatting

The Google backend uses **Descriptive** prompt formatting by default. This means prompts are formatted as natural language descriptions rather than keyword lists. This works well with Google's Gemini models, which are designed to understand natural language instructions.

When generating images, provide detailed descriptions of what you want to create. For image editing, describe the changes you want to make in natural language.
