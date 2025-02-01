# Settings

## General

General summarization settings.

![Summarizer agent general settings](/talemate/img/0.29.0/summarizer-general-settings.png)

##### Summarize to long term memory archive

Automatically summarize scene dialogue when the number of tokens in the history exceeds a threshold. This helps keep the context history from growing too large.

###### Token threshold

The number of tokens in the history that will trigger the summarization process.

###### Summarization method

The method used to summarize the scene dialogue. 

- `Balanced` - medium length summary
- `Short & Concise` - short summary
- `Lengthy & Detailed` - long summary
- `Factual list` - numbered list of events that transpired

###### Use preceeding summaries to strengthen context

Help the AI summarize by including the last few summaries as additional context. Some models may incorporate this context into the new summary directly, so if you find yourself with a bunch of similar history entries, try setting this to 0.

## Layered History

Settings for the layered history summarization.

Talemate `0.28.0` introduces a new feature called layered history summarization. This feature allows the AI to summarize the scene dialogue in layers, with each layer providing a different level of detail.

Not only does this allow to keep more context in the history, albeit with earlier layers containing less detail, but it also allows us to do history investgations to extract relevant information from the history during conversation and narration prompts.

Right now this is considered an experimental feature, and whether or not its feasible in the long term will depend on how well it works in practice.

![Summarizer agent layered history settings](/talemate/img/0.29.0/summarizer-layered-history-settings.png)

##### Enable layered history

Allows you to enable or disable the layered history summarization.

!!! note "Enabling this on big scenes"
    If you enable this on a big established scene, the next time the summarization agent runs, it will take a while to process the entire history and generate the layers.

##### Token threshold

The number of tokens in the layer that will trigger the summarization process to the next layer.

##### Maximum number of layers

The maximum number of layers that can be created. Raising this limit past 3 is likely to have dimishing returns. We have observed that usually by layer 3 you are down to single sentences for individual events, making it difficult to summarize further in a meaningful way.

##### Maximum tokens to process

Smaller LLMs may struggle with accurately summarizing long texts. This setting will split the text into chunks and summarize each chunk separately, then stitch them together in the next layer. If you're using a strong LLM (70B+), you can try setting this to be the same as the threshold.

Setting this higher than the token threshold does nothing.

##### Chunk size

During the summarization itself, the text will be furhter split into chunks where each chunk is summarized separately. This setting controls the size of those chunks. This is a character length setting, **NOT** token length.

##### Enable analyzation

Enables the analyzation of the chunks and their relationship to each other before summarization. This can greatly improve the quality of the summarization, but will also result in a bigger size requirement of the output.

##### Maximum response length

The maximum length of the response that the summarizer agent will generate.

!!! info "Analyzation requires a bigger length"
    If you enable analyzation, you should set this to be high enough so the response has room for both the analysis and the summary of all the chunks.

## Long term memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

## Scene Analysis

![Summarizer agent scene analysis settings](/talemate/img/0.29.0/summarizer-scene-analysis-settings.png)

When enabled scene analysis will be performed during conversation and narration tasks. This analysis will be used to provide additional context to other agents, which should hopefully improve the quality of the generated content.

##### Length of analysis

The maximum number of tokens for the response. (e.g., how long should the analysis be).

##### Conversation

Enable scene analysis for conversation tasks.

##### Narration

Enable scene analysis for narration tasks.

##### Deep analysis

Enable context investigations based on the initial analysis.

##### Max. content investigations

The maximum number of content investigations that can be performed. This is a safety feature to prevent the AI from going overboard with the investigations. The number here is to be taken per layer in the history. So if this is set to 1 and there are 2 layers, this will perform 2 investigations.

##### Cache analysis

Cache the analysis results for the scene. Enable this to prevent regenerationg the analysis when you regenerate the most recent output. 

!!! info
    This cache is anchored to the last message in the scene (excluding the current message). Editing that message will invalidate the cache.

## Context investigation

![Summarizer agent context investigation settings](/talemate/img/0.29.0/summarizer-context-investigation-settings.png)

When enabled, the summarizer agent will dig into the layers of the history to find context that may be relevant to the current scene.

!!! info
    This is currently only triggered during deep analysis as part of the scene analysis. Disabling context investigation will also disable the deep analysis.

##### Answer length

The maximum length of the answer that the AI will generate.

##### Update method

How to update the context with the new information.

- `Replace` - replace the context with the new information
- `Smart merge` - merge the new information with the existing context (uses another LLM promp to generate the merge)