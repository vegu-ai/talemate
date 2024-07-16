# Overview

Talemate supports Text-to-Speech (TTS) functionality, allowing users to convert text into spoken audio. This document outlines the steps required to configure TTS for Talemate using different providers, including ElevenLabs and a local TTS API.

## Enable the Voice agent

Start by enabling the voice agent, if it is currently disabled. 

![Voice agent disabled](/talemate/img/0.26.0/voice-agent-disabled.png)

If your voice agent is disabled - indicated by the grey dot next to the agent - you can enable it by clicking on the agent and checking the `Enable` checkbox near the top of the agent settings.

![Agent disabled](/talemate/img/0.26.0/agent-disabled.png) ![Agent enabled](/talemate/img/0.26.0/agent-enabled.png)


!!! abstract "Next: Connect to a TTS api"
    Next you need to decide which service / api to use for audio generation and configure the voice agent accordingly.

    - [OpenAI](openai.md)
    - [ElevenLabs](elevenlabs.md)
    - [Local TTS](local_tts.md)

    You can also find more information about the various settings [here](settings.md).

## Select a voice

![Elevenlaps voice missing](/talemate/img/0.26.0/voice-agent-no-voice-selected.png)

Click on the agent to open the agent settings.

Then click on the `Narrator Voice` dropdown and select a voice.

![Elevenlaps voice selected](/talemate/img/0.26.0/voice-agent-select-voice.png)

The selection is saved automatically, click anywhere outside the agent window to close it.

The Voice agent should now show that the voice is selected and be ready to use.

![Elevenlabs ready](/talemate/img/0.26.0/elevenlabs-ready.png)