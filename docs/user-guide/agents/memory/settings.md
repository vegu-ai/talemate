# Settings

![Memory agent settings](/talemate/img/0.40.0/memory-agent-settings.png)

##### Embeddings

Select which embedding to use. Embeddings themselves are managed through the [Embedding presets](/talemate/user-guide/agents/memory/embeddings).

!!! info "openAI"
    If you are using the OpenAI API, you will need to have an API key set under **Connections → API Keys**. See the [OpenAI API setup](/talemate/user-guide/apis/openai/) for setting up the OpenAI API key.

!!! info "openRouter"
    If you are using the OpenRouter API, you will need to have an API key set under **Connections → API Keys**. See the [OpenRouter API setup](/talemate/user-guide/apis/openrouter/) for setting up the OpenRouter API key.

###### Device

The device to use for the embeddings. This can be either `cpu` or `cuda`.

!!! note "Switching device without a restart (0.37.0)"
    As of version 0.37.0, changing the device while a scene is loaded no longer requires restarting Talemate. The previously loaded model is released from ChromaDB's cache and any GPU memory it held is freed before the new device is applied. The scene's memory database is re-imported automatically — depending on the size of the model and scene this may take a moment.

## :material-shape-outline: Topics

![Memory agent Topics settings](/talemate/img/0.40.0/memory-topics-settings.png)

Group recorded facts by subject to show each character's knowledge and find related memories. **Turn on for the Known facts by topic table and topic-based memory retrieval.** Grouping uses the embedding model, with no extra text-generation request.

The World Editor's Knowledge tab counts each character's known facts within each topic. Standard mode can also give the AI a [Topic knowledge overview](/talemate/user-guide/agents/conversation/settings/#topic-knowledge-overview); Character perspectives mode does not make those all/some/nothing assertions. Disabling Topics hides the table and overview.

For conversation memory searches, the closest matching topic contributes facts ahead of other search results. In Standard mode, these additions are selected and ranked by the Summarizer's [Fact chronology](/talemate/user-guide/agents/summarizer/settings/#fact-chronology) rules. Character perspectives keeps the topic's existing audience-fact order, applying chronology only to eligibility and relative time markers. Context Database searches and node queries do not get this addition. Topics take their names from the most frequent subjects in their facts.

##### Facts between topic updates

Regroup topics when the fact count changes by this many (default 20), up or down. **Lower for more frequent updates; raise to regroup less often.** This controls how often topics are updated, not how many topics you get.

Editing, deleting or regenerating facts, or changing the embedding preset, updates topics immediately. Topics are also built on load when facts exist but no topics are stored. The memory agent rebuilds the information it needs for topic matching when loading a story.

##### Topic similarity

Set how closely facts must match to share a topic, and how closely a topic must match a memory search. **Raise for tighter, smaller groups; lower for broader groups.** A higher value also requires a closer match before a topic contributes memories to a search. Results depend on the facts and embedding model.

**0 = use embedding preset** (the default), shown at the slider. It uses the [embedding preset's Topic Threshold](/talemate/user-guide/agents/memory/embeddings/#topic-threshold), currently 0.50 in the shipped presets. Zero does not disable topics. Choose a value above zero to set a custom threshold.

If most facts land in one topic, try raising the value. If nearly every fact has its own topic, try lowering it. The memory agent logs a warning for these cases. Internally, each fact joins the first topic whose first fact is similar enough; one refinement pass then moves facts to the closest topic center.

## :material-filter-variant: Retrieval

![Memory agent Retrieval settings](/talemate/img/0.40.0/memory-retrieval-settings.png)

How similarity results are ranked and merged before they reach a prompt. Nothing in this group adds a request; the cross-encoder runs a local model. [Character knowledge: flow reference](/talemate/user-guide/world-editor/knowledge-how-it-works/#what-a-characters-reply-is-built-from) shows where the memories land in a reply.

Retrieval controls the order of search results through query relevance, the recency weight and the optional cross-encoder rerank. The Summarizer's [Fact chronology](/talemate/user-guide/agents/summarizer/settings/#fact-chronology) rules remove ineligible facts and add relative time markers while preserving that retrieval order. A fact's chronology score does not move it ahead of a more relevant retrieved result. Character knowledge filtering still determines access before facts can enter a character's prompt.

##### Recency weight

Newer results rank higher. Each result's score is its distance plus this weight times its age, where 0 is the newest and 1 the oldest result in the set (a result without a time counts as 0.5). Default 0.1; 0 turns the term off.

##### Diversity threshold

A result whose embedding is more similar than this (cosine) to one already selected is skipped, so the memory block does not repeat itself. A fresher fact keeps the earliest selected slot and replaces every older near-copy it overlaps. This also applies to results admitted by Match known facts. Default 0.92; 1 turns the check off.

##### Entity lookup

When the recent lines name a character who is not in the scene (aliases from the world state's name mappings count), that character's description is fetched from the memory store and placed ahead of the similarity results. A name that carries a capital must appear as written, so "Will" is not found in "I will go"; an alias that is lower-case in the name mappings matches whatever the case. On by default.

##### Match known facts

Allow a memory of an event the character missed when it closely matches a fact they know. **Turn on to recognize retold information; turn off for stricter access filtering.** On by default.

Available in **Standard** mode when retrieval is limited to a character's knowledge. Uses the Summarizer's [Fact matching tolerance](/talemate/user-guide/agents/summarizer/settings/#fact-matching-tolerance): raise that tolerance to accept looser matches, or lower it for closer matches. This cannot override an entry's **Known by** setting or a **Block** rule. See [Knowledge](/talemate/user-guide/world-editor/knowledge/).

Hidden and unused in **Character perspectives** mode, where similarity ranks available memories and never grants access to unavailable ones.

##### Cross-encoder rerank

Scores the top 30 merged results against the queries with `cross-encoder/ms-marco-MiniLM-L-6-v2` and keeps the best 5. No request; the model runs on the embeddings device and is downloaded on first use. Off by default. When the model fails to load, retrieval carries on without the rerank and the agent shows the error in its details.
