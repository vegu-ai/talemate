# Chatterbox

Local zero shot voice cloning from .wav files.

!!! warning "FFmpeg Required"
    Chatterbox requires FFmpeg for audio processing. If you encounter errors like `Could not load libtorchcodec` or `FFmpeg version 8: Could not load this library`, you need to install FFmpeg.

    **Windows:** Run `install-ffmpeg.bat` from the Talemate root directory.

    **Linux/macOS:** Install FFmpeg using your system package manager (versions 4-8 supported).

    See the [TTS Troubleshooting Guide](troubleshooting.md#ffmpeg-not-found) for more details.

![Chatterbox API settings](/talemate/img/0.32.0/chatterbox-api-settings.png)

##### Device

Auto-detects best available option

##### Model

Default Chatterbox model optimized for speed

##### Chunk size

Split text into chunks of this size. Smaller values will increase responsiveness at the cost of lost context between chunks. (Stuff like appropriate inflection, etc.). 0 = no chunking

## Adding Chatterbox Voices

### Voice Requirements

Chatterbox voices require:

- Reference audio file (.wav format, 5-15 seconds optimal)
- Clear speech with minimal background noise
- Single speaker throughout the sample

### Creating a Voice

1. Open the Voice Library
2. Click **:material-plus: New**
3. Select "Chatterbox" as the provider
4. Configure the voice:

![Add Chatterbox voice](/talemate/img/0.32.0/add-chatterbox-voice.png)

**Label:** Descriptive name (e.g., "Marcus - Deep Male")

**Voice ID / Upload File** Upload a .wav file containing the voice sample. The uploaded reference audio will also be the voice ID.

**Speed:** Adjust playback speed (0.5 to 2.0, default 1.0)

**Tags:** Add descriptive tags for organization

**Extra voice parameters**

There exist some optional parameters that can be set here on a per voice level.

![Chatterbox extra voice parameters](/talemate/img/0.32.0/chatterbox-parameters.png)

##### Exaggeration Level

Exaggeration (Neutral = 0.5, extreme values can be unstable). Higher exaggeration tends to speed up speech; reducing cfg helps compensate with slower, more deliberate pacing.

##### CFG / Pace

If the reference speaker has a fast speaking style, lowering cfg to around 0.3 can improve pacing.