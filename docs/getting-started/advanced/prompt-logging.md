# Prompt Logging

Talemate can write every prompt it sends to a language model — together with the model's response and a bundle of metadata — to a JSON Lines file on disk. This is intended for debugging prompt issues, comparing behaviour across clients, or feeding collected prompts into offline analysis.

Prompt logging is **off by default** and is enabled with a single environment variable.

## Enabling

Set `TALEMATE_LOG_PROMPTS=1` before starting the server. Any truthy value enables logging (Talemate checks for the variable being set to a non-empty string).

#### :material-linux: Linux

Prefix the start command:

```bash
TALEMATE_LOG_PROMPTS=1 ./start.sh
```

Or when running manually:

```bash
TALEMATE_LOG_PROMPTS=1 uv run src/talemate/server/run.py runserver --host 0.0.0.0 --port 5050
```

#### :material-microsoft-windows: Windows

```batch
SET TALEMATE_LOG_PROMPTS=1
start.bat
```

## Disabling

Unset the variable (or set it to an empty string) and restart Talemate:

#### :material-linux: Linux

```bash
unset TALEMATE_LOG_PROMPTS
./start.sh
```

#### :material-microsoft-windows: Windows

```batch
SET TALEMATE_LOG_PROMPTS=
start.bat
```

## Output file

| Setting | Value |
|---------|-------|
| Path | `logs/prompt_log.jsonl` in the Talemate project root |
| Format | JSON Lines (one JSON object per line) |
| Write mode | Append — never truncated or rotated |
| Flush | Every record is flushed immediately, so partial runs are not lost |

The file is opened the first time a prompt is logged after startup and kept open for the lifetime of the process. It is **never rotated or truncated by Talemate**, so the file will keep growing as long as the variable is set. If you only need a short capture, enable the variable, reproduce the problem, disable it, and delete or move the file afterwards.

!!! info "`logs/prompt_log.jsonl` vs `logs/prompt_log.json`"
    The JSON-Lines file described here is written by the server while it runs.

    The similarly named `logs/prompt_log.json` is a separate, one-shot snapshot produced by the **Dump to file** button in the Debug Tools → Prompts tab and is independent of this environment variable.

## Record schema

Each line in `prompt_log.jsonl` is a single JSON object with the fields below. Field order inside the object is not guaranteed.

The server writes one terminal record per logical request, including failures and cancellations. Retries share its identity. The in-app viewers additionally receive active snapshots as the request progresses; a one-shot dump can therefore contain active records with null pending fields.

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | string | Unique identity of the logical request, shared by its lifecycle updates. |
| `status` | string | `active`, `completed`, `failed` or `cancelled`. JSONL records are terminal. |
| `started_at` | number | Unix timestamp when the request began. |
| `attempts` | int | Number of provider attempts, including retries. Zero while preparing or waiting to start. |
| `error` | string or null | Failure/cancellation information, or the current retry/error-dialog reason while active. |
| `kind` | string | Prompt kind identifier (e.g. `conversation`, `narrate_scene`, `summarize`). Corresponds to the template/system-prompt kind used for the call. |
| `prompt` | string | The full finalized prompt text sent to the model, after template rendering and any client-side formatting. |
| `response` | string or null | The full model response text, after stop-string trimming and smart-quote normalization; null if none was received. |
| `prompt_tokens` | int | Prompt token count. Uses the client's own counter unless the backend returned an explicit prompt-token count, in which case that value is preferred. |
| `response_tokens` | int | Response token count. Uses the backend-reported count when available, otherwise the client's tokenizer. |
| `client_name` | string | Name of the client that produced the prompt (as configured on the Clients screen). |
| `client_type` | string | Client type identifier (e.g. `openai`, `anthropic`, `koboldcpp`). |
| `time` | number or null | Elapsed seconds for the logical request, including preparation, waiting and retries; null while active. |
| `agent_stack` | list of strings | The agent call stack at the time of the prompt, outermost first. The final entry is the agent that actually issued the call (e.g. `["director", "conversation"]`). Empty if no agent context was active. |
| `generation_parameters` | object | Final generation parameters passed to the backend for this call (temperature, top-p, max tokens, etc. — contents vary by client type). |
| `inference_preset` | string or null | Name of the active inference preset, if any. |
| `preset_group` | string or null | Preset group the client is using, if any. |
| `reasoning` | string or null | The extracted reasoning / thinking trace for this response, when the client supports reasoning tokens. |
| `template_uid` | string or null | UID of the Jinja prompt template that produced the prompt. Useful for correlating a log line back to a specific template in the Prompt Manager. |

Token counts can be null when unavailable. Input tokens initially use the local estimate and are replaced by provider usage when supplied. Explicit zero counts remain zero. Response usage is pending during generation and unavailable after a failure or cancellation if the provider supplied none.

The record uses the same `PromptData` structure that Talemate emits over the websocket to populate the in-app [Debug Tools](../../user-guide/debug-tools.md#prompts) Prompts tab.

## Quick inspection

Because each line is a self-contained JSON object, the file works well with standard JSON tools. A few examples:

Pretty-print the last prompt:

```bash
tail -n 1 logs/prompt_log.jsonl | jq
```

Count prompts per agent (top of the stack):

```bash
jq -r '.agent_stack[-1] // "none"' logs/prompt_log.jsonl | sort | uniq -c
```

Extract only the prompts that took longer than five seconds:

```bash
jq 'select(.time > 5)' logs/prompt_log.jsonl
```

## Related

- [Debug Logging](debug-logging.md) — enable `DEBUG`-level logging and error-log file output with `TALEMATE_DEBUG=1`.
- [Debug Tools › Prompts](../../user-guide/debug-tools.md#prompts) — in-app viewer for the same prompt records, with a one-shot export button.
