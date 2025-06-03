# Rate Limiting

You can rate limit a client to N requests per minute.

![Rate limit](/talemate/img/0.30.0/client-ratelimit.png)

Once the limit is hit you will get a popup notification.

![Rate limit popup](/talemate/img/0.30.0/client-ratelimit-popup.png)

Here you can either choose to wait for the rate limit to reset, or to abort the generation.

If you abort the generation, the current stack of actions will be canceled and control will be given back to the user. This is essentially the same as Cancelling the generation through normal means.

If you chose to wait the notification will collapse to the top of the screen with a timer counting down the remaining time.

Clicking the notification will expand it again.

![Rate limit notification](/talemate/img/0.30.0/client-ratelimit-notification.png)