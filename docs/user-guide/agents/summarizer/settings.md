# Settings

## General

General summarization settings.

![Summarizer agent general settings](/talemate/img/0.28.0/summarizer-general-settings.png)

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

![Summarizer agent layered history settings](/talemate/img/0.28.0/summarizer-layered-history-settings.png)

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