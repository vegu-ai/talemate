# Voice Library

The Voice Library is the central hub for managing all voices across all TTS providers in Talemate. It provides a unified interface for organizing, creating, and assigning voices to characters.

## Accessing the Voice Library

The Voice Library can be accessed from the main application bar at the top of the Talemate interface.

![Voice Library access](/talemate/img/0.32.0/voice-library-access.png)

Click the voice icon to open the Voice Library dialog.

!!! note "Voice agent needs to be enabled"
    The Voice agent needs to be enabled for the voice library to be available.

## Voice Library Interface

![Voice Library interface](/talemate/img/0.32.0/voice-library-interface.png)

The Voice Library interface consists of:

### Scope Tabs

- **Global** - Voices available across all scenes
- **Scene** - Voices specific to the current scene (only visible when a scene is loaded)
- **Characters** - Character voice assignments for the current scene (only visible when a scene is loaded)

### API Status

The toolbar shows the status of all TTS APIs:

- **Green** - API is enabled and ready
- **Orange** - API is enabled but not configured
- **Red** - API has configuration issues
- **Gray** - API is disabled

![API status](/talemate/img/0.32.0/voice-library-api-status.png)

## Managing Voices

### Global Voice Library

The global voice library contains voices that are available across all scenes. These include:

- Default voices provided by each TTS provider
- Custom voices you've added

#### Adding New Voices

To add a new voice:

1. Click the "+ New" button
2. Select the TTS provider
3. Configure the voice parameters:
   - **Label** - Display name for the voice
   - **Provider ID** - Provider-specific identifier
   - **Tags** - Free-form descriptive tags you define (gender, age, style, etc.)
   - **Parameters** - Provider-specific settings

Check the provider specific documentation for more information on how to configure the voice.

#### Voice Types by Provider

**F5-TTS & Chatterbox:**

- Upload .wav reference files for voice cloning
- Specify reference text for better quality
- Adjust speed and other parameters

**Pocket TTS:**

- Upload .wav reference files for voice cloning
- Use built-in voice samples included with Talemate
- Use voices from the Hugging Face voice catalog
- Runs on CPU (no GPU required)

**Kokoro:**

- Select from predefined voice models
- Create mixed voices by combining multiple models
- Adjust voice mixing weights

**ElevenLabs:**

- Select from available ElevenLabs voices
- Configure voice settings and stability
- Use custom cloned voices from your ElevenLabs account

**OpenAI:**

- Choose from available OpenAI voice models
- Configure model (GPT-4o Mini TTS, TTS-1, TTS-1-HD)

**Google Gemini-TTS:**

- Select from Google's voice models
- Configure language and gender settings

### Scene Voice Library

Scene-specific voices are only available within the current scene. This is useful for:

- Scene-specific characters
- Temporary voice experiments  
- Custom voices for specific scenarios

Scene voices are saved with the scene and will be available when the scene is loaded.

## Character Voice Assignment

### Automatic Assignment

The Director agent can automatically assign voices to new characters based on:

- Character tags and attributes
- Voice tags matching character personality
- Available voices in the voice library

This feature can be enabled in the Director agent settings.

### Manual Assignment

![Character voice assignment](/talemate/img/0.32.0/character-voice-assignment.png)

To manually assign a voice to a character:

1. Go to the "Characters" tab in the Voice Library
2. Find the character in the list
3. Click the voice dropdown for that character
4. Select a voice from the available options
5. The assignment is saved automatically

### Character Voice Status

The character list shows:

- **Character name**
- **Currently assigned voice** (if any)
- **Voice status** - whether the voice's API is available
- **Quick assignment controls**

## Voice Tags and Organization

### Tagging System

Voices can be tagged with any descriptive attributes you choose. Tags are completely free-form and user-defined. Common examples include:

- **Gender**: male, female, neutral
- **Age**: young, mature, elderly
- **Style**: calm, energetic, dramatic, mysterious
- **Quality**: deep, high, raspy, smooth
- **Character types**: narrator, villain, hero, comic relief
- **Custom tags**: You can create any tags that help you organize your voices

### Filtering and Search

Use the search bar to filter voices by:
- Voice label/name
- Provider
- Tags
- Character assignments

This makes it easy to find the right voice for specific characters or situations.