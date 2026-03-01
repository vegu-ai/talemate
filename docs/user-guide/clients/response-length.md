# Response Length Instructions

!!! info "New in 0.36.0"
    Response length instruction enforcement can now be toggled per client.

When enabled, Talemate appends a response length instruction to prompts that don't already include one inline. This helps guide the model to produce responses of appropriate length based on the configured generation settings.

## How It Works

Many prompt templates already include response length instructions inline (e.g., "The length of your response must fit within 2 paragraphs"). However, some templates do not. When **Include Response Length Instructions** is enabled, Talemate automatically appends a response length instruction as a fallback for those templates, ensuring the model always receives length guidance.

The instruction is derived from the configured max token count for the current generation:

| Token Budget | Instruction |
|---|---|
| ≤ 32 | Keep your response short and limited |
| ≤ 64 | 1 - 3 sentences |
| ≤ 128 | 1 paragraph |
| ≤ 256 | 2 paragraphs |
| ≤ 384 | 3 paragraphs |
| ≤ 512 | 4 paragraphs |
| ≤ 1024 | 6 paragraphs |
| ≤ 1536 | 9 paragraphs |
| > 1536 | Be as detailed and verbose as you need to be |

## Configuration

The setting is found in the client settings under the **General** tab.

1. Open the client settings by clicking on a client in the sidebar
2. Find the **Include Response Length Instructions** toggle
3. Toggle it on or off

This setting is **enabled by default**.

!!! tip "When to disable"
    You might want to disable this if you find the length instructions are too constraining for your use case, or if you prefer to let the model determine response length naturally. Some models may also respond poorly to explicit length constraints.
