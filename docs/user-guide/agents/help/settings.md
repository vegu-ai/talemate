# Settings

![Help agent settings](/talemate/img/0.39.0/help-agent-settings.png)

##### Response token budget

Maximum response length for help responses.

##### Tool call rounds

How many rounds of tool calls (documentation lookups, settings reads and updates) the help agent may perform before it must answer. Each round lets the agent use its tools and then continue with the results in context.

##### Tool calls per round

Maximum tool calls per round. When the connected client supports concurrent inference, the read-only calls in a round execute concurrently; settings changes always run one at a time.

##### Custom instructions

Extra instructions added to every help chat prompt.
