# Settings

![Narrator agent settings](/talemate/img/0.26.0/narrator-agent-settings.png)

##### Client

The text-generation client to use for conversation generation.


##### Generation Override

Checkbox that exposes further settings to configure the conversation agent generation.

###### Instructions

Extra instructions for the generation. This should be short and generic as it will be applied for all narration.

##### Auto Break Repetition

If checked and talemate detects a repetitive response (based on a threshold), it will automatically re-generate the resposne with increased randomness parameters.

##### Narrate time passaage

Whenever you indicate a passage of time using the [Scene tools](/user-guide/scenario-tools), the narrator will automatically narrate the passage of time.

##### Guide time narration via prompt

Wheneever you indicate a passage of time using the [Scene tools](/user-guide/scenario-tools), the narrator will wait for a prompt from you before narrating the passage of time.

This allows you to explain what happens during the passage of time.

##### Narrate after dialogue

Whenever a character speaks, the narrator will automatically narrate the scene after.