<!--- --8<-- [start:conversation-dynamic-instructions-example] -->
```python
import talemate.emit.async_signals as async_signals

# Append an extra system instruction every time the Conversation agent builds a prompt
async def add_custom_instruction(emission):
    emission.dynamic_instructions.append(
        "You are cursed to always answer in poetic verse. Keep it short."
    )

# Connect our handler (run once at application start-up)
async_signals.get("agent.conversation.inject_instructions").connect(add_custom_instruction)
```
<!--- --8<-- [end:conversation-dynamic-instructions-example] --> 

<!--- --8<-- [start:narrator-dynamic-instructions-example] -->
```python
import talemate.emit.async_signals as async_signals

# Append an extra system instruction every time the Narrator agent builds a prompt
async def add_custom_instruction(emission):
    emission.dynamic_instructions.append(
        "You are cursed to always answer in poetic verse. Keep it short."
    )

async_signals.get("agent.narrator.inject_instructions").connect(add_custom_instruction)
```
<!--- --8<-- [end:narrator-dynamic-instructions-example] --> 