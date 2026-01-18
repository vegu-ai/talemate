# Overview

The narrator agent handles the generation of narrative text. This could be progressing the story, describing the scene, or providing exposition and answers to questions.

## Scene Intention Awareness

When you set a **story intention** and **scene phase intention** in the [World Editor - Scene Direction](/talemate/user-guide/world-editor/scene/direction), the narrator automatically incorporates this information into its prompts. This helps the narrator understand both the big-picture goals of your story and the specific objectives of the current scene.

### How It Works

The narrator receives the following context when generating narrative:

- **Story Intention**: Your overarching expectations for the experience (tone, themes, pacing)
- **Scene Type**: The current mode of play (e.g., roleplay, combat, investigation)
- **Scene Phase Intention**: The specific goal and context for what's happening now

With this information, the narrator can better align its output with your creative vision. For example, if your scene intention indicates building tension before a reveal, the narrator will lean into that atmosphere rather than rushing to resolution.

### Setup

To take advantage of scene intention awareness:

1. Open the **World Editor** and navigate to **Scene > Direction**
2. Set an **Overall Intention** describing the story's goals and expectations
3. Set a **Scene Type** and **Current Scene Intention** for the current phase

Both the overall intention and current scene intention should be set for best results. Without them, the narrator generates content without this additional guidance.

For more details on configuring scene direction, see [World Editor - Scene Direction](/talemate/user-guide/world-editor/scene/direction).

## Content

### :material-script: Writing Style

The narrator agent can be influenced by one of your writing style templates.

Make sure a writing style is selected in the [Scene Settings](/talemate/user-guide/world-editor/scene/settings) to apply the writing style to the generated content.