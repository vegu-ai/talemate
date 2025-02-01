# Overview
The summarizer agent is responsible for summarizing the generated content and other analytical tasks.

### :material-forum: Dialogue summarization
Dialogue is summarized regularly to keep the conversation backlogs from getting too large.

### :material-layers: Layered history
Summarized dialogue is then further summarized into a layered history, where each layer represents a different level of detail.

Maintaining a layered history should theoretically allow to keep the entire history in the context, albeit at a lower level of detail the further back in history you go.

### :material-lightbulb: Scene analysis
As of version 0.29 the summarizer agent also has the ability to analyze the scene and provide this analysis to other agents for hopefully improve the quality of the generated content.

### :material-layers-search: Context investigation
Context investigations are when the summarizer agent will dig into the layers of the history to find context that may be relevant to the current scene.

!!! danger "This can result in many extra prompts being generated."
    This can be useful for generating more contextually relevant content, but can also result in a lot of extra prompts being generated.

    This is currently only used when the scene analysis with **deep analysis** is enabled.

!!! example "Experimental"
    The results of this are sort of hit and miss. It can be useful, but it can also be a bit of a mess and actually make the generated content worse. (e.g., context isn't correctly identified as being relevant, which A LOT of llms still seem to struggle with in my testing.)