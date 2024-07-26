# Settings

![Voice agent settings](/talemate/img/0.26.0/voice-agent-settings.png)

##### API

The TTS API to use for voice generation.

- OpenAI
- ElevenLabs
- Local TTS

##### Narrator Voice

The voice to use for narration. Each API will come with its own set of voices.

![Narrator voice](/talemate/img/0.26.0/voice-agent-select-voice.png)

!!! note "Local TTS"
    For local TTS, you will have to provide voice samples yourself. See [Local TTS Instructions](local_tts.md) for more information.

##### Generate for player

Whether to generate voice for the player. If enabled, whenever the player speaks, the voice agent will generate audio for them.

##### Generate for NPCs

Whether to generate voice for NPCs. If enabled, whenever a non player character speaks, the voice agent will generate audio for them.

##### Generate for narration

Whether to generate voice for narration. If enabled, whenever the narrator speaks, the voice agent will generate audio for them.

##### Split generation

If enabled, the voice agent will generate audio in chunks, allowing for faster generation. This does however cause it lose context between chunks, and inflection may not be as good.