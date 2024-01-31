# Talemate Text-to-Speech (TTS) Configuration

Talemate supports Text-to-Speech (TTS) functionality, allowing users to convert text into spoken audio. This document outlines the steps required to configure TTS for Talemate using different providers, including ElevenLabs, Coqui, and a local TTS API.

## Configuring ElevenLabs TTS

To use ElevenLabs TTS with Talemate, follow these steps:

1. Visit [ElevenLabs](https://elevenlabs.com) and create an account if you don't already have one.
2. Click on your profile in the upper right corner of the Eleven Labs website to access your API key.
3. In the `config.yaml` file, under the `elevenlabs` section, set the `api_key` field with your ElevenLabs API key.

Example configuration snippet:

```yaml
elevenlabs:
  api_key: <YOUR_ELEVENLABS_API_KEY>
```

## Configuring Local TTS API

For running a local TTS API, Talemate requires specific dependencies to be installed.

### Windows Installation

Run `install-local-tts.bat` to install the necessary requirements.

### Linux Installation

Execute the following command:

```bash
pip install TTS
```

### Model and Device Configuration

1. Choose a TTS model from the [Coqui TTS model list](https://github.com/coqui-ai/TTS).
2. Decide whether to use `cuda` or `cpu` for the device setting.
3. The first time you run TTS through the local API, it will download the specified model. Please note that this may take some time, and the download progress will be visible in the Talemate backend output.

Example configuration snippet:

```yaml
tts:
  device: cuda # or 'cpu'
  model: tts_models/multilingual/multi-dataset/xtts_v2
```

### Voice Samples Configuration

Configure voice samples by setting the `value` field to the path of a .wav file voice sample. Official samples can be downloaded from [Coqui XTTS-v2 samples](https://huggingface.co/coqui/XTTS-v2/tree/main/samples).

Example configuration snippet:

```yaml
tts:
  voices:
    - label: English Male
      value: path/to/english_male.wav
    - label: English Female
      value: path/to/english_female.wav
```

## Saving the Configuration

After configuring the `config.yaml` file, save your changes. Talemate will use the updated settings the next time it starts.

For more detailed information on configuring Talemate, refer to the `config.py` file in the Talemate source code and the `config.example.yaml` file for a barebone configuration example.
