# Model expectations

Talemate is built for current reasoning and agentic models. The director chats with function calling, focal actions make several calls in a row, perception analysis returns strict JSON, knowledge extraction and planning return structured output. A model from the pre-agentic era (a small local instruct model, an older hosted model without reasoning) fails these steps, and the failures look like Talemate bugs.

This page states what Talemate needs for the full experience and what still works without it. It is not a list of supported models: an unknown model name is never judged, and nothing below blocks you.

## The bar

Check your model against these three points:

- A current reasoning-capable model
- Reliable JSON and tool-call output
- A usable context of 16k tokens or more (32k recommended for Character perspectives)

The **Context Length** setting of a client is the only one of the three that Talemate can check itself. A new client starts at 16384 tokens. When a client's Context Length sits below 16384, the client settings editor shows a warning under the field; raise the setting if your model allows it.

A bigger context is not better by itself. Talemate is made to work well with smaller context sizes: its summarization layers keep the story context compact, so 16k to 48k is usually enough. The [Setup Wizard](setup-wizard.md) says so when you add a client, and when a client's Context Length is above 65536 the client settings editor shows a short note under the field. A larger context still works; set one if your model and budget allow it.

## Known good examples

These are examples, updated with each release. They are never used as a check.

| Provider type | Examples |
|---|---|
| Hosted | gemini-3.8-flash, glm-5.2 |
| Self-hosted | Qwen 3.8 27B (reasoning on), Gemma 4 31B (reasoning on), Gemma 4 26B (reasoning on, lower VRAM) |

The self-hosted examples are the smallest models that run the full agentic workflow reliably. Turn reasoning on for them in the [client settings](/talemate/user-guide/clients/reasoning/).

## What still works without it

Basic conversation and narration work with older or smaller models. Expect failures in the director, planning, knowledge and Character perspectives features and in other analytical requests.

A story in **Standard** mode asks less of the model than a story with **Character perspectives**, which adds one analytical request per passage and pauses generation when that analysis fails. See [Choosing a mode](/talemate/user-guide/world-editor/knowledge/#choosing-a-mode) before you create your first story.

## Symptoms you will see with an older model

Before you file a bug, check these signs of a model below the bar:

- Function calls do not happen: the director answers in prose instead of acting, or an action completes without any change.
- The director replies with a `report_issue` fallback instead of the action you asked for.
- Perception analysis fails in a Character perspectives story, and the generation error dialog offers **Retry** again and again.
- Structured output comes back empty or malformed (broken JSON or YAML), and a generation error dialog reports a parse failure.
- Reasoning models drift or loop when reasoning is off; turn it on in the client settings.

The bundled [Model Testing Harness](/talemate/user-guide/clients/model-testing-harness/) scene runs these checks against the clients assigned to your agents. Load it after you configure a new client.

## Where this shows in the app

- The [Setup Wizard](setup-wizard.md) shows this bar on its first step, before you pick a provider.
- The client editor, in the wizard and on **Settings → Connections → Clients**, links to this page. The Clients page editor also shows the Context Length setting, warns when it is below 16384 and notes when it is above 65536 that a smaller context is usually enough.
