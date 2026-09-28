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

## :material-filter-variant: Retrieval

![Memory agent Retrieval settings](/talemate/img/0.40.0/memory-retrieval-settings.png)

How similarity results are ranked and merged before they reach a prompt. Nothing in this group adds a request; the cross-encoder runs a local model. [Character knowledge: flow reference](/talemate/user-guide/world-editor/knowledge-how-it-works/#what-a-characters-reply-is-built-from) shows where the memories land in a reply.

Retrieval controls the order of search results through query relevance, the recency weight and the optional cross-encoder rerank.

##### Recency weight

Newer results rank higher. Each result's score is its distance plus this weight times its age, where 0 is the newest and 1 the oldest result in the set (a result without a time counts as 0.5). Default 0.1; 0 turns the term off.

##### Diversity threshold

A result whose embedding is more similar than this (cosine) to one already selected is skipped, so the memory block does not repeat itself. Default 0.92; 1 turns the check off.

##### Entity lookup

When the recent lines refer to a character who is not in the scene, that character's description is fetched from the memory store and placed ahead of the similarity results. On by default. Character knowledge still limits which descriptions the viewer may retrieve.

##### Use Decision Model for Entity Lookup

On by default. With a [decision model](/talemate/user-guide/app-settings/decision-model/) configured, entity lookup can recognize a character by pronoun, title or nickname, including names written in lower case. For example, "she takes the innkeeper's advice" can refer to Mara even without naming her. "I will go" need not refer to a character called Will.

This adds one short decision request per entity lookup, typically about 0.3–0.5 seconds depending on the provider. All off-stage candidates are checked together. Confident answers include or exclude each character; uncertain or failed answers use the original name match. That match requires capitalized aliases to appear as written and matches lower-case aliases without regard to case. With the option off or no decision model, only that matching is used.

The policy `memory.decision-entity-references` in **Prompts** controls the questions and confidence threshold. **Decision Log** shows the answers and fallback use. A confident answer can still select the wrong character; turn the option off if the name match better suits your scene.

##### Cross-encoder rerank

Scores the top 30 merged results against the queries with `cross-encoder/ms-marco-MiniLM-L-6-v2` and keeps the best 5. No request; the model runs on the embeddings device and is downloaded on first use. Off by default. When the model fails to load, retrieval carries on without the rerank and the agent shows the error in its details.
