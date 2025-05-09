# Overview

Talemate has a number of agents that perform various tasks.

### Conversation

Hanldes character dialog generation

### Creator

Used for creative tasks like scene and character generation

### Director

Will eventually become a Game Master type agent. Right now used for some very rudimentary scene direction. Allows complex scene control via the scoped api scripting.

### Editor

Will try to correct markup and optionally revise text to fix repetition and unwanted prose.

### Long-term Memory

Attempts to select and add relevant information to the current context window.

### Narrator

Handles scene narration

### Summarizer

Will regularly summarize scene progress whenever time advances or a certain length (tokens) threshold is reached.

### Visualizer

Handles image generation for characters and environments. Currently supports OpenAI, AUTOMATIC1111, and ComfyUI backends.

### Voice

Handles TTS generation. Currently supports ElevenLabs and OpenAI backends.

### World State

Keeps track of the current world state and reinforces specific character states.