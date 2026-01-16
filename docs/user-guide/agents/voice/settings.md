# Settings

![Voice agent settings](/talemate/img/0.32.0/voice-agent-settings.png)

##### Enabled APIs

Select which TTS APIs to enable. You can enable multiple APIs simultaneously:

- **Kokoro** - Fastest generation with predefined voice models and mixing
- **F5-TTS** - Fast voice cloning with occasional mispronunciations
- **Chatterbox** - High-quality voice cloning (slower generation)
- **Pocket TTS** - CPU-based voice cloning from Kyutai (no GPU required)
- **ElevenLabs** - Professional voice synthesis with voice cloning
- **Google Gemini-TTS** - Google's text-to-speech service
- **OpenAI** - OpenAI's TTS-1 and TTS-1-HD models

!!! note "Multi-API Support"
    You can enable multiple APIs and assign different voices from different providers to different characters. The system will automatically route voice generation to the appropriate API based on the voice assignment.

##### Narrator Voice

The default voice used for narration and as a fallback for characters without assigned voices.

The dropdown shows all available voices from all enabled APIs, with the format: "Voice Name (Provider)"

!!! info "Voice Management"
    Voices are managed through the Voice Library, accessible from the main application bar. Adding, removing, or modifying voices should be done through the Voice Library interface.

##### Speaker Separation

Controls how dialogue is separated from exposition in messages:

- **No separation** - Character messages use character voice entirely, narrator messages use narrator voice
- **Simple** - Basic separation of dialogue from exposition using punctuation analysis, with exposition being read by the narrator voice
- **Mixed** - Enables AI assisted separation for narrator messages and simple separation for character messages
- **AI assisted** - AI assisted separation for both narrator and character messages

!!! warning "AI Assisted Performance"
    AI-assisted speaker separation sends additional prompts to your LLM, which may impact response time and API costs.

##### Auto-generate for player

Generate voice automatically for player messages

##### Auto-generate for AI characters

Generate voice automatically for NPC/AI character messages

##### Auto-generate for narration

Generate voice automatically for narrator messages

##### Auto-generate for context investigation

Generate voice automatically for context investigation messages

## Advanced Settings

Advanced settings are configured per-API and can be found in the respective API configuration sections:

- **Chunk size** - Maximum text length per generation request
- **Model selection** - Choose specific models for each API
- **Voice parameters** - Provider-specific voice settings

!!! tip "Performance Optimization"
    Each API has different optimal chunk sizes and parameters. The system automatically handles chunking and queuing for optimal performance across all enabled APIs.