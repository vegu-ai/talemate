# History

Will hold the archived history for the scene.

This historical archive is extended everytime the [Summarizer Agent](/talemate/user-guide/agents/summarizer/) summarizes the scene.

Summarization happens when a certain progress treshold is reached (tokens) or when a time passage event occurs.

All archived history is a potential candidate to be included in the context sent to the AI based on relevancy. This is handled by the [Memory Agent](/talemate/user-guide/agents/memory/).

You can use the **:material-refresh: Regenerate History** button to force a new summarization of the scene.

!!! warning
    If there has been lots of progress this will potentially take a long time to complete.