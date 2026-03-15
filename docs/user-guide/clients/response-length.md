# Response Length Enforcement

!!! info "New in 0.36.0"
    Response length enforcement is now configurable per client with four modes.

Talemate can control response length in two ways: by capping the token budget sent to the API (`max_tokens`) and by appending human-readable length instructions to the prompt. The **Response Length Enforcement** setting lets you choose which of these mechanisms to use.

## How It Works

Many prompt templates already include response length instructions inline (e.g., "The length of your response must fit within 2 paragraphs"). However, some templates do not. When the selected mode includes instructions, Talemate automatically appends a response length instruction as a fallback for those templates, ensuring the model always receives length guidance.

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

## Modes

| Mode | Token limit | Instructions | Description |
|---|---|---|---|
| **Limit tokens and send instructions** | Yes | Yes | The default. Limits the API token budget and appends length instructions to prompts that don't already include them. |
| **Limit tokens** | Yes | No | Limits the API token budget but does not append any length instructions. |
| **Send instructions** | No | Yes | Appends length instructions but does not limit the API token budget, leaving it up to the API. |
| **Uncapped** | No | No | Neither limits tokens nor sends instructions. |

!!! warning "Uncapped"
    Not recommended. Any generation length settings will be ignored when this is selected.

## Configuration

The setting is found in the client settings under the **General** tab.

1. Open the client settings by clicking on a client in the sidebar
2. Find the **Response Length Enforcement** dropdown
3. Select the desired mode

This setting defaults to **Limit tokens and send instructions**.
