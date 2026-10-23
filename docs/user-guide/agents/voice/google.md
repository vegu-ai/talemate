# Google Gemini-TTS

Google Gemini-TTS provides access to Google's text-to-speech service.

## API Setup

Google Gemini-TTS requires a Google Cloud API key.

See the [Google Cloud API setup](/talemate/user-guide/apis/google/) for instructions on obtaining an API key.

## Configuration

![Google TTS settings](/talemate/img/0.40.0/google-tts-api-settings.png)

**Google API Key:** The shared Google API key. It can also be set on the API Keys page under **Connections → API Keys**.

**Model:** Select from available Google TTS models

**Chunk size:** Split text into chunks of this size. Smaller values will increase responsiveness at the cost of lost context between chunks. 0 = no chunking
