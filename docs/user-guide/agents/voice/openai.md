# OpenAI

If you are using OpenAI for voice generation, you will need to provide an API key.

![no api token](/talemate/img/0.26.0/no-api-token.png)

See the [OpenAI API setup](/talemate/user-guide/apis/openai/) for instructions on how to set up the API key.

## Settings

![Voice agent openai settings](/talemate/img/0.40.0/openai-tts-api-settings.png)

##### Model

Which model to use for generation.

- GPT-4o Mini TTS
- TTS 1
- TTS 1 HD

##### Chunk size

Split text into chunks of this size. Smaller values will increase responsiveness at the cost of lost context between chunks. (Stuff like appropriate inflection, etc.). 0 = no chunking
