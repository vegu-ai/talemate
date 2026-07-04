# Settings

![Help agent settings](/talemate/img/0.39.0/help-agent-settings.png)

##### Response token budget

Maximum response length for help responses.

##### Documentation lookup rounds

How many rounds of documentation lookups the help agent may perform before it must answer. Each round lets the agent consult the documentation and then continue with the results in context.

##### Lookups per round

Maximum documentation tool calls (search, read page, read section) per lookup round. When the connected client supports concurrent inference, the lookups in a round execute concurrently.

##### Custom instructions

Extra instructions added to every help chat prompt.
