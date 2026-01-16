# Concurrent Requests (Experimental)

Concurrent requests is an experimental feature that allows certain LLM clients to process multiple requests simultaneously rather than one at a time.

## What It Does

When enabled, operations that require multiple LLM queries (such as generating image prompts) will execute those queries in parallel instead of sequentially. This can significantly reduce the total time needed for these batch operations.

**Currently, this feature is only used for visual prompt generation** (creating prompts for image generation). It is not applied to regular conversation or narration tasks.

## Supported Clients

Concurrent requests are available for the following hosted API clients:

- [Anthropic](/talemate/user-guide/clients/types/anthropic/)
- [OpenAI](/talemate/user-guide/clients/types/openai/)
- [Google Gemini](/talemate/user-guide/clients/types/google/)
- [OpenRouter](/talemate/user-guide/clients/types/openrouter/)

Local clients (KoboldCpp, llama.cpp, etc.) do not support this feature as they typically cannot handle concurrent inference requests.

## How to Enable

For clients that support concurrent requests, you will see a toggle button in the client list. The button uses a parallel lines icon.

Click the button to enable concurrent requests. When enabled, the button will appear highlighted.

You can also enable this feature through the client's settings dialog under the **Concurrency** tab.

## Important Considerations

!!! warning "Experimental Feature"
    This feature is experimental and may behave unpredictably in certain situations, particularly when rate limiting is in effect.

**Rate Limiting**: If you have [rate limiting](/talemate/user-guide/clients/rate-limiting/) configured for the client, concurrent requests may interact with the rate limiter in unexpected ways. If you experience issues, consider disabling concurrent requests or adjusting your rate limit settings.

## When to Use This Feature

Consider enabling concurrent requests if:

- You frequently use the visual/image generation features
- You want to reduce wait times during image prompt generation
- You are not experiencing rate limit issues with the API

You can safely leave this disabled if:

- You rarely use image generation features
- You have strict rate limits configured
- You experience any instability with the feature enabled
