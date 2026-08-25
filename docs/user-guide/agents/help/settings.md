# Settings

![Help agent settings](/talemate/img/0.40.0/help-agent-settings.png)

##### Response token budget

Maximum response length for help responses.

##### Tool call rounds

How many rounds of tool calls (documentation lookups, settings, theme and template reads and updates) the help agent may perform before it must answer. Each round lets the agent use its tools and then continue with the results in context.

##### Tool calls per round

Maximum tool calls per round. When the connected client supports concurrent inference, the read-only calls in a round execute concurrently; settings, theme and template changes always run one at a time.

##### Custom instructions

Extra instructions added to every help chat prompt.

# Permissions

What the help chat is allowed to change. Reading is always available; both permissions are **off** by default. You can toggle them here or from the chips above the help chat itself — what the agent cannot do is grant them to itself.

##### Allow changes to settings

Lets the help chat change your application and agent settings when you ask it to. With it off, the setting-writing tools are not handed to the agent at all — it reads the setting and walks you through the change instead.

##### Allow changes to templates

Lets the help chat create and change world state templates, themes included. With it off, the template-writing tools are not handed to the agent at all.

Applying a theme is the one action that answers to both permissions: it replaces the message and markup styling in your appearance settings — italic, bold, visibility, own-color, and the backdrop's opacity and text shadow — and switches the active theme, so the agent gets it only when **Allow changes to settings** is on too. A color you set by hand under Appearance → Messages survives and keeps overriding the theme; clearing those is what **Restore from theme** is for.

!!! warning "Use a strong agentic reasoning model"
    Both permissions let an LLM write real changes on its own. A strong agentic reasoning model is highly recommended before turning one on — weaker models make destructive or unwanted changes.
