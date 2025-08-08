# ElevenLabs

Professional voice synthesis with voice cloning capabilities using ElevenLabs API.

![ElevenLabs API settings](/talemate/img/0.32.0/elevenlabs-api-settings.png)

## API Setup

ElevenLabs requires an API key. See the [ElevenLabs API setup](/talemate/user-guide/apis/elevenlabs/) for instructions on obtaining and setting an API key.

## Configuration

**Model:** Select from available ElevenLabs models

!!! warning "Voice Limits"
    Your ElevenLabs subscription allows you to maintain a set number of voices (10 for the cheapest plan). Any voice that you generate audio for is automatically added to your voices at [https://elevenlabs.io/app/voice-lab](https://elevenlabs.io/app/voice-lab). This also happens when you use the "Test" button. It is recommended to test voices via their voice library instead.

## Adding ElevenLabs Voices

### Getting Voice IDs

1. Go to [https://elevenlabs.io/app/voice-lab](https://elevenlabs.io/app/voice-lab) to view your voices
2. Find or create the voice you want to use
3. Click "More Actions" -> "Copy Voice ID" for the desired voice

![Copy Voice ID](/talemate/img/0.32.0/elevenlabs-copy-voice-id.png)

### Creating a Voice in Talemate

![Add ElevenLabs voice](/talemate/img/0.32.0/add-elevenlabs-voice.png)

1. Open the Voice Library
2. Click "Add Voice"
3. Select "ElevenLabs" as the provider
4. Configure the voice:

**Label:** Descriptive name for the voice

**Provider ID:** Paste the ElevenLabs voice ID you copied

**Tags:** Add descriptive tags for organization