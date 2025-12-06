# Settings

![This image displays a dark user interface header labeled "Visualizer," accented with a chromatic aberration effect and a green status dot. Below the title, there are two badges: one labeled "Google" with a monitor icon, and a warning badge featuring a triangle alert symbol that reads "No backend configured."](/talemate/img/0.34.0/visual-agent-general-1.png)

The Visualizer agent settings are organized into two main tabs: **General** and **Styles**.

![A dark-mode settings interface for a 'Visualizer' tool displaying the 'General' configuration tab. It features dropdown menus showing 'Google' selected as the client with no backends currently configured, alongside a slider for image generation timeout and checkboxes for automatic setup options.](/talemate/img/0.34.0/visual-agent-general-2.png)

## General Settings

### Backend Configuration

The Visualizer agent supports separate backends for different types of operations. You can configure each independently:

- **Backend (text to image)**: The backend to use for basic text-to-image generation. This is the primary backend used when generating new images from prompts.
- **Backend (image editing)**: The backend to use for contextual image editing. This allows you to modify existing images using reference images.
- **Backend (image analysis)**: The backend to use for image analysis. This enables AI-powered analysis of images to extract information.

!!! note "Backend Selection"
    Not all backends support all three operations. The dropdown menus will only show backends that support the specific operation. You can use different backends for different operations if needed.

### Image Generation Timeout

Controls how long the agent will wait for an image generation request to complete before considering it failed. The default is 300 seconds (5 minutes), and can be adjusted from 1 to 900 seconds (15 minutes).

If a backend doesn't generate an image within this time limit, the generation will be marked as failed and you'll be notified.

### Automatic Setup

When enabled, the Visualizer agent will automatically configure backends if your selected client has built-in support for them. For example, some clients like KoboldCpp provide an Automatic1111 API that can be automatically detected and configured.

This setting is enabled by default and helps streamline the setup process when using compatible clients.

### Automatic Generation

When enabled, allows the Visualizer agent to automatically generate visual content based on scene context. This can be useful for automatically creating character portraits or scene illustrations as your story progresses.

This setting is disabled by default, giving you full control over when images are generated.

### Fallback Prompt Type

Determines the format used for prompt-only generation when no backends are configured. This setting only affects the output format when generating prompts without actually creating images.

Available options:

- **Keywords**: Generates prompts using keyword-based formatting
- **Descriptive**: Generates prompts using descriptive text formatting

## Styles Configuration

![This image shows the "Styles" configuration tab within the dark-mode "Visualizer" interface, listing various dropdown menus for customizing generation settings. Options include "Art Style," set to "Digital Art," alongside selectors for character cards, portraits, and scene elements. A "Manage styles" box at the bottom indicates that additional styles can be created in the Templates manager.](/talemate/img/0.34.0/visual-agent-general-3.png)

The Styles tab allows you to configure visual styles for different types of content. Each style is a template that defines how prompts are formatted and what visual characteristics are applied.

### Style Options

- **Art Style**: The default art style to use for visual prompt generation. This can be overridden in scene settings.
- **Character Card**: The style to use for character card visual prompt generation
- **Character Portrait**: The style to use for character portrait visual prompt generation
- **Scene Card**: The style to use for scene card visual prompt generation
- **Scene Background**: The style to use for scene background visual prompt generation
- **Scene Illustration**: The style to use for scene illustration visual prompt generation

!!! info "Managing Styles"
    Additional styles can be created and managed in the Templates manager. Styles are reusable templates that define visual characteristics, keywords, and instructions for different types of visual content.

Each style template can include:

- Positive keywords (things to include)
- Negative keywords (things to avoid)
- Descriptive text (detailed descriptions)
- Instructions (specific generation instructions)

These styles are applied automatically when generating images based on the visual type you select.
