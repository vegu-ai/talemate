# Concurrent Requests

Concurrent requests allows certain LLM clients to process multiple requests simultaneously rather than one at a time.

## What It Does

When enabled, operations that require multiple LLM queries will execute those queries in parallel instead of sequentially. This can significantly reduce the total time needed for these batch operations.

Operations that take advantage of this include:

- Visual/image prompt generation
- Image analysis batches run by the Analyze Images node, when analysis goes through a Talemate client
- Function-calling batches, where an AI response requests several tool calls at once (for example director chat query actions or help agent documentation lookups)
- Multi-query world state updates
- World state snapshots, which only run as true background tasks when the client can handle a concurrent request
- Tracked state reinforcement updates, when several are due in the same round
- Character progression checks across multiple characters — this one requires concurrent requests on **both** the World State agent's client and the Creator agent's client, since the proposed changes are generated through the Creator

Regular conversation and narration tasks are single generations and are unaffected.

## Supported Clients

Concurrent requests are available for the following hosted API clients, and are **enabled by default** for them:

- [Anthropic](/talemate/user-guide/clients/types/anthropic/)
- [OpenAI](/talemate/user-guide/clients/types/openai/)
- [Google Gemini](/talemate/user-guide/clients/types/google/)
- [MistralAI](/talemate/user-guide/clients/types/mistral/)
- [OpenRouter](/talemate/user-guide/clients/types/openrouter/)

It is also available for the [Pi Bridge](/talemate/user-guide/clients/types/pi-bridge/) client — each concurrent request runs its own pi instance — and the local [llama.cpp](/talemate/user-guide/clients/types/llamacpp/) client. Both are **off by default**: for Pi Bridge each request spins up its own pi instance, and for llama.cpp your `llama-server` must be started with enough parallel slots to handle more than one request at a time; otherwise the extra requests are simply queued and you will not see a speed-up.

Other local clients (KoboldCpp, etc.) do not support this feature.

## How to Toggle

For clients that support concurrent requests, you will see a toggle button in the client list. The button uses a parallel lines icon.

Click the button to enable or disable concurrent requests. When enabled, the button will appear highlighted.

You can also toggle this feature in the **Concurrency** section of the client editor on the [Clients settings page](client-configuration.md).

!!! note "Enabled by default since 0.40.0"
    For the five hosted API clients listed above, newly added clients have concurrent requests enabled by default since 0.40.0. Existing clients keep their stored value — because the setting has always been written into saved configurations, most existing clients keep it off until you enable it in the client editor or with the toggle button.

## Important Considerations

**Rate Limiting**: If you have [rate limiting](/talemate/user-guide/clients/rate-limiting/) configured for the client, concurrent requests may interact with the rate limiter in unexpected ways. If you experience issues, consider disabling concurrent requests or adjusting your rate limit settings.

## When to Disable This Feature

Concurrent requests are on by default for the hosted API clients and benefit the visual/image generation features, the director and help chats, and tracked world states.

Consider disabling concurrent requests for a client if:

- You have strict rate limits configured
- You experience any instability with the feature enabled
