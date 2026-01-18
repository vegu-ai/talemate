# Overview

In 0.32.0 Talemate's TTS (Text-to-Speech) agent has been completely refactored to provide advanced voice capabilities including per-character voice assignment, speaker separation, and support for multiple local and remote APIs. The voice system now includes a comprehensive voice library for managing and organizing voices across all supported providers.

## Key Features

- **Per-character voice assignment** - Each character can have their own unique voice
- **Speaker separation** - Automatic detection and separation of dialogue from narration
- **Voice library management** - Centralized management of all voices across providers
- **Multiple API support** - Support for both local and remote TTS providers
- **Director integration** - Automatic voice assignment for new characters

## Supported APIs

### Local APIs
- **[Kokoro](kokoro.md)** - Fastest generation with predefined voice models and mixing
- **[F5-TTS](f5tts.md)** - Fast voice cloning with occasional mispronunciations
- **[Chatterbox](chatterbox.md)** - High-quality voice cloning (slower generation)
- **[Pocket TTS](pocket-tts.md)** - CPU-based voice cloning from Kyutai (no GPU required)

### Remote APIs
- **[ElevenLabs](elevenlabs.md)** - Professional voice synthesis with voice cloning
- **[Google Gemini-TTS](google.md)** - Google's text-to-speech service
- **[OpenAI](openai.md)** - OpenAI's TTS-1 and TTS-1-HD models

## Troubleshooting

Having issues with TTS? See the [TTS Troubleshooting Guide](troubleshooting.md) for common problems and solutions, including FFmpeg installation and audio playback issues.

## Enable the Voice agent

Start by enabling the voice agent, if it is currently disabled. 

![Voice agent disabled](/talemate/img/0.26.0/voice-agent-disabled.png)

If your voice agent is disabled - indicated by the grey dot next to the agent - you can enable it by clicking on the agent and checking the `Enable` checkbox near the top of the agent settings.

![Agent disabled](/talemate/img/0.26.0/agent-disabled.png) ![Agent enabled](/talemate/img/0.26.0/agent-enabled.png)

!!! note "Ctrl click to toggle agent"
    You can use Ctrl click to toggle the agent on and off.

## Voice Library Management

Voices are managed through the Voice Library, accessible from the main application bar. The Voice Library allows you to:

- Add and organize voices from all supported providers
- Assign voices to specific characters
- Create mixed voices (Kokoro)
- Manage both global and scene-specific voice libraries

See the [Voice Library Guide](voice-library.md) for detailed instructions.

## Character Voice Assignment

![Character voice assignment](/talemate/img/0.32.0/character-voice-assignment.png)

Characters can have individual voices assigned through the Voice Library. When a character has a voice assigned:

1. Their dialogue will use their specific voice
2. The narrator voice is used for exposition in their messages (with speaker separation enabled)
3. If their assigned voice's API is not available, it falls back to the narrator voice

The Voice agent status will show all assigned character voices and their current status.

![Voice agent status with characters](/talemate/img/0.32.0/voice-agent-status-characters.png)