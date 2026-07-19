# Auto Retry

By default, when a generation runs into a response issue — an empty response, an API rate limit, or a reasoning model that skipped its reasoning tokens — Talemate notifies you immediately with a dialog offering to retry, ignore, or cancel the generation.

You can instead configure a client to quietly retry a number of times on its own before you are notified. Each response issue has its own slider (0 to 5 retries, default 0 = notify immediately):

- **Empty Response** — the model returned an empty response. Retries fire immediately.
- **Rate Limited** — the API responded with HTTP 429. Retries wait progressively longer between attempts (2s, 4s, 8s, 16s, capped at 30s). Other API errors are not affected and still notify you immediately.
- **Missing Reasoning** — a reasoning model's response did not contain the expected reasoning pattern. Retries fire immediately. See [Reasoning](reasoning.md).

The **Empty Response** and **Rate Limited** sliders are on the **Advanced** tab of the [client configuration](client-configuration.md) dialog. The **Missing Reasoning** slider is on the **Reasoning** tab, next to the **Pattern Not Found Behavior** setting (it only appears when that setting is **Fail** — with **Ignore**, a missing pattern is never treated as an error).

While automatic retries are running, a notification at the top of the screen shows which client is retrying, why, and the attempt count. You can abort the generation from there at any time. If all automatic retries are exhausted, the usual generation error dialog appears.

!!! note "Rate limit responses vs. the Rate Limit slider"
    The **Rate Limited** retry slider reacts to the *API* telling Talemate to slow down (HTTP 429). This is separate from the [Rate Limit](rate-limiting.md) slider, which is Talemate's own client-side cap on requests per minute.
