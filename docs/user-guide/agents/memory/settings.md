# Settings

![Memory agent settings](/talemate/img/0.40.0/memory-agent-settings.png)

##### Embeddings

Select which embedding to use. Embeddings themselves are managed through the [Embedding presets](/talemate/user-guide/agents/memory/embeddings).

!!! info "openAI"
    If you are using the OpenAI API, you will need to have an API key set under **Connections → API Keys**. See the [OpenAI API setup](/talemate/user-guide/apis/openai/) for setting up the OpenAI API key.

###### Device

The device to use for the embeddings. This can be either `cpu` or `cuda`.

!!! note "Switching device without a restart (0.37.0)"
    As of version 0.37.0, changing the device while a scene is loaded no longer requires restarting Talemate. The previously loaded model is released from ChromaDB's cache and any GPU memory it held is freed before the new device is applied. The scene's memory database is re-imported automatically — depending on the size of the model and scene this may take a moment.

## :material-filter-variant: Retrieval

How similarity results are ranked and merged before they reach a prompt. Nothing in this group adds a request; the cross-encoder runs a local model.

##### Recency weight

Newer results rank higher. Each result's score is its distance plus this weight times its age, where 0 is the newest and 1 the oldest result in the set (a result without a time counts as 0.5). Default 0.1; 0 turns the term off.

##### Diversity threshold

A result whose embedding is more similar than this (cosine) to one already selected is skipped, so the memory block does not repeat itself. Default 0.92; 1 turns the check off.

##### Entity lookup

When the recent lines name a character who is not in the scene (aliases from the world state's name mappings count), that character's description is fetched by id and placed ahead of the similarity results. On by default.

##### Similarity knowledge gate

When retrieval is filtered by a character's knowledge (see [World Editor -- Knowledge](/talemate/user-guide/world-editor/knowledge/)), a result outside their knowledge still passes if a fact they do know sits within the summarizer's *Fact near-duplicate distance* of it: someone told them later, and the retold fact sits next to the original. On by default.

##### Cross-encoder rerank

Scores the top 30 merged results against the queries with `cross-encoder/ms-marco-MiniLM-L-6-v2` and keeps the best 5. No request; the model runs on the embeddings device and is downloaded on first use. Off by default. When the model fails to load, retrieval carries on without the rerank and the agent shows the error in its details.
